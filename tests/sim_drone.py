"""
虚拟无人机 (SimDrone)
模拟无人机飞行：接收航点 → 模拟飞行 → 通过 update_device_telemetry 上报遥测。
通过 CloudEdgeManager 的通用接口通信，替换为真机时只需切换为 MAVLink 连接。

替换指南：
  真机上运行 brain_box/mavlink_adapter.py（MAVLink 版），
  遥测数据格式与本模拟器完全一致（drone_status telemetry_type）。
"""
import math
import time
import random
import logging
import threading
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger("sim_drone")


class SimDrone:
    """
    虚拟无人机。

    模拟功能：
      - GPS 定位（lat/lng/alt）
      - 速度向量（vx/vy/vz）
      - 姿态（roll/pitch/yaw）
      - 电池电量（线性消耗）
      - 航点飞行（接收航点列表后逐点飞行）
      - 遥测上报（通过回调 → 映射到 update_device_telemetry）
    """

    def __init__(
        self,
        device_id: str,
        telemetry_callback: Optional[Callable[[str, str, Dict, Optional[Dict]], Any]] = None,
        telemetry_interval_s: float = 1.0,
        initial_position: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            device_id: 本设备在边缘服务中的注册 ID
            telemetry_callback: 上报遥测的回调 (device_id, telemetry_type, data, metadata)
                                对应 CloudEdgeManager.update_device_telemetry
            telemetry_interval_s: 遥测上报周期（秒）
            initial_position: 初始位置 {"lat": ..., "lng": ..., "alt": ...}
        """
        self.device_id = device_id
        self._telemetry_callback = telemetry_callback
        self._telemetry_interval = telemetry_interval_s

        pos = initial_position or {"lat": 30.270, "lng": 120.150, "alt": 0.0}
        self._position = dict(pos)
        self._velocity = {"vx": 0.0, "vy": 0.0, "vz": 0.0}
        self._attitude = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        self._battery_pct = 100.0
        self._flight_mode = "STABILIZE"
        self._armed = False
        self._gps_fix_type = 3
        self._satellites_visible = 12

        self._waypoints: List[Dict[str, Any]] = []
        self._wp_index = 0
        self._flight_speed = 3.0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flight_thread: Optional[threading.Thread] = None
        self._telemetry_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    #  状态读取
    # ------------------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        """返回当前状态字典，格式与 update_device_telemetry(telemetry_type="drone_status") 一致"""
        with self._lock:
            return {
                "position": dict(self._position),
                "velocity": dict(self._velocity),
                "attitude": dict(self._attitude),
                "battery_pct": round(self._battery_pct, 1),
                "flight_mode": self._flight_mode,
                "armed": self._armed,
                "gps_fix_type": self._gps_fix_type,
                "satellites_visible": self._satellites_visible,
            }

    @property
    def is_flying(self) -> bool:
        with self._lock:
            return self._armed and self._flight_mode == "AUTO"

    @property
    def mission_complete(self) -> bool:
        with self._lock:
            return self._wp_index >= len(self._waypoints) if self._waypoints else True

    # ------------------------------------------------------------------
    #  生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop_event.clear()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_loop, name=f"drone-telemetry-{self.device_id}", daemon=True,
        )
        self._telemetry_thread.start()
        logger.info("[SimDrone:%s] 启动，初始位置 %s", self.device_id, self._position)

    def stop(self) -> None:
        self._stop_event.set()
        if self._flight_thread:
            self._flight_thread.join(timeout=3)
        if self._telemetry_thread:
            self._telemetry_thread.join(timeout=3)
        with self._lock:
            self._armed = False
            self._flight_mode = "STABILIZE"
        logger.info("[SimDrone:%s] 已停止", self.device_id)

    # ------------------------------------------------------------------
    #  航点任务
    # ------------------------------------------------------------------

    def upload_mission(self, waypoints: List[Dict[str, Any]]) -> bool:
        with self._lock:
            self._waypoints = list(waypoints)
            self._wp_index = 0
            if waypoints:
                self._position = {
                    "lat": waypoints[0]["lat"],
                    "lng": waypoints[0]["lng"],
                    "alt": waypoints[0].get("alt", 10.0),
                }
                self._flight_speed = waypoints[0].get("speed_m_s", 3.0)
        logger.info("[SimDrone:%s] 任务上传: %d 航点", self.device_id, len(waypoints))
        return True

    def arm_and_fly(self) -> None:
        with self._lock:
            self._armed = True
            self._flight_mode = "AUTO"
        if self._flight_thread and self._flight_thread.is_alive():
            return
        self._flight_thread = threading.Thread(
            target=self._flight_loop, name=f"drone-flight-{self.device_id}", daemon=True,
        )
        self._flight_thread.start()
        logger.info("[SimDrone:%s] 已解锁，开始飞行", self.device_id)

    # ------------------------------------------------------------------
    #  飞行模拟循环
    # ------------------------------------------------------------------

    def _flight_loop(self) -> None:
        step_interval = 0.2  # 5Hz 位置更新
        while not self._stop_event.is_set():
            with self._lock:
                if not self._armed or self._flight_mode != "AUTO":
                    break
                if self._wp_index >= len(self._waypoints):
                    self._flight_mode = "LOITER"
                    self._velocity = {"vx": 0.0, "vy": 0.0, "vz": 0.0}
                    logger.info("[SimDrone:%s] 任务完成，切换 LOITER", self.device_id)
                    break

                target = self._waypoints[self._wp_index]
                dx = target["lat"] - self._position["lat"]
                dy = target["lng"] - self._position["lng"]
                dz = target.get("alt", 10.0) - self._position["alt"]
                dist = math.sqrt(dx * dx + dy * dy)

                step_size = 0.0005  # ~50m per step at equator
                if dist < step_size:
                    self._position = {
                        "lat": target["lat"],
                        "lng": target["lng"],
                        "alt": target.get("alt", 10.0),
                    }
                    self._wp_index += 1
                    logger.debug(
                        "[SimDrone:%s] 到达航点 %d/%d",
                        self.device_id, self._wp_index, len(self._waypoints),
                    )
                else:
                    ratio = step_size / dist if dist > 0 else 0
                    self._position["lat"] += dx * ratio
                    self._position["lng"] += dy * ratio
                    self._position["alt"] += dz * ratio * 0.5

                speed = target.get("speed_m_s", self._flight_speed)
                yaw = math.atan2(dy, dx) if dist > 0 else self._attitude["yaw"]
                self._velocity = {
                    "vx": round(speed * math.cos(yaw), 2),
                    "vy": round(speed * math.sin(yaw), 2),
                    "vz": round(dz * 0.1, 2),
                }
                self._attitude = {
                    "roll": round(random.uniform(-0.05, 0.05), 3),
                    "pitch": round(random.uniform(-0.03, 0.03), 3),
                    "yaw": round(yaw, 3),
                }

                self._battery_pct = max(0, self._battery_pct - 0.02)
                self._satellites_visible = random.randint(10, 15)

            self._stop_event.wait(step_interval)

    # ------------------------------------------------------------------
    #  遥测上报循环
    # ------------------------------------------------------------------

    def _telemetry_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._telemetry_callback:
                state = self.get_state()
                try:
                    self._telemetry_callback(
                        self.device_id,
                        "drone_status",
                        state,
                        {"source": "sim_mavlink"},
                    )
                except Exception:
                    logger.exception("[SimDrone:%s] 遥测上报失败", self.device_id)
            self._stop_event.wait(self._telemetry_interval)
