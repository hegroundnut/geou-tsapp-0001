#!/usr/bin/env python3
"""
模拟无人设备 HTTP 服务 — 端口 15002
模拟真实无人机的 HTTP 接口，接收航点、飞行指令，持续上报遥测。

接口：
  POST /api/mission    — 上传航点  {"waypoints": [...]}
  POST /api/arm        — 解锁起飞
  GET  /api/status     — 获取状态（位置/速度/姿态/电池/飞行模式）
  GET  /api/telemetry  — 获取最新遥测数据

后台线程：
  - 飞行模拟线程（5Hz 位置更新）
  - 遥测上报线程 → HTTP POST 到边缘服务

启动：python sim_drone_server.py [--port 15002] [--edge-url http://127.0.0.1:15000]
"""
import os
import sys
import json
import math
import time
import random
import logging
import argparse
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sim_drone] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sim_drone")

# ---------------------------------------------------------------------------
#  无人机模拟核心
# ---------------------------------------------------------------------------

class DroneCore:
    def __init__(self, device_id: str, initial_position: dict):
        self.device_id = device_id
        self._position = dict(initial_position)
        self._velocity = {"vx": 0.0, "vy": 0.0, "vz": 0.0}
        self._attitude = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        self._battery_pct = 100.0
        self._flight_mode = "STABILIZE"
        self._armed = False
        self._gps_fix_type = 3
        self._satellites_visible = 12
        self._waypoints = []
        self._wp_index = 0
        self._flight_speed = 5.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flight_thread = None

    def get_state(self) -> dict:
        with self._lock:
            return {
                "device_id": self.device_id,
                "position": dict(self._position),
                "velocity": dict(self._velocity),
                "attitude": dict(self._attitude),
                "battery_pct": round(self._battery_pct, 1),
                "flight_mode": self._flight_mode,
                "armed": self._armed,
                "gps_fix_type": self._gps_fix_type,
                "satellites_visible": self._satellites_visible,
                "mission_progress": f"{self._wp_index}/{len(self._waypoints)}",
                "mission_complete": self._wp_index >= len(self._waypoints) if self._waypoints else True,
            }

    def upload_mission(self, waypoints: list) -> bool:
        with self._lock:
            self._waypoints = list(waypoints)
            self._wp_index = 0
            if waypoints:
                self._position = {
                    "lat": waypoints[0]["lat"],
                    "lng": waypoints[0]["lng"],
                    "alt": waypoints[0].get("alt", 10.0),
                }
                self._flight_speed = waypoints[0].get("speed_m_s", 5.0)
        logger.info("任务上传: %d 航点", len(waypoints))
        return True

    def arm_and_fly(self) -> bool:
        with self._lock:
            if not self._waypoints:
                return False
            self._armed = True
            self._flight_mode = "AUTO"
        if self._flight_thread and self._flight_thread.is_alive():
            return True
        self._flight_thread = threading.Thread(target=self._flight_loop, daemon=True)
        self._flight_thread.start()
        logger.info("已解锁，开始飞行")
        return True

    def stop(self):
        self._stop_event.set()
        if self._flight_thread:
            self._flight_thread.join(timeout=3)

    def _flight_loop(self):
        step_interval = 0.2
        while not self._stop_event.is_set():
            with self._lock:
                if not self._armed or self._flight_mode != "AUTO":
                    break
                if self._wp_index >= len(self._waypoints):
                    self._flight_mode = "LOITER"
                    self._velocity = {"vx": 0.0, "vy": 0.0, "vz": 0.0}
                    logger.info("任务完成，切换 LOITER")
                    break
                target = self._waypoints[self._wp_index]
                dx = target["lat"] - self._position["lat"]
                dy = target["lng"] - self._position["lng"]
                dz = target.get("alt", 10.0) - self._position["alt"]
                dist = math.sqrt(dx * dx + dy * dy)
                step_size = 0.0005
                if dist < step_size:
                    self._position = {"lat": target["lat"], "lng": target["lng"], "alt": target.get("alt", 10.0)}
                    self._wp_index += 1
                    logger.info("到达航点 %d/%d", self._wp_index, len(self._waypoints))
                else:
                    ratio = step_size / dist if dist > 0 else 0
                    self._position["lat"] += dx * ratio
                    self._position["lng"] += dy * ratio
                    self._position["alt"] += dz * ratio * 0.5
                speed = target.get("speed_m_s", self._flight_speed)
                yaw = math.atan2(dy, dx) if dist > 0 else self._attitude["yaw"]
                self._velocity = {"vx": round(speed * math.cos(yaw), 2), "vy": round(speed * math.sin(yaw), 2), "vz": round(dz * 0.1, 2)}
                self._attitude = {"roll": round(random.uniform(-0.05, 0.05), 3), "pitch": round(random.uniform(-0.03, 0.03), 3), "yaw": round(yaw, 3)}
                self._battery_pct = max(0, self._battery_pct - 0.02)
                self._satellites_visible = random.randint(10, 15)
            self._stop_event.wait(step_interval)


