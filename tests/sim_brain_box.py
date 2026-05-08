"""
虚拟类脑盒子 (SimBrainBox)
模拟类脑计算设备：接收任务配置 → 生成导航轨迹 → 上报 submit_task_result。
通过 CloudEdgeManager 的通用接口通信，替换为真机时只需切换为 HTTP 调用。

替换指南：
  真机上运行 brain_box/main.py + edge_client.py（HTTP 版），
  数据格式与本模拟器完全一致，边缘服务无需任何修改。
"""
import math
import time
import uuid
import logging
import threading
from typing import Dict, List, Any, Optional, Callable

logger = logging.getLogger("sim_brain_box")


# ---------------------------------------------------------------------------
#  内置轨迹生成（与 brain_box/navigator.py 算法对齐）
# ---------------------------------------------------------------------------

def _haversine(p1: Dict[str, float], p2: Dict[str, float]) -> float:
    R = 6371000
    lat1, lat2 = math.radians(p1["lat"]), math.radians(p2["lat"])
    dlat = lat2 - lat1
    dlng = math.radians(p2["lng"] - p1["lng"])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _linear_interpolation(
    start: Dict[str, float],
    end: Dict[str, float],
    interval_m: float = 50.0,
    speed: float = 3.0,
) -> List[Dict[str, Any]]:
    dist = _haversine(start, end)
    n = max(1, int(dist / interval_m))
    waypoints = []
    for i in range(n + 1):
        t = i / n
        waypoints.append({
            "lat": start["lat"] + (end["lat"] - start["lat"]) * t,
            "lng": start["lng"] + (end["lng"] - start["lng"]) * t,
            "alt": start.get("alt", 10) + (end.get("alt", 10) - start.get("alt", 10)) * t,
            "seq": i,
            "speed_m_s": speed,
        })
    return waypoints


# ---------------------------------------------------------------------------
#  SimBrainBox
# ---------------------------------------------------------------------------

class SimBrainBox:
    """
    虚拟类脑盒子。

    交互方式（与真机完全一致的数据格式）：
      1. 边缘服务通过 assign_and_start_task 下发任务（含 custom_payloads 中的导航参数）
      2. SimBrainBox.on_task_assigned() 被编排器调用，模拟"收到任务"
      3. 生成轨迹后调用 result_callback → 映射到 submit_task_result(result_type="trajectory")
      4. 航点列表通过 waypoint_callback 传给 SimDrone
    """

    def __init__(
        self,
        device_id: str,
        server_id: str,
        result_callback: Optional[Callable[[str, str, Dict, Optional[Dict]], Any]] = None,
        waypoint_callback: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
    ):
        """
        Args:
            device_id:  本设备在边缘服务中的注册 ID
            server_id:  本设备作为计算服务器在边缘服务中的注册 ID
            result_callback:  提交任务结果的回调 (task_id, result_type, payload, metadata)
                              对应 CloudEdgeManager.submit_task_result
            waypoint_callback: 将航点列表传递给无人机的回调
        """
        self.device_id = device_id
        self.server_id = server_id
        self._result_callback = result_callback
        self._waypoint_callback = waypoint_callback

        self._state = "idle"  # idle | computing | error
        self._current_task_id: Optional[str] = None
        self._lock = threading.Lock()
        self._algorithms = {
            "linear_interpolation": _linear_interpolation,
            "default": _linear_interpolation,
        }

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def register_algorithm(self, name: str, func: Callable) -> None:
        self._algorithms[name] = func

    # ------------------------------------------------------------------
    #  核心：接收任务并处理
    # ------------------------------------------------------------------

    def on_task_assigned(self, task_id: str, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        模拟接收边缘服务下发的任务。

        task_config 结构与 assign_and_start_task 的 task_config 一致，
        导航参数从 custom_payloads 中提取。

        Returns:
            轨迹结果字典（与 submit_task_result 的 payload 格式一致）
        """
        with self._lock:
            self._state = "computing"
            self._current_task_id = task_id

        logger.info("[SimBrainBox:%s] 收到任务 %s", self.device_id, task_id)

        custom = task_config.get("custom_payloads", {})
        start_point = custom.get("start_point", {"lat": 0, "lng": 0, "alt": 10})
        end_point = custom.get("end_point", {"lat": 0, "lng": 0, "alt": 10})
        algorithm = task_config.get("algorithm", "default")
        nav_params = custom.get("nav_params", {})
        interval = nav_params.get("waypoint_interval_m", 50.0)
        speed = nav_params.get("speed_m_s", 3.0)

        # 模拟计算耗时
        time.sleep(0.1)

        # 生成轨迹
        algo_func = self._algorithms.get(algorithm, _linear_interpolation)
        waypoints = algo_func(start_point, end_point, interval, speed)

        total_distance = 0.0
        for i in range(1, len(waypoints)):
            p1 = {"lat": waypoints[i - 1]["lat"], "lng": waypoints[i - 1]["lng"]}
            p2 = {"lat": waypoints[i]["lat"], "lng": waypoints[i]["lng"]}
            total_distance += _haversine(p1, p2)

        avg_speed = speed if speed > 0 else 3.0
        estimated_time = total_distance / avg_speed

        trajectory_payload = {
            "waypoints": waypoints,
            "total_distance_m": round(total_distance, 2),
            "estimated_time_s": round(estimated_time, 2),
            "algorithm_used": algorithm if algorithm in self._algorithms else "linear_interpolation",
        }

        logger.info(
            "[SimBrainBox:%s] 轨迹生成完成: %d 航点, %.1fm, ~%.0fs",
            self.device_id,
            len(waypoints),
            total_distance,
            estimated_time,
        )

        # 步骤 1: 上报轨迹给边缘控制服务
        if self._result_callback:
            self._result_callback(
                task_id,
                "trajectory",
                trajectory_payload,
                {"source": self.device_id, "server_id": self.server_id},
            )
            logger.info("[SimBrainBox:%s] 轨迹已上报 (submit_task_result)", self.device_id)

        # 步骤 2: 将航点传递给无人机
        if self._waypoint_callback:
            self._waypoint_callback(waypoints)
            logger.info("[SimBrainBox:%s] 航点已下发给无人机", self.device_id)

        with self._lock:
            self._state = "idle"
            self._current_task_id = None

        return trajectory_payload

    def stop(self) -> None:
        with self._lock:
            self._state = "idle"
            self._current_task_id = None
        logger.info("[SimBrainBox:%s] 已停止", self.device_id)
