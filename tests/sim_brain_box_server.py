#!/usr/bin/env python3
"""
模拟类脑盒子 HTTP 服务 — 端口 15001
直接使用 brain_box/ 中的完整代码栈（BrainBox → Navigator + MAVLinkAdapter + EdgeServiceClient）。

接口：
  POST /api/task        — 接收任务 {"task_id": "...", "task_config": {...}}
  GET  /api/status      — 获取状态
  GET  /api/algorithms  — 获取支持的算法列表

内部流程（收到任务后）：
  1. brain_box/Navigator 生成轨迹
  2. brain_box/EdgeServiceClient → HTTP POST :15000/api/submit_task_result  (上报轨迹)
  3. brain_box/MAVLinkAdapter 内部模拟飞行
  4. HTTP POST → SimDrone :15002/api/mission (下发航点)
  5. HTTP POST → SimDrone :15002/api/arm     (通知起飞)

启动：python sim_brain_box_server.py [--port 15001] [--edge-url ...] [--drone-url ...]
"""
import os
import sys
import json
import logging
import argparse
import threading
import importlib
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sim_brain_box] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sim_brain_box")


# ---------------------------------------------------------------------------
#  隔离导入 brain_box 模块（与 edge_service 同名模块不冲突）
# ---------------------------------------------------------------------------

_brain_box_dir = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "brain_box")
)


def _import_brain_box():
    conflicting_names = ["models", "config", "main", "navigator", "edge_client", "mavlink_adapter"]
    saved_modules = {}
    for name in conflicting_names:
        if name in sys.modules:
            saved_modules[name] = sys.modules.pop(name)

    sys.path.insert(0, _brain_box_dir)
    try:
        bb_main = importlib.import_module("main")
        bb_config = importlib.import_module("config")
        BrainBox = bb_main.BrainBox
        BrainBoxConfig = bb_config.BrainBoxConfig
        EdgeServiceConfig = bb_config.EdgeServiceConfig
        MAVLinkConfig = bb_config.MAVLinkConfig
        NavigatorConfig = bb_config.NavigatorConfig
        return BrainBox, BrainBoxConfig, EdgeServiceConfig, MAVLinkConfig, NavigatorConfig
    finally:
        for name in conflicting_names:
            sys.modules.pop(name, None)
        for name, mod in saved_modules.items():
            sys.modules[name] = mod
        sys.path.remove(_brain_box_dir)


BrainBox, BrainBoxConfig, EdgeServiceConfig, MAVLinkConfig, NavigatorConfig = _import_brain_box()


# ---------------------------------------------------------------------------
#  HTTP 桥接 — 将 EdgeServiceClient._post 路由到真实 HTTP
# ---------------------------------------------------------------------------

def _make_http_post_bridge(edge_url: str):
    """
    返回一个函数，替换 EdgeServiceClient._post，
    让它通过真实 HTTP POST 调用边缘服务 :15000。
    """
    def _http_post(endpoint: str, payload: Dict[str, Any]) -> bool:
        url = f"{edge_url}/api/{endpoint}"
        data = json.dumps(payload, ensure_ascii=False).encode()
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=5)
            result = json.loads(resp.read())
            return result.get("code", -1) == 0
        except Exception as e:
            logger.error("HTTP POST %s 失败: %s", url, e)
            return False
    return _http_post


def _http_post_json(url: str, data: dict) -> dict:
    payload = json.dumps(data, ensure_ascii=False).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read())
    except Exception as e:
        logger.error("HTTP POST %s 失败: %s", url, e)
        return {"code": -1, "msg": str(e)}


# ---------------------------------------------------------------------------
#  类脑盒子核心（封装 brain_box/BrainBox）
# ---------------------------------------------------------------------------

