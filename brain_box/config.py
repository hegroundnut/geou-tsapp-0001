"""
类脑盒子配置
通过环境变量或配置文件灵活设置各项参数。
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EdgeServiceConfig:
    """边缘控制服务连接配置"""
    base_url: str = "http://127.0.0.1:8080"
    device_id: str = "brain_box_01"
    server_id: str = "svr_brain_01"
    heartbeat_interval_s: float = 5.0
    reconnect_interval_s: float = 3.0
    timeout_s: float = 10.0


@dataclass
class MAVLinkConfig:
    """MAVLink 连接配置"""
    connection_string: str = "udp:127.0.0.1:14550"
    baud_rate: int = 57600
    source_system: int = 255
    source_component: int = 0
    heartbeat_interval_s: float = 1.0
    status_report_interval_s: float = 1.0
    command_timeout_s: float = 5.0


@dataclass
class NavigatorConfig:
    """导航模块配置"""
    default_algorithm: str = "linear_interpolation"
    default_speed_m_s: float = 3.0
    default_altitude_m: float = 10.0
    waypoint_interval_m: float = 50.0
    max_waypoints: int = 500


@dataclass
class BrainBoxConfig:
    """类脑盒子总配置"""
    edge_service: EdgeServiceConfig = field(default_factory=EdgeServiceConfig)
    mavlink: MAVLinkConfig = field(default_factory=MAVLinkConfig)
    navigator: NavigatorConfig = field(default_factory=NavigatorConfig)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "BrainBoxConfig":
        cfg = cls()
        cfg.edge_service.base_url = os.getenv("EDGE_SERVICE_URL", cfg.edge_service.base_url)
        cfg.edge_service.device_id = os.getenv("BRAIN_BOX_DEVICE_ID", cfg.edge_service.device_id)
        cfg.edge_service.server_id = os.getenv("BRAIN_BOX_SERVER_ID", cfg.edge_service.server_id)
        cfg.edge_service.heartbeat_interval_s = float(
            os.getenv("EDGE_HEARTBEAT_INTERVAL", str(cfg.edge_service.heartbeat_interval_s))
        )
        cfg.mavlink.connection_string = os.getenv("MAVLINK_CONN", cfg.mavlink.connection_string)
        cfg.mavlink.baud_rate = int(os.getenv("MAVLINK_BAUD", str(cfg.mavlink.baud_rate)))
        cfg.mavlink.status_report_interval_s = float(
            os.getenv("MAVLINK_STATUS_INTERVAL", str(cfg.mavlink.status_report_interval_s))
        )
        cfg.navigator.default_algorithm = os.getenv("NAV_ALGORITHM", cfg.navigator.default_algorithm)
        cfg.navigator.default_speed_m_s = float(
            os.getenv("NAV_DEFAULT_SPEED", str(cfg.navigator.default_speed_m_s))
        )
        cfg.log_level = os.getenv("LOG_LEVEL", cfg.log_level)
        return cfg
