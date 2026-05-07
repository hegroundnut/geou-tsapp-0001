"""
CloudEdgeManager 数据模型定义
定义服务器节点、边缘设备、任务记录、流通道等核心数据结构
"""
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


# ---------------------------------------------------------------------------
#  枚举类型
# ---------------------------------------------------------------------------

class ServerStatus(str, Enum):
    ACTIVE = "active"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    PLANNING = "planning"
    ERROR = "error"


class TaskStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    PREEMPTED = "preempted"


class ChannelType(str, Enum):
    SIGNALING = "signaling"   # HTTP/WebSocket — 控制信令（路径下发、状态上报等）
    MEDIA = "media"           # WebRTC/UDP — 高带宽媒体流（视频、激光雷达点云等）


# ---------------------------------------------------------------------------
#  服务器节点
# ---------------------------------------------------------------------------

@dataclass
class ServerNode:
    server_id: str
    ip_address: str
    capacity: int
    tags: List[str] = field(default_factory=list)
    status: ServerStatus = ServerStatus.ACTIVE
    current_load: int = 0
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def available_slots(self) -> int:
        return max(0, self.capacity - self.current_load)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_id": self.server_id,
            "ip_address": self.ip_address,
            "capacity": self.capacity,
            "tags": list(self.tags),
            "status": self.status.value,
            "current_load": self.current_load,
            "available_slots": self.available_slots,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
#  边缘设备
# ---------------------------------------------------------------------------

@dataclass
class EdgeDevice:
    device_id: str
    hardware_type: str
    is_simulated: bool = False
    supported_streams: List[str] = field(default_factory=list)
    group_id: str = "default"
    status: DeviceStatus = DeviceStatus.ONLINE
    last_active_time: float = field(default_factory=time.time)
    assigned_server_id: Optional[str] = None
    active_task_id: Optional[str] = None
    location: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hardware_type": self.hardware_type,
            "is_simulated": self.is_simulated,
            "supported_streams": list(self.supported_streams),
            "group_id": self.group_id,
            "status": self.status.value,
            "last_active_time": self.last_active_time,
            "assigned_server_id": self.assigned_server_id,
            "active_task_id": self.active_task_id,
            "location": dict(self.location),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
#  任务记录
# ---------------------------------------------------------------------------

@dataclass
class TaskRecord:
    task_id: str
    device_id: str
    server_id: str
    algorithm: str
    frequency_hz: int
    enable_video_stream: bool = False
    stream_port: Optional[int] = None
    custom_payloads: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.RUNNING
    created_at: float = field(default_factory=time.time)
    stopped_at: Optional[float] = None
    stop_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "device_id": self.device_id,
            "server_id": self.server_id,
            "algorithm": self.algorithm,
            "frequency_hz": self.frequency_hz,
            "enable_video_stream": self.enable_video_stream,
            "stream_port": self.stream_port,
            "custom_payloads": dict(self.custom_payloads),
            "status": self.status.value,
            "created_at": self.created_at,
            "stopped_at": self.stopped_at,
            "stop_reason": self.stop_reason,
        }

    @staticmethod
    def generate_task_id() -> str:
        return f"task_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
#  流通道
# ---------------------------------------------------------------------------

@dataclass
class StreamChannel:
    channel_id: str
    device_id: str
    channel_type: ChannelType
    protocol: str            # "websocket", "webrtc", "http", "udp"
    port: int
    stream_type: str         # "video", "lidar_point_cloud", "location", "path"
    active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "device_id": self.device_id,
            "channel_type": self.channel_type.value,
            "protocol": self.protocol,
            "port": self.port,
            "stream_type": self.stream_type,
            "active": self.active,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def generate_channel_id() -> str:
        return f"ch_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
#  任务结果（通用 — 服务器向边缘服务提交的计算结果）
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    """
    通用任务结果。
    服务器完成计算后提交，result_type 标识结果类型（如 trajectory、analysis 等），
    payload 为具体数据（格式由调用方自定义，边缘服务不解析内部结构）。
    """
    result_id: str
    task_id: str
    device_id: str
    server_id: str
    result_type: str = ""           # e.g. "trajectory", "detection", "analysis"
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
            "server_id": self.server_id,
            "result_type": self.result_type,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def generate_result_id() -> str:
        return f"res_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
#  设备遥测（通用 — 设备/服务器向边缘服务上报的遥测数据）
# ---------------------------------------------------------------------------

@dataclass
class DeviceTelemetry:
    """
    通用设备遥测。
    telemetry_type 标识遥测类型（如 position、drone_status、sensor 等），
    data 为具体遥测数据（格式由上报方自定义，边缘服务只存储和转发）。
    """
    device_id: str
    telemetry_type: str = ""        # e.g. "position", "drone_status", "sensor", "lidar"
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "telemetry_type": self.telemetry_type,
            "data": dict(self.data),
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }
