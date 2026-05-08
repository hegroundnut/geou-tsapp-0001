#!/usr/bin/env python3
"""
模拟类脑盒子 HTTP 服务 — 端口 15001
模拟真实类脑设备的 HTTP 接口，接收导航任务、生成轨迹、回调上报。

接口：
  POST /api/task     — 接收任务 {"task_id": "...", "task_config": {...}}
  GET  /api/status   — 获取状态
  GET  /api/algorithms — 获取支持的算法列表

回调（主动 HTTP POST）：
  → edge_service/api/submit_task_result   — 上报轨迹结果
  → drone/api/mission                     — 下发航点给无人机
  → drone/api/arm                         — 通知无人机起飞

启动：python sim_brain_box_server.py [--port 15001] [--edge-url ...] [--drone-url ...]
"""
import os
import sys
import json
import math
import time
import logging
import argparse
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sim_brain_box] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sim_brain_box")


# ---------------------------------------------------------------------------
#  轨迹生成（与 brain_box/navigator.py 算法对齐）
# ---------------------------------------------------------------------------

def _haversine(p1: dict, p2: dict) -> float:
    R = 6371000
    lat1, lat2 = math.radians(p1["lat"]), math.radians(p2["lat"])
    dlat = lat2 - lat1
    dlng = math.radians(p2["lng"] - p1["lng"])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def linear_interpolation(start: dict, end: dict, interval_m: float = 200.0, speed: float = 5.0) -> list:
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


def polyline_via_midpoint(start: dict, end: dict, offset_lat: float = 0.001, offset_lng: float = 0.001, speed: float = 5.0) -> list:
    mid = {
        "lat": (start["lat"] + end["lat"]) / 2 + offset_lat,
        "lng": (start["lng"] + end["lng"]) / 2 + offset_lng,
        "alt": max(start.get("alt", 10), end.get("alt", 10)) + 5,
    }
    waypoints = []
    for i, p in enumerate([start, mid, end]):
        waypoints.append({"lat": p["lat"], "lng": p["lng"], "alt": p.get("alt", 10), "seq": i, "speed_m_s": speed})
    return waypoints


ALGORITHMS = {
    "linear_interpolation": linear_interpolation,
    "polyline_via_midpoint": polyline_via_midpoint,
    "default": linear_interpolation,
}


# ---------------------------------------------------------------------------
#  类脑盒子核心
# ---------------------------------------------------------------------------

class BrainBoxCore:
    def __init__(self, server_id: str, edge_url: str, drone_url: str):
        self.server_id = server_id
        self._edge_url = edge_url
        self._drone_url = drone_url
        self._state = "idle"  # idle | computing | connected | error
        self._current_task_id = None
        self._lock = threading.Lock()

    def get_status(self) -> dict:
        with self._lock:
            return {
                "server_id": self.server_id,
                "state": self._state,
                "current_task_id": self._current_task_id,
                "algorithms": list(ALGORITHMS.keys()),
                "edge_url": self._edge_url,
                "drone_url": self._drone_url,
            }

    def process_task(self, task_id: str, task_config: dict) -> dict:
        with self._lock:
            self._state = "computing"
            self._current_task_id = task_id

        logger.info("收到任务 %s，开始处理...", task_id)

        custom = task_config.get("custom_payloads", {})
        start_point = custom.get("start_point", {"lat": 0, "lng": 0, "alt": 10})
        end_point = custom.get("end_point", {"lat": 0, "lng": 0, "alt": 10})
        algorithm = task_config.get("algorithm", "default")
        nav_params = custom.get("nav_params", {})
        interval = nav_params.get("waypoint_interval_m", 200.0)
        speed = nav_params.get("speed_m_s", 5.0)

        # 模拟计算耗时
        time.sleep(0.1)

        # 生成轨迹
        algo_func = ALGORITHMS.get(algorithm, linear_interpolation)
        if algorithm == "polyline_via_midpoint":
            waypoints = algo_func(start_point, end_point, speed=speed)
        else:
            waypoints = algo_func(start_point, end_point, interval, speed)

        total_distance = sum(
            _haversine(waypoints[i - 1], waypoints[i])
            for i in range(1, len(waypoints))
        )
        estimated_time = total_distance / speed if speed > 0 else 0

        trajectory_payload = {
            "waypoints": waypoints,
            "total_distance_m": round(total_distance, 2),
            "estimated_time_s": round(estimated_time, 2),
            "algorithm_used": algorithm if algorithm in ALGORITHMS else "linear_interpolation",
        }

        logger.info("轨迹生成完毕: %d 航点, %.1fm, ~%.0fs", len(waypoints), total_distance, estimated_time)

        # 步骤 1: HTTP POST 轨迹到边缘服务
        self._post_to_edge("submit_task_result", {
            "task_id": task_id,
            "result_type": "trajectory",
            "payload": trajectory_payload,
            "metadata": {"source": self.server_id, "algorithm": algorithm},
        })
        logger.info("轨迹已上报边缘服务 → %s/api/submit_task_result", self._edge_url)

        # 步骤 2: HTTP POST 航点到无人机
        self._post_to_drone("mission", {"waypoints": waypoints})
        logger.info("航点已下发无人机 → %s/api/mission", self._drone_url)

        # 步骤 3: 通知无人机起飞
        self._post_to_drone("arm", {})
        logger.info("已通知无人机起飞 → %s/api/arm", self._drone_url)

        with self._lock:
            self._state = "connected"

        return trajectory_payload

    def _post_to_edge(self, endpoint: str, data: dict):
        return self._http_post(f"{self._edge_url}/api/{endpoint}", data)

    def _post_to_drone(self, endpoint: str, data: dict):
        return self._http_post(f"{self._drone_url}/api/{endpoint}", data)

    def _http_post(self, url: str, data: dict) -> dict:
        payload = json.dumps(data, ensure_ascii=False).encode()
        try:
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            resp = urllib.request.urlopen(req, timeout=5)
            return json.loads(resp.read())
        except Exception as e:
            logger.error("HTTP POST %s 失败: %s", url, e)
            return {"code": -1, "msg": str(e)}


