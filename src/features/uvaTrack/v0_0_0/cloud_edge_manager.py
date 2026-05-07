"""
CloudEdgeManager — 云边协同管控核心调度器
负责：
  1. 服务器节点池管理（增删查 + 状态维护）
  2. 边缘设备管理（增删查 + 模拟设备 + 心跳状态）
  3. 任务调度（设备↔服务器绑定、路径规划下发、任务抢占与停止）
  4. 流通道管理（信令/媒体隔离）
  5. 灵活扩展（custom_payloads、自定义计算插件等）
"""
import time
import threading
import logging
from typing import Dict, List, Optional, Any, Callable

from models import (
    ServerNode,
    ServerStatus,
    EdgeDevice,
    DeviceStatus,
    TaskRecord,
    TaskStatus,
    ChannelType,
    TaskResult,
    DeviceTelemetry,
)
from stream_registry import StreamRegistry
from heartbeat import HeartbeatMonitor

logger = logging.getLogger("cloud_edge_manager")


class CloudEdgeManager:
    """
    单例管理器，维护服务器表、设备表、任务表、流通道表。
    所有公开方法均线程安全。
    """

    _instance: Optional["CloudEdgeManager"] = None
    _init_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "CloudEdgeManager":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        heartbeat_interval: float = 5.0,
        device_timeout: float = 15.0,
        server_timeout: float = 30.0,
        on_task_stopped: Optional[Callable[[TaskRecord], None]] = None,
    ):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._lock = threading.RLock()
        self._servers: Dict[str, ServerNode] = {}
        self._devices: Dict[str, EdgeDevice] = {}
        self._tasks: Dict[str, TaskRecord] = {}       # task_id -> TaskRecord
        self._device_tasks: Dict[str, str] = {}        # device_id -> task_id

        self._task_results: Dict[str, List[TaskResult]] = {}   # task_id -> [TaskResult, ...]
        self._device_telemetry: Dict[str, DeviceTelemetry] = {}  # device_id -> latest DeviceTelemetry

        self._stream_registry = StreamRegistry()
        self._heartbeat = HeartbeatMonitor(
            self,
            check_interval_s=heartbeat_interval,
            device_timeout_s=device_timeout,
            server_timeout_s=server_timeout,
        )
        self._on_task_stopped = on_task_stopped

        self._heartbeat.start()
        logger.info("CloudEdgeManager initialized")

    # ==================================================================
    #  服务器管理
    # ==================================================================

    def add_server(
        self,
        server_id: str,
        ip_address: str,
        capacity: int,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if server_id in self._servers:
                return {
                    "code": -1,
                    "msg": f"服务器 {server_id} 已存在",
                    "data": {},
                }
            server = ServerNode(
                server_id=server_id,
                ip_address=ip_address,
                capacity=int(capacity),
                tags=list(tags) if tags else [],
                metadata=dict(metadata) if metadata else {},
            )
            self._servers[server_id] = server
            logger.info("Server added: %s (%s)", server_id, ip_address)
            return {
                "code": 0,
                "msg": "success",
                "data": server.to_dict(),
            }

    def remove_server(
        self,
        server_id: str,
        force_stop: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            server = self._servers.get(server_id)
            if not server:
                return {
                    "code": -1,
                    "msg": f"服务器 {server_id} 不存在",
                    "data": {},
                }
            affected_tasks = self._get_tasks_on_server(server_id)
            if affected_tasks and not force_stop:
                return {
                    "code": -2,
                    "msg": f"服务器 {server_id} 上尚有 {len(affected_tasks)} 个运行中任务，"
                    f"请先停止任务或使用 force_stop=true",
                    "data": {
                        "running_tasks": [t.task_id for t in affected_tasks]
                    },
                }
            stopped_tasks = []
            for task in affected_tasks:
                self._stop_task_internal(task.task_id, reason="server_removed")
                stopped_tasks.append(task.task_id)

            del self._servers[server_id]
            logger.info("Server removed: %s (force=%s)", server_id, force_stop)
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "server_id": server_id,
                    "stopped_tasks": stopped_tasks,
                },
            }

    def list_servers(
        self,
        filter_by_status: str = "all",
    ) -> Dict[str, Any]:
        with self._lock:
            servers = list(self._servers.values())
            if filter_by_status != "all":
                try:
                    target_status = ServerStatus(filter_by_status)
                    servers = [s for s in servers if s.status == target_status]
                except ValueError:
                    pass
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "total": len(servers),
                    "servers": [s.to_dict() for s in servers],
                },
            }

    def refresh_server_heartbeat(self, server_id: str) -> bool:
        with self._lock:
            server = self._servers.get(server_id)
            if not server:
                return False
            server.last_heartbeat = time.time()
            if server.status == ServerStatus.OFFLINE:
                server.status = ServerStatus.ACTIVE
            return True

    def mark_server_offline(self, server_id: str, reason: str = "") -> None:
        with self._lock:
            server = self._servers.get(server_id)
            if not server:
                return
            server.status = ServerStatus.OFFLINE
            for task in self._get_tasks_on_server(server_id):
                self._stop_task_internal(task.task_id, reason=reason or "server_offline")
            logger.warning("Server %s marked offline: %s", server_id, reason)

    # ==================================================================
    #  设备管理
    # ==================================================================

    def add_device(
        self,
        device_id: str,
        hardware_type: str,
        is_simulated: bool = False,
        supported_streams: Optional[List[str]] = None,
        group_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if device_id in self._devices:
                return {
                    "code": -1,
                    "msg": f"设备 {device_id} 已存在",
                    "data": {},
                }
            device = EdgeDevice(
                device_id=device_id,
                hardware_type=hardware_type,
                is_simulated=bool(is_simulated),
                supported_streams=list(supported_streams) if supported_streams else [],
                group_id=group_id,
                metadata=dict(metadata) if metadata else {},
            )
            self._devices[device_id] = device
            logger.info(
                "Device added: %s (hw=%s, simulated=%s)",
                device_id,
                hardware_type,
                is_simulated,
            )
            return {
                "code": 0,
                "msg": "success",
                "data": device.to_dict(),
            }

    def remove_device(self, device_id: str) -> Dict[str, Any]:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return {
                    "code": -1,
                    "msg": f"设备 {device_id} 不存在",
                    "data": {},
                }
            if device.active_task_id:
                self._stop_task_internal(
                    device.active_task_id, reason="device_removed"
                )
            closed_channels = self._stream_registry.close_device_channels(device_id)
            del self._devices[device_id]
            logger.info(
                "Device removed: %s (closed %d channels)", device_id, closed_channels
            )
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "device_id": device_id,
                    "closed_channels": closed_channels,
                },
            }

    def list_devices(
        self,
        group_id: str = "all",
    ) -> Dict[str, Any]:
        with self._lock:
            devices = list(self._devices.values())
            if group_id != "all":
                devices = [d for d in devices if d.group_id == group_id]
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "total": len(devices),
                    "devices": [d.to_dict() for d in devices],
                },
            }

    def refresh_device_heartbeat(
        self,
        device_id: str,
        location: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return False
            device.last_active_time = time.time()
            if location:
                device.location = location
            if device.status == DeviceStatus.OFFLINE:
                device.status = DeviceStatus.ONLINE
            return True

    def mark_device_offline(self, device_id: str, reason: str = "") -> None:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return
            device.status = DeviceStatus.OFFLINE
            if device.active_task_id:
                self._stop_task_internal(
                    device.active_task_id, reason=reason or "device_offline"
                )
            self._stream_registry.close_device_channels(device_id)
            logger.warning("Device %s marked offline: %s", device_id, reason)

    # ==================================================================
    #  任务调度
    # ==================================================================

    def assign_and_start_task(
        self,
        device_id: str,
        server_id: str,
        task_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        task_config = task_config or {}
        algorithm = task_config.get("algorithm", "default")
        frequency_hz = int(task_config.get("frequency_hz", 10))
        enable_video_stream = bool(task_config.get("enable_video_stream", False))
        stream_port = task_config.get("stream_port")
        custom_payloads = task_config.get("custom_payloads", {})

        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return {"code": -1, "msg": f"设备 {device_id} 不存在", "data": {}}

            server = self._servers.get(server_id)
            if not server:
                return {"code": -1, "msg": f"服务器 {server_id} 不存在", "data": {}}

            if server.status != ServerStatus.ACTIVE:
                return {
                    "code": -2,
                    "msg": f"服务器 {server_id} 当前不可用 (status={server.status.value})",
                    "data": {},
                }

            if server.available_slots <= 0:
                return {
                    "code": -3,
                    "msg": f"服务器 {server_id} 已满载 (load={server.current_load}/{server.capacity})",
                    "data": {},
                }

            # 任务抢占：若设备已有运行中任务则先停止旧任务
            preempted_task_id = None
            if device.active_task_id:
                preempted_task_id = device.active_task_id
                self._stop_task_internal(
                    device.active_task_id, reason="task_preempted"
                )

            task_id = TaskRecord.generate_task_id()
            task = TaskRecord(
                task_id=task_id,
                device_id=device_id,
                server_id=server_id,
                algorithm=algorithm,
                frequency_hz=frequency_hz,
                enable_video_stream=enable_video_stream,
                stream_port=int(stream_port) if stream_port else None,
                custom_payloads=dict(custom_payloads) if custom_payloads else {},
            )
            self._tasks[task_id] = task
            self._device_tasks[device_id] = task_id

            device.assigned_server_id = server_id
            device.active_task_id = task_id
            device.status = DeviceStatus.PLANNING

            server.current_load += 1

            # 注册信令通道
            signaling_info = None
            self._stream_registry.close_device_channels(device_id)
            sig_ch = self._stream_registry.register_channel(
                device_id=device_id,
                channel_type=ChannelType.SIGNALING,
                protocol="websocket",
                port=int(stream_port) + 1 if stream_port else 0,
                stream_type="control",
                metadata={"server_id": server_id, "task_id": task_id},
            )
            if sig_ch:
                signaling_info = sig_ch.to_dict()

            # 注册媒体通道（若启用视频流）
            media_info = None
            if enable_video_stream and stream_port:
                media_ch = self._stream_registry.register_channel(
                    device_id=device_id,
                    channel_type=ChannelType.MEDIA,
                    protocol="webrtc",
                    port=int(stream_port),
                    stream_type="video",
                    metadata={"server_id": server_id, "task_id": task_id},
                )
                if media_ch:
                    media_info = media_ch.to_dict()

            logger.info(
                "Task %s started: device=%s -> server=%s (algo=%s, freq=%dHz)",
                task_id,
                device_id,
                server_id,
                algorithm,
                frequency_hz,
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "task": task.to_dict(),
                    "preempted_task_id": preempted_task_id,
                    "signaling_channel": signaling_info,
                    "media_channel": media_info,
                },
            }

    def stop_task(
        self,
        device_id: str,
        reason: str = "user_manual_stop",
    ) -> Dict[str, Any]:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return {"code": -1, "msg": f"设备 {device_id} 不存在", "data": {}}

            if not device.active_task_id:
                return {
                    "code": -2,
                    "msg": f"设备 {device_id} 当前没有运行中的任务",
                    "data": {},
                }

            task = self._stop_task_internal(device.active_task_id, reason=reason)
            if not task:
                return {"code": -3, "msg": "任务停止异常", "data": {}}

            return {
                "code": 0,
                "msg": "success",
                "data": task.to_dict(),
            }

    # ==================================================================
    #  内部辅助方法
    # ==================================================================

    def _stop_task_internal(
        self,
        task_id: str,
        reason: str = "unknown",
    ) -> Optional[TaskRecord]:
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.RUNNING:
            return task

        task.status = (
            TaskStatus.PREEMPTED if reason == "task_preempted" else TaskStatus.STOPPED
        )
        task.stopped_at = time.time()
        task.stop_reason = reason

        device = self._devices.get(task.device_id)
        if device:
            device.active_task_id = None
            device.assigned_server_id = None
            if device.status == DeviceStatus.PLANNING:
                device.status = DeviceStatus.ONLINE

        server = self._servers.get(task.server_id)
        if server and server.current_load > 0:
            server.current_load -= 1

        self._stream_registry.close_device_channels(task.device_id)
        self._device_tasks.pop(task.device_id, None)

        if self._on_task_stopped:
            try:
                self._on_task_stopped(task)
            except Exception:
                logger.exception("on_task_stopped callback error")

        logger.info("Task %s stopped: reason=%s", task_id, reason)
        return task

    def _get_tasks_on_server(self, server_id: str) -> List[TaskRecord]:
        return [
            t
            for t in self._tasks.values()
            if t.server_id == server_id and t.status == TaskStatus.RUNNING
        ]

    # ==================================================================
    #  供心跳监控器调用的只读辅助
    # ==================================================================

    def get_all_devices(self) -> List[EdgeDevice]:
        with self._lock:
            return list(self._devices.values())

    def get_all_servers(self) -> List[ServerNode]:
        with self._lock:
            return list(self._servers.values())

    # ==================================================================
    #  扩展查询接口
    # ==================================================================

    def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            info = device.to_dict()
            info["stream_channels"] = self._stream_registry.get_channels_by_device(
                device_id
            )
            if device.active_task_id:
                task = self._tasks.get(device.active_task_id)
                info["active_task"] = task.to_dict() if task else None
            telemetry = self._device_telemetry.get(device_id)
            info["latest_telemetry"] = telemetry.to_dict() if telemetry else None
            return info

    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            info = task.to_dict()
            results = self._task_results.get(task_id, [])
            info["results"] = [r.to_dict() for r in results]
            return info

    def get_stream_channels(self, device_id: str) -> List[Dict[str, Any]]:
        return self._stream_registry.get_channels_by_device(device_id)

    # ==================================================================
    #  通用数据交互（设备无关 — 任何服务器/设备均可使用）
    # ==================================================================

    def submit_task_result(
        self,
        task_id: str,
        result_type: str,
        payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"code": -1, "msg": f"任务 {task_id} 不存在", "data": {}}

            result = TaskResult(
                result_id=TaskResult.generate_result_id(),
                task_id=task_id,
                device_id=task.device_id,
                server_id=task.server_id,
                result_type=result_type,
                payload=dict(payload) if payload else {},
                metadata=dict(metadata) if metadata else {},
            )
            self._task_results.setdefault(task_id, []).append(result)
            logger.info(
                "Task result submitted: %s type=%s task=%s",
                result.result_id,
                result_type,
                task_id,
            )
            return {
                "code": 0,
                "msg": "success",
                "data": result.to_dict(),
            }

    def update_device_telemetry(
        self,
        device_id: str,
        telemetry_type: str,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return {"code": -1, "msg": f"设备 {device_id} 不存在", "data": {}}

            telemetry = DeviceTelemetry(
                device_id=device_id,
                telemetry_type=telemetry_type,
                data=dict(data) if data else {},
                metadata=dict(metadata) if metadata else {},
            )
            self._device_telemetry[device_id] = telemetry

            position = (data or {}).get("position")
            if position and isinstance(position, dict):
                device.location = dict(position)
            device.last_active_time = time.time()

            logger.info(
                "Telemetry updated: device=%s type=%s",
                device_id,
                telemetry_type,
            )
            return {
                "code": 0,
                "msg": "success",
                "data": telemetry.to_dict(),
            }

    def shutdown(self) -> None:
        self._heartbeat.stop()
        with self._lock:
            running_tasks = [
                t for t in self._tasks.values() if t.status == TaskStatus.RUNNING
            ]
            for task in running_tasks:
                self._stop_task_internal(task.task_id, reason="system_shutdown")
        logger.info("CloudEdgeManager shutdown complete")