# ---------------------------------------------------------------------------
#  遥测上报线程
# ---------------------------------------------------------------------------

class TelemetryReporter:
    def __init__(self, drone: DroneCore, edge_url: str, interval: float = 1.0):
        self._drone = drone
        self._edge_url = edge_url
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("遥测上报启动 → %s (每 %.1f 秒)", self._edge_url, self._interval)

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _loop(self):
        while not self._stop_event.is_set():
            state = self._drone.get_state()
            payload = json.dumps({
                "device_id": self._drone.device_id,
                "telemetry_type": "drone_status",
                "data": state,
                "metadata": {"source": "sim_mavlink"},
            }).encode()
            try:
                req = urllib.request.Request(
                    f"{self._edge_url}/api/uvaTrack/CTest/update_device_telemetry",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=3)
            except Exception as e:
                logger.debug("遥测上报失败: %s", e)
            self._stop_event.wait(self._interval)


# ---------------------------------------------------------------------------
#  HTTP 请求处理
# ---------------------------------------------------------------------------

_drone: DroneCore = None


class DroneHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/api/status", "/api/telemetry"):
            self._json_response(200, {"code": 0, "data": _drone.get_state()})
        else:
            self._json_response(404, {"code": -1, "msg": "not found"})

    def do_POST(self):
        body = self._read_body()

        if self.path == "/api/mission":
            waypoints = body.get("waypoints", [])
            ok = _drone.upload_mission(waypoints)
            self._json_response(200, {"code": 0 if ok else -1, "msg": f"uploaded {len(waypoints)} waypoints"})

        elif self.path == "/api/arm":
            ok = _drone.arm_and_fly()
            self._json_response(200, {"code": 0 if ok else -1, "msg": "armed" if ok else "no mission"})

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
        pass  # 抑制默认日志


# ---------------------------------------------------------------------------
#  启动
# ---------------------------------------------------------------------------

def start_drone_server(
    port: int = 15002,
    device_id: str = "drone_sim_01",
    edge_url: str = "http://127.0.0.1:15000",
    initial_position: dict = None,
    telemetry_interval: float = 1.0,
    blocking: bool = True,
):
    global _drone
    pos = initial_position or {"lat": 30.270, "lng": 120.150, "alt": 0.0}
    _drone = DroneCore(device_id=device_id, initial_position=pos)

    reporter = TelemetryReporter(_drone, edge_url, telemetry_interval)
    reporter.start()

    server = HTTPServer(("0.0.0.0", port), DroneHandler)

    print()
    print("=" * 60)
    print("  模拟无人设备 (SimDrone) 已启动")
    print("=" * 60)
    print(f"    HTTP 地址:    http://127.0.0.1:{port}")
    print(f"    设备 ID:      {device_id}")
    print(f"    初始位置:     lat={pos['lat']}, lng={pos['lng']}, alt={pos['alt']}")
    print(f"    飞行模式:     {_drone.get_state()['flight_mode']}")
    print(f"    电池电量:     {_drone.get_state()['battery_pct']}%")
    print(f"    GPS:          fix_type={_drone.get_state()['gps_fix_type']}, 卫星={_drone.get_state()['satellites_visible']}")
    print(f"    遥测上报:     每 {telemetry_interval}s → {edge_url}/api/uvaTrack/CTest/update_device_telemetry")
    print()
    print("    接口列表:")
    print(f"      POST http://127.0.0.1:{port}/api/mission    — 上传航点")
    print(f"      POST http://127.0.0.1:{port}/api/arm        — 解锁起飞")
    print(f"      GET  http://127.0.0.1:{port}/api/status     — 获取状态")
    print(f"      GET  http://127.0.0.1:{port}/api/telemetry  — 获取遥测")
    print("=" * 60)
    print()

    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            reporter.stop()
            _drone.stop()
            server.server_close()
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, reporter, _drone


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模拟无人设备 HTTP 服务")
    parser.add_argument("--port", type=int, default=15002)
    parser.add_argument("--device-id", default="drone_sim_01")
    parser.add_argument("--edge-url", default="http://127.0.0.1:15000")
    parser.add_argument("--telemetry-interval", type=float, default=1.0)
    args = parser.parse_args()
    start_drone_server(
        port=args.port,
        device_id=args.device_id,
        edge_url=args.edge_url,
        telemetry_interval=args.telemetry_interval,
    )