# ---------------------------------------------------------------------------
#  HTTP 请求处理
# ---------------------------------------------------------------------------

_brain_box: BrainBoxCore = None


class BrainBoxHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            self._json_response(200, {"code": 0, "data": _brain_box.get_status()})
        elif self.path == "/api/algorithms":
            self._json_response(200, {"code": 0, "data": {"algorithms": list(ALGORITHMS.keys())}})
        else:
            self._json_response(404, {"code": -1, "msg": "not found"})

    def do_POST(self):
        body = self._read_body()

        if self.path == "/api/task":
            task_id = body.get("task_id", "")
            task_config = body.get("task_config", {})
            if not task_id:
                self._json_response(400, {"code": -1, "msg": "task_id required"})
                return
            result = _brain_box.process_task(task_id, task_config)
            self._json_response(200, {"code": 0, "data": result})
        else:
            self._json_response(404, {"code": -1, "msg": "not found"})

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _json_response(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


# ---------------------------------------------------------------------------
#  启动
# ---------------------------------------------------------------------------

def start_brain_box_server(
    port: int = 15001,
    server_id: str = "svr_brain_sim_01",
    edge_url: str = "http://127.0.0.1:15000",
    drone_url: str = "http://127.0.0.1:15002",
    blocking: bool = True,
):
    global _brain_box
    _brain_box = BrainBoxCore(server_id=server_id, edge_url=edge_url, drone_url=drone_url)

    server = HTTPServer(("0.0.0.0", port), BrainBoxHandler)

    print()
    print("=" * 60)
    print("  模拟类脑盒子 (SimBrainBox) 已启动")
    print("=" * 60)
    print(f"    HTTP 地址:    http://127.0.0.1:{port}")
    print(f"    服务器 ID:    {server_id}")
    print(f"    状态:         {_brain_box.get_status()['state']}")
    print(f"    支持算法:     {list(ALGORITHMS.keys())}")
    print(f"    边缘服务:     {edge_url}")
    print(f"    无人机地址:   {drone_url}")
    print()
    print("    接口列表:")
    print(f"      POST http://127.0.0.1:{port}/api/task        — 下发任务")
    print(f"      GET  http://127.0.0.1:{port}/api/status      — 获取状态")
    print(f"      GET  http://127.0.0.1:{port}/api/algorithms  — 支持的算法")
    print()
    print("    收到任务后自动执行:")
    print(f"      1. 生成轨迹 (Navigator)")
    print(f"      2. HTTP POST → {edge_url}/api/submit_task_result  (上报轨迹)")
    print(f"      3. HTTP POST → {drone_url}/api/mission            (下发航点)")
    print(f"      4. HTTP POST → {drone_url}/api/arm                (通知起飞)")
    print("=" * 60)
    print()

    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, _brain_box


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模拟类脑盒子 HTTP 服务")
    parser.add_argument("--port", type=int, default=15001)
    parser.add_argument("--server-id", default="svr_brain_sim_01")
    parser.add_argument("--edge-url", default="http://127.0.0.1:15000")
    parser.add_argument("--drone-url", default="http://127.0.0.1:15002")
    args = parser.parse_args()
    start_brain_box_server(
        port=args.port,
        server_id=args.server_id,
        edge_url=args.edge_url,
        drone_url=args.drone_url,
    )
