"""
导航轨迹生成模块
负责根据导航指令（起点、终点、算法、参数）生成航点序列。

设计原则：
  - 可插拔算法架构：通过 register_algorithm 注册自定义算法
  - 内置基础算法：线性插值、简单折线
  - 预留接口：未来可集成 ROS 2 导航栈、GraphRAG 拓扑地图等
"""
import math
import time
import logging
from typing import Dict, List, Optional, Any, Callable

from models import Waypoint, NavigationInstruction, TrajectoryResult
from config import NavigatorConfig

logger = logging.getLogger("navigator")

# 算法函数签名: (start, end, params, config) -> List[Waypoint]
AlgorithmFunc = Callable[
    [Dict[str, float], Dict[str, float], Dict[str, Any], NavigatorConfig],
    List[Waypoint],
]


def _haversine_distance(p1: Dict[str, float], p2: Dict[str, float]) -> float:
    R = 6371000  # 地球半径（米）
    lat1, lat2 = math.radians(p1["lat"]), math.radians(p2["lat"])
    dlat = lat2 - lat1
    dlng = math.radians(p2["lng"] - p1["lng"])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
#  内置算法
# ---------------------------------------------------------------------------

def linear_interpolation(
    start: Dict[str, float],
    end: Dict[str, float],
    params: Dict[str, Any],
    config: NavigatorConfig,
) -> List[Waypoint]:
    """线性插值：在起终点间等距生成航点"""
    interval = params.get("waypoint_interval_m", config.waypoint_interval_m)
    speed = params.get("speed_m_s", config.default_speed_m_s)

    dist = _haversine_distance(start, end)
    n_segments = max(1, int(dist / interval))

    waypoints = []
    for i in range(n_segments + 1):
        t = i / n_segments
        wp = Waypoint(
            lat=start["lat"] + (end["lat"] - start["lat"]) * t,
            lng=start["lng"] + (end["lng"] - start["lng"]) * t,
            alt=start.get("alt", config.default_altitude_m)
            + (end.get("alt", config.default_altitude_m) - start.get("alt", config.default_altitude_m)) * t,
            seq=i,
            speed_m_s=speed,
        )
        waypoints.append(wp)
    return waypoints


def polyline_via_midpoint(
    start: Dict[str, float],
    end: Dict[str, float],
    params: Dict[str, Any],
    config: NavigatorConfig,
) -> List[Waypoint]:
    """折线航路：经过中间偏移点，模拟避障绕行"""
    offset_lat = params.get("offset_lat", 0.001)
    offset_lng = params.get("offset_lng", 0.001)
    speed = params.get("speed_m_s", config.default_speed_m_s)

    mid = {
        "lat": (start["lat"] + end["lat"]) / 2 + offset_lat,
        "lng": (start["lng"] + end["lng"]) / 2 + offset_lng,
        "alt": max(start.get("alt", 10), end.get("alt", 10)) + 5,
    }
    points = [start, mid, end]
    waypoints = []
    for i, p in enumerate(points):
        waypoints.append(Waypoint(
            lat=p["lat"], lng=p["lng"], alt=p.get("alt", config.default_altitude_m),
            seq=i, speed_m_s=speed,
        ))
    return waypoints


# ---------------------------------------------------------------------------
#  导航器
# ---------------------------------------------------------------------------

class Navigator:
    """
    导航轨迹生成器。

    使用方式:
        nav = Navigator(config)
        nav.register_algorithm("my_algo", my_func)
        result = nav.plan(instruction)
    """

    def __init__(self, config: NavigatorConfig):
        self._config = config
        self._algorithms: Dict[str, AlgorithmFunc] = {
            "linear_interpolation": linear_interpolation,
            "polyline_via_midpoint": polyline_via_midpoint,
        }

    def register_algorithm(self, name: str, func: AlgorithmFunc) -> None:
        self._algorithms[name] = func
        logger.info("Algorithm registered: %s", name)

    @property
    def available_algorithms(self) -> List[str]:
        return list(self._algorithms.keys())

    def plan(self, instruction: NavigationInstruction) -> TrajectoryResult:
        algo_name = instruction.algorithm
        if algo_name == "default" or algo_name not in self._algorithms:
            algo_name = self._config.default_algorithm

        algo_func = self._algorithms.get(algo_name)
        if not algo_func:
            logger.error("Algorithm not found: %s, falling back to linear", algo_name)
            algo_func = linear_interpolation
            algo_name = "linear_interpolation"

        logger.info(
            "Planning trajectory: %s -> %s (algo=%s)",
            instruction.start_point,
            instruction.end_point,
            algo_name,
        )

        waypoints = algo_func(
            instruction.start_point,
            instruction.end_point,
            instruction.nav_params,
            self._config,
        )

        total_distance = 0.0
        for i in range(1, len(waypoints)):
            p1 = {"lat": waypoints[i - 1].lat, "lng": waypoints[i - 1].lng}
            p2 = {"lat": waypoints[i].lat, "lng": waypoints[i].lng}
            total_distance += _haversine_distance(p1, p2)

        avg_speed = instruction.nav_params.get("speed_m_s", self._config.default_speed_m_s)
        estimated_time = total_distance / avg_speed if avg_speed > 0 else 0

        return TrajectoryResult(
            instruction_id=instruction.instruction_id,
            waypoints=waypoints,
            total_distance_m=total_distance,
            estimated_time_s=estimated_time,
            algorithm_used=algo_name,
        )
