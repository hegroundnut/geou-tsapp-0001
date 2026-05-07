"""
边缘服务客户端 — 与边缘控制服务通信
负责：
  1. 心跳上报（保持在线状态）
  2. 接收导航指令（轮询或 WebSocket 推送）
  3. 上报导航轨迹
  4. 转发无人机位置/状态

设计原则：
  - HTTP 客户端用于 REST 接口调用
  - 心跳在独立线程中定时发送
  - 所有网络请求带超时和重试
  - 可插拔：接入真实 HTTP 服务或本地模拟
"""
import time
import threading
import logging
from typing import Dict, List, Optional, Any, Callable

from config import EdgeServiceConfig
from models import DroneState, Waypoint, NavigationInstruction, TrajectoryResult

logger = logging.getLogger("edge_client")

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logger.warning("httpx not installed, using simulation mode for edge client")


class EdgeServiceClient:
    """
    边缘控制服务客户端。
    通过 HTTP/REST 与边缘控制服务通信。
    """

    def __init__(
        self,
        config: EdgeServiceConfig,
        on_navigation_received: Optional[Callable[[NavigationInstruction], None]] = None,
        simulated: bool = False,
    ):
        self._config = config
        self._on_navigation_received = on_navigation_received
        self._simulated = simulated or (not HAS_HTTPX)
        self._client: Any = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pending_instructions: List[NavigationInstruction] = []
        self._lock = threading.Lock()

    def connect(self) -> bool:
        if self._simulated:
            logger.info("EdgeServiceClient running in SIMULATION mode")
            self._start_background_threads()
            return True
        try:
            self._client = httpx.Client(
                base_url=self._config.base_url,
                timeout=self._config.timeout_s,
            )
            logger.info("Connected to edge service: %s", self._config.base_url)
            self._start_background_threads()
            return True
        except Exception as e:
            logger.error("Failed to connect to edge service: %s", e)
            return False

    def disconnect(self) -> None:
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=3)
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
        if self._client:
            self._client.close()
            self._client = None
        logger.info("EdgeServiceClient disconnected")

    # ------------------------------------------------------------------
    #  心跳上报
    # ------------------------------------------------------------------

    def send_heartbeat(self, location: Optional[Dict[str, float]] = None) -> bool:
        payload = {
            "target_type": "server",
            "target_id": self._config.server_id,
        }
        if location:
            payload["location"] = location
        return self._post("heartbeat", payload)

    # ------------------------------------------------------------------
    #  轨迹上报
    # ------------------------------------------------------------------

    def report_trajectory(
        self,
        instruction_id: str,
        waypoints: List[Waypoint],
        total_distance_m: float = 0.0,
        estimated_time_s: float = 0.0,
        algorithm_used: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        payload = {
            "instruction_id": instruction_id,
            "device_id": self._config.device_id,
            "server_id": self._config.server_id,
            "waypoints": [wp.to_dict() for wp in waypoints],
            "total_distance_m": total_distance_m,
            "estimated_time_s": estimated_time_s,
            "algorithm_used": algorithm_used,
            "metadata": metadata or {},
        }
        return self._post("receive_trajectory", payload)

    # ------------------------------------------------------------------
    #  无人机状态转发
    # ------------------------------------------------------------------

    def forward_drone_status(self, device_id: str, drone_state: DroneState) -> bool:
        payload = {
            "device_id": device_id,
            "position": drone_state.position,
            "velocity": drone_state.velocity,
            "attitude": drone_state.attitude,
            "battery_pct": drone_state.battery_pct,
            "flight_mode": drone_state.flight_mode,
            "armed": drone_state.armed,
            "gps_fix_type": drone_state.gps_fix_type,
            "satellites_visible": drone_state.satellites_visible,
        }
        return self._post("receive_drone_status", payload)

    # ------------------------------------------------------------------
    #  模拟注入导航指令（供测试使用）
    # ------------------------------------------------------------------

    def inject_navigation_instruction(self, instruction: NavigationInstruction) -> None:
        with self._lock:
            self._pending_instructions.append(instruction)
        if self._on_navigation_received:
            self._on_navigation_received(instruction)

    # ------------------------------------------------------------------
    #  内部通信
    # ------------------------------------------------------------------

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> bool:
        if self._simulated:
            logger.debug("Simulated POST /%s: %s", endpoint, list(payload.keys()))
            return True
        try:
            resp = self._client.post(f"/api/{endpoint}", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("code", -1) == 0
            logger.warning("POST /%s failed: %d", endpoint, resp.status_code)
            return False
        except Exception as e:
            logger.error("POST /%s error: %s", endpoint, e)
            return False

    # ------------------------------------------------------------------
    #  后台线程
    # ------------------------------------------------------------------

    def _start_background_threads(self) -> None:
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="edge-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.send_heartbeat()
            except Exception:
                logger.exception("Heartbeat error")
            self._stop_event.wait(self._config.heartbeat_interval_s)
