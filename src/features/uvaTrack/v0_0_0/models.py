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
#  导航指令
# ---------------------------------------------------------------------------

class NavigationStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    TRAJECTORY_RECEIVED = "trajectory_received"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


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


@dataclass
class NavigationInstruction:
    instruction_id: str
    task_id: str
    device_id: str
    server_id: str
    start_point: Dict[str, float]         # {"lat": ..., "lng": ..., "alt": ...}
    end_point: Dict[str, float]
    algorithm: str = "default"
    nav_params: Dict[str, Any] = field(default_factory=dict)
    status: NavigationStatus = NavigationStatus.PENDING
    created_at: float = field(default_factory=time.time)
    dispatched_at: Optional[float] = None

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
            "status": self.status.value,
            "created_at": self.created_at,
            "dispatched_at": self.dispatched_at,
        }

    @staticmethod
    def generate_instruction_id() -> str:
        return f"nav_{uuid.uuid4().hex[:12]}"


@dataclass
class TrajectoryData:
    trajectory_id: str
    instruction_id: str
    device_id: str
    server_id: str
    waypoints: List[Waypoint] = field(default_factory=list)
    total_distance_m: float = 0.0
    estimated_time_s: float = 0.0
    algorithm_used: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "instruction_id": self.instruction_id,
            "device_id": self.device_id,
            "server_id": self.server_id,
            "waypoints": [wp.to_dict() for wp in self.waypoints],
            "total_distance_m": self.total_distance_m,
            "estimated_time_s": self.estimated_time_s,
            "algorithm_used": self.algorithm_used,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def generate_trajectory_id() -> str:
        return f"traj_{uuid.uuid4().hex[:12]}"


@dataclass
class DroneStatus:
    device_id: str
    position: Dict[str, float] = field(default_factory=dict)  # lat, lng, alt
    velocity: Dict[str, float] = field(default_factory=dict)  # vx, vy, vz
    attitude: Dict[str, float] = field(default_factory=dict)  # roll, pitch, yaw
    battery_pct: float = 0.0
    flight_mode: str = "unknown"
    armed: bool = False
    gps_fix_type: int = 0
    satellites_visible: int = 0
    timestamp: float = field(default_factory=time.time)
    raw_mavlink: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "position": dict(self.position),
            "velocity": dict(self.velocity),
            "attitude": dict(self.attitude),
            "battery_pct": self.battery_pct,
            "flight_mode": self.flight_mode,
            "armed": self.armed,
            "gps_fix_type": self.gps_fix_type,
            "satellites_visible": self.satellites_visible,
            "timestamp": self.timestamp,
            "raw_mavlink": dict(self.raw_mavlink),
        }