class BrainBoxCore:
    def __init__(self, server_id: str, device_id: str, edge_url: str, drone_url: str):
        self.server_id = server_id
        self.device_id = device_id
        self._edge_url = edge_url
        self._drone_url = drone_url
        self._lock = threading.Lock()

        # 使用 brain_box/ 真实代码
        config = BrainBoxConfig(
            edge_service=EdgeServiceConfig(
                device_id=device_id,
                server_id=server_id,
            ),
            mavlink=MAVLinkConfig(),
            navigator=NavigatorConfig(),
        )
        sys.path.insert(0, _brain_box_dir)
        try:
            self._brain_box = BrainBox(config=config)
        finally:
            sys.path.remove(_brain_box_dir)

        # 桥接：将 EdgeServiceClient._post 替换为真实 HTTP 调用 :15000
        self._brain_box._edge_client._post = _make_http_post_bridge(edge_url)

        # 启动 BrainBox
        self._brain_box.start()
        logger.info("BrainBox 已启动（使用 brain_box/ 完整代码栈）")

    def get_status(self) -> dict:
        return {
            "server_id": self.server_id,
            "device_id": self.device_id,
            "state": self._brain_box.state.value,
            "modules": {
                "Navigator": "brain_box/navigator.py",
                "MAVLinkAdapter": "brain_box/mavlink_adapter.py (模拟模式)",
                "EdgeServiceClient": f"brain_box/edge_client.py → HTTP {self._edge_url}",
            },
            "edge_url": self._edge_url,
            "drone_url": self._drone_url,
        }

    def get_algorithms(self) -> list:
        return list(self._brain_box._navigator._algorithms.keys())

    def process_task(self, task_id: str, task_config: dict) -> dict:
        custom = task_config.get("custom_payloads", {})
        nav_config = {
            "start_point": custom.get("start_point", {}),
            "end_point": custom.get("end_point", {}),
            "algorithm": task_config.get("algorithm", custom.get("algorithm", "default")),
            "nav_params": custom.get("nav_params", {}),
        }

        logger.info("收到任务 %s，调用 BrainBox.handle_navigation()...", task_id)

        # 拦截 EdgeServiceClient 的 submit_task_result 调用，捕获轨迹数据
        captured_trajectory = {}
        original_post = self._brain_box._edge_client._post

        def _intercepting_post(endpoint: str, payload: Dict[str, Any]) -> bool:
            if endpoint == "submit_task_result" and payload.get("result_type") == "trajectory":
                captured_trajectory.update(payload.get("payload", {}))
            return original_post(endpoint, payload)

        self._brain_box._edge_client._post = _intercepting_post

        # 调用 brain_box/ 真实代码执行导航
        # handle_navigation 内部会：
        #   1. Navigator.plan() 生成轨迹
        #   2. EdgeServiceClient.report_trajectory() → HTTP POST :15000/api/submit_task_result
        #   3. MAVLinkAdapter.upload_mission() → 内部模拟
        ok = self._brain_box.handle_navigation(task_id, nav_config)

        # 恢复原始 _post
        self._brain_box._edge_client._post = original_post

        if not ok:
            return {"code": -1, "msg": "handle_navigation failed"}

        waypoints = captured_trajectory.get("waypoints", [])

        # 下发航点给 SimDrone
        logger.info("下发航点给无人机 → %s/api/mission", self._drone_url)
        _http_post_json(f"{self._drone_url}/api/mission", {"waypoints": waypoints})

        # 通知无人机起飞
        logger.info("通知无人机起飞 → %s/api/arm", self._drone_url)
        _http_post_json(f"{self._drone_url}/api/arm", {})

        return {
            "waypoints": waypoints,
            "total_distance_m": captured_trajectory.get("total_distance_m", 0),
            "estimated_time_s": captured_trajectory.get("estimated_time_s", 0),
            "algorithm_used": captured_trajectory.get("algorithm_used", ""),
        }

    def stop(self):
        self._brain_box.stop()


# ---------------------------------------------------------------------------
#  HTTP 请求处理
# ---------------------------------------------------------------------------

_brain_box_core: BrainBoxCore = None


class BrainBoxHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            self._json_response(200, {"code": 0, "data": _brain_box_core.get_status()})
        elif self.path == "/api/algorithms":
            self._json_response(200, {"code": 0, "data": {"algorithms": _brain_box_core.get_algorithms()}})
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
            result = _brain_box_core.process_task(task_id, task_config)
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
    device_id: str = "drone_sim_01",
    edge_url: str = "http://127.0.0.1:15000",
    drone_url: str = "http://127.0.0.1:15002",
    blocking: bool = True,
):
    global _brain_box_core
    _brain_box_core = BrainBoxCore(
        server_id=server_id,
        device_id=device_id,
        edge_url=edge_url,
        drone_url=drone_url,
    )

    algorithms = _brain_box_core.get_algorithms()
    server = HTTPServer(("0.0.0.0", port), BrainBoxHandler)

    print()
    print("=" * 60)
    print("  模拟类脑盒子 (SimBrainBox) 已启动")
    print("=" * 60)
    print(f"    HTTP 地址:    http://127.0.0.1:{port}")
    print(f"    服务器 ID:    {server_id}")
    print(f"    关联设备 ID:  {device_id}")
    print(f"    状态:         {_brain_box_core.get_status()['state']}")
    print(f"    代码栈:       brain_box/ (Navigator + MAVLinkAdapter + EdgeServiceClient)")
    print(f"    支持算法:     {algorithms}")
    print(f"    边缘服务:     {edge_url}")
    print(f"    无人机地址:   {drone_url}")
    print()
    print("    接口列表:")
    print(f"      POST http://127.0.0.1:{port}/api/task        — 下发任务")
    print(f"      GET  http://127.0.0.1:{port}/api/status      — 获取状态")
    print(f"      GET  http://127.0.0.1:{port}/api/algorithms  — 支持的算法")
    print()
    print("    收到任务后自动执行 (brain_box/ 真实代码):")
    print(f"      1. Navigator.plan()           → 生成轨迹")
    print(f"      2. EdgeServiceClient._post()  → HTTP POST {edge_url}/api/submit_task_result")
    print(f"      3. MAVLinkAdapter              → 内部模拟飞行")
    print(f"      4. HTTP POST                  → {drone_url}/api/mission (下发航点)")
    print(f"      5. HTTP POST                  → {drone_url}/api/arm    (通知起飞)")
    print("=" * 60)
    print()

    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            _brain_box_core.stop()
            server.server_close()
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, _brain_box_core


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模拟类脑盒子 HTTP 服务")
    parser.add_argument("--port", type=int, default=15001)
    parser.add_argument("--server-id", default="svr_brain_sim_01")
    parser.add_argument("--device-id", default="drone_sim_01")
    parser.add_argument("--edge-url", default="http://127.0.0.1:15000")
    parser.add_argument("--drone-url", default="http://127.0.0.1:15002")
    args = parser.parse_args()
    start_brain_box_server(
        port=args.port,
        server_id=args.server_id,
        device_id=args.device_id,
        edge_url=args.edge_url,
        drone_url=args.drone_url,
    )
