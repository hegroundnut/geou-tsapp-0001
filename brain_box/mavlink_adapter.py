"""
MAVLink 适配层 — 与无人机通信
负责：
  1. 通过 MAVLink 协议连接无人机（支持串口/UDP/TCP）
  2. 接收无人机位置、速度、姿态、电池等遥测数据
  3. 向无人机下发导航航点（mission upload）
  4. 下发飞行控制指令（起飞、降落、模式切换等）

设计原则：
  - 提供可插拔的接口，当 pymavlink 不可用时自动降级为模拟模式
  - 所有 MAVLink I/O 在独立线程中运行，不阻塞主线程
  - 线程安全的状态读取
"""
import math
import time
import threading
import logging
from typing import List, Optional, Callable, Any, Dict

from models import DroneState, DroneConnectionState, Waypoint
from config import MAVLinkConfig

logger = logging.getLogger("mavlink_adapter")

try:
    from pymavlink import mavutil
    HAS_PYMAVLINK = True
except ImportError:
    HAS_PYMAVLINK = False
    logger.warning("pymavlink not installed, running in simulation mode")


class MAVLinkAdapter:
    """
    MAVLink 通信适配器。

    若 pymavlink 可用则连接真实飞控；
    否则以模拟模式运行，生成虚拟遥测数据。
    """

    def __init__(
        self,
        config: MAVLinkConfig,
        on_state_update: Optional[Callable[[DroneState], None]] = None,
        simulated: bool = False,
    ):
        self._config = config
        self._on_state_update = on_state_update
        self._simulated = simulated or (not HAS_PYMAVLINK)
        self._connection: Any = None
        self._state = DroneState()
        self._lock = threading.Lock()
        self._recv_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._current_waypoints: List[Waypoint] = []
        self._sim_wp_index = 0
        self._sim_position = {"lat": 0.0, "lng": 0.0, "alt": 0.0}

    @property
    def state(self) -> DroneState:
        with self._lock:
            return self._state

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._state.connection_state not in (
                DroneConnectionState.DISCONNECTED,
                DroneConnectionState.ERROR,
            )

    def connect(self) -> bool:
        if self._simulated:
            logger.info("MAVLink adapter running in SIMULATION mode")
            with self._lock:
                self._state.connection_state = DroneConnectionState.CONNECTED
                self._state.flight_mode = "STABILIZE"
            self._start_recv_loop()
            return True

        try:
            logger.info("Connecting to MAVLink: %s", self._config.connection_string)
            self._connection = mavutil.mavlink_connection(
                self._config.connection_string,
                baud=self._config.baud_rate,
                source_system=self._config.source_system,
                source_component=self._config.source_component,
            )
            self._connection.wait_heartbeat(timeout=self._config.command_timeout_s)
            with self._lock:
                self._state.connection_state = DroneConnectionState.CONNECTED
            logger.info(
                "MAVLink connected (sysid=%d compid=%d)",
                self._connection.target_system,
                self._connection.target_component,
            )
            self._start_recv_loop()
            return True
        except Exception as e:
            logger.error("MAVLink connection failed: %s", e)
            with self._lock:
                self._state.connection_state = DroneConnectionState.ERROR
            return False

    def disconnect(self) -> None:
        self._stop_event.set()
        if self._recv_thread:
            self._recv_thread.join(timeout=3)
        if self._connection:
            self._connection.close()
            self._connection = None
        with self._lock:
            self._state.connection_state = DroneConnectionState.DISCONNECTED
        logger.info("MAVLink disconnected")

    def upload_mission(self, waypoints: List[Waypoint]) -> bool:
        self._current_waypoints = list(waypoints)
        if self._simulated:
            logger.info("Simulated mission upload: %d waypoints", len(waypoints))
            self._sim_wp_index = 0
            if waypoints:
                self._sim_position = {
                    "lat": waypoints[0].lat,
                    "lng": waypoints[0].lng,
                    "alt": waypoints[0].alt,
                }
            return True

        if not self._connection:
            logger.error("Cannot upload mission: not connected")
            return False

        try:
            self._connection.waypoint_clear_all_send()
            self._connection.waypoint_count_send(len(waypoints))

            for wp in waypoints:
                self._connection.mav.mission_item_int_send(
                    self._connection.target_system,
                    self._connection.target_component,
                    wp.seq,
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                    0, 1,  # current, autocontinue
                    wp.hold_time_s, 0, 0, 0,
                    int(wp.lat * 1e7),
                    int(wp.lng * 1e7),
                    wp.alt,
                )
            logger.info("Mission uploaded: %d waypoints", len(waypoints))
            return True
        except Exception as e:
            logger.error("Mission upload failed: %s", e)
            return False

    def set_mode(self, mode: str) -> bool:
        if self._simulated:
            with self._lock:
                self._state.flight_mode = mode
            logger.info("Simulated mode change: %s", mode)
            return True

        if not self._connection:
            return False
        try:
            mode_id = self._connection.mode_mapping().get(mode)
            if mode_id is None:
                logger.error("Unknown flight mode: %s", mode)
                return False
            self._connection.set_mode(mode_id)
            return True
        except Exception as e:
            logger.error("Set mode failed: %s", e)
            return False

    def arm(self) -> bool:
        if self._simulated:
            with self._lock:
                self._state.armed = True
                self._state.connection_state = DroneConnectionState.ARMED
            return True
        if not self._connection:
            return False
        try:
            self._connection.arducopter_arm()
            return True
        except Exception as e:
            logger.error("Arm failed: %s", e)
            return False

    def disarm(self) -> bool:
        if self._simulated:
            with self._lock:
                self._state.armed = False
                self._state.connection_state = DroneConnectionState.CONNECTED
            return True
        if not self._connection:
            return False
        try:
            self._connection.arducopter_disarm()
            return True
        except Exception as e:
            logger.error("Disarm failed: %s", e)
            return False

    # ------------------------------------------------------------------
    #  接收循环
    # ------------------------------------------------------------------

    def _start_recv_loop(self) -> None:
        self._stop_event.clear()
        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="mavlink-recv", daemon=True
        )
        self._recv_thread.start()

    def _recv_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._simulated:
                    self._simulate_telemetry()
                else:
                    self._read_real_telemetry()
            except Exception:
                logger.exception("MAVLink recv loop error")
            self._stop_event.wait(self._config.status_report_interval_s)

    def _read_real_telemetry(self) -> None:
        if not self._connection:
            return
        msg = self._connection.recv_match(blocking=True, timeout=1)
        if not msg:
            return
        msg_type = msg.get_type()
        with self._lock:
            if msg_type == "GLOBAL_POSITION_INT":
                self._state.position = {
                    "lat": msg.lat / 1e7,
                    "lng": msg.lon / 1e7,
                    "alt": msg.relative_alt / 1000.0,
                }
                self._state.velocity = {
                    "vx": msg.vx / 100.0,
                    "vy": msg.vy / 100.0,
                    "vz": msg.vz / 100.0,
                }
            elif msg_type == "ATTITUDE":
                self._state.attitude = {
                    "roll": msg.roll,
                    "pitch": msg.pitch,
                    "yaw": msg.yaw,
                }
            elif msg_type == "SYS_STATUS":
                self._state.battery_pct = getattr(msg, "battery_remaining", 0)
            elif msg_type == "HEARTBEAT":
                self._state.armed = bool(msg.base_mode & 128)
                mode_map = self._connection.mode_mapping()
                rev_map = {v: k for k, v in mode_map.items()} if mode_map else {}
                self._state.flight_mode = rev_map.get(msg.custom_mode, str(msg.custom_mode))
            elif msg_type == "GPS_RAW_INT":
                self._state.gps_fix_type = msg.fix_type
                self._state.satellites_visible = msg.satellites_visible
            self._state.timestamp = time.time()
        if self._on_state_update:
            self._on_state_update(self._state)

    def _simulate_telemetry(self) -> None:
        with self._lock:
            if self._current_waypoints and self._sim_wp_index < len(self._current_waypoints):
                target = self._current_waypoints[self._sim_wp_index]
                dx = target.lat - self._sim_position["lat"]
                dy = target.lng - self._sim_position["lng"]
                dz = target.alt - self._sim_position["alt"]
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                step = 0.0001
                if dist < step:
                    self._sim_position = {"lat": target.lat, "lng": target.lng, "alt": target.alt}
                    self._sim_wp_index += 1
                else:
                    ratio = step / dist
                    self._sim_position["lat"] += dx * ratio
                    self._sim_position["lng"] += dy * ratio
                    self._sim_position["alt"] += dz * ratio
                self._state.connection_state = DroneConnectionState.IN_FLIGHT
            self._state.position = dict(self._sim_position)
            self._state.velocity = {"vx": 1.0, "vy": 0.5, "vz": 0.0}
            self._state.attitude = {"roll": 0.01, "pitch": -0.02, "yaw": 1.57}
            self._state.battery_pct = max(0, self._state.battery_pct - 0.01) if self._state.battery_pct > 0 else 95.0
            self._state.gps_fix_type = 3
            self._state.satellites_visible = 12
            self._state.timestamp = time.time()
        if self._on_state_update:
            self._on_state_update(self._state)
