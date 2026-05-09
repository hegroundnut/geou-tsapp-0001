"""
类脑盒子数据模型
与边缘控制服务的 models.py 保持数据结构对齐，
同时定义 MAVLink 交互所需的本地数据结构。
"""
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


class BrainBoxState(str, Enum):
    IDLE = "idle"
    CONNECTED = "connected"
    NAVIGATING = "navigating"
    ERROR = "error"


class DroneConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ARMED = "armed"
    IN_FLIGHT = "in_flight"
    ERROR = "error"


@dataclass
class Waypoint:
    lat: float
    lng: float
    alt: float
    seq: int = 0
    hold_time_s: float = 0.0
    speed_m_s: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lat": self.lat,
            "lng": self.lng,
            "alt": self.alt,
            "seq": self.seq,
            "hold_time_s": self.hold_time_s,
            "speed_m_s": self.speed_m_s,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any], seq: int = 0) -> "Waypoint":
        return Waypoint(
            lat=float(d.get("lat", 0)),
            lng=float(d.get("lng", 0)),
            alt=float(d.get("alt", 0)),
            seq=d.get("seq", seq),
            hold_time_s=float(d.get("hold_time_s", 0)),
            speed_m_s=float(d.get("speed_m_s", 0)),
            metadata=d.get("metadata", {}),
        )


@dataclass
class NavigationInstruction:
    instruction_id: str
    task_id: str
    device_id: str
    server_id: str
    start_point: Dict[str, float]
    end_point: Dict[str, float]
    algorithm: str = "default"
    nav_params: Dict[str, Any] = field(default_factory=dict)
    received_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instruction_id": self.instruction_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
            "server_id": self.server_id,
            "start_point": dict(self.start_point),
            "end_point": dict(self.end_point),
            "algorithm": self.algorithm,
            "nav_params": dict(self.nav_params),
            "received_at": self.received_at,
        }


@dataclass
class TrajectoryResult:
    instruction_id: str
    waypoints: List[Waypoint] = field(default_factory=list)
    total_distance_m: float = 0.0
    estimated_time_s: float = 0.0
    algorithm_used: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instruction_id": self.instruction_id,
            "waypoints": [wp.to_dict() for wp in self.waypoints],
            "total_distance_m": self.total_distance_m,
            "estimated_time_s": self.estimated_time_s,
            "algorithm_used": self.algorithm_used,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class DroneState:
    position: Dict[str, float] = field(default_factory=dict)
    velocity: Dict[str, float] = field(default_factory=dict)
    attitude: Dict[str, float] = field(default_factory=dict)
    battery_pct: float = 0.0
    flight_mode: str = "unknown"
    armed: bool = False
    gps_fix_type: int = 0
    satellites_visible: int = 0
    connection_state: DroneConnectionState = DroneConnectionState.DISCONNECTED
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position": dict(self.position),
            "velocity": dict(self.velocity),
            "attitude": dict(self.attitude),
            "battery_pct": self.battery_pct,
            "flight_mode": self.flight_mode,
            "armed": self.armed,
            "gps_fix_type": self.gps_fix_type,
            "satellites_visible": self.satellites_visible,
            "connection_state": self.connection_state.value,
            "timestamp": self.timestamp,
        }
