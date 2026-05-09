#!/usr/bin/env python3
"""
边缘控制服务 HTTP 包装 — 端口 15000
将 CloudEdgeManager 暴露为 HTTP API，供模拟设备通过网络回调。

设备通过 /api/uvaTrack/CTest/ 前缀访问（与 CTest 类路径一致）。

接口：
  POST /api/uvaTrack/CTest/add_server              — 注册服务器
  POST /api/uvaTrack/CTest/add_device              — 注册设备
  POST /api/uvaTrack/CTest/assign_and_start_task   — 分配任务
  POST /api/uvaTrack/CTest/stop_task               — 停止任务
  POST /api/uvaTrack/CTest/submit_task_result      — 提交计算结果（通用）
  POST /api/uvaTrack/CTest/update_device_telemetry — 上报遥测数据（通用）
  POST /api/uvaTrack/CTest/heartbeat               — 心跳
  GET  /api/uvaTrack/CTest/list_servers            — 服务器列表
  GET  /api/uvaTrack/CTest/list_devices            — 设备列表
  GET  /api/uvaTrack/CTest/task_info?task_id=xxx   — 任务详情
  GET  /api/uvaTrack/CTest/device_info?device_id=x — 设备详情

启动：python edge_service_server.py [--port 15000]
"""
import os
import sys
import json
import logging
import argparse
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 确保能找到 CloudEdgeManager
_src_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "features", "uvaTrack", "v0_0_0",
)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from cloud_edge_manager import CloudEdgeManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [edge_service] %(levelname)s: %(message)s",
)
logger = logging.getLogger("edge_service")

_manager: CloudEdgeManager = None


class EdgeServiceHandler(BaseHTTPRequestHandler):

    # -------------------------  GET  -------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/uvaTrack/CTest/list_servers":
            filter_status = params.get("filter_by_status", ["all"])[0]
            self._json_response(200, _manager.list_servers(filter_status))

        elif path == "/api/uvaTrack/CTest/list_devices":
            group_id = params.get("group_id", ["all"])[0]
            self._json_response(200, _manager.list_devices(group_id))

        elif path == "/api/uvaTrack/CTest/task_info":
            task_id = params.get("task_id", [None])[0]
            if not task_id:
                self._json_response(400, {"code": -1, "msg": "task_id required"})
                return
            info = _manager.get_task_info(task_id)
            if info is None:
                self._json_response(404, {"code": -1, "msg": f"task {task_id} not found"})
            else:
                self._json_response(200, {"code": 0, "data": info})

        elif path == "/api/uvaTrack/CTest/device_info":
            device_id = params.get("device_id", [None])[0]
            if not device_id:
                self._json_response(400, {"code": -1, "msg": "device_id required"})
                return
            info = _manager.get_device_info(device_id)
            if info is None:
                self._json_response(404, {"code": -1, "msg": f"device {device_id} not found"})
            else:
                self._json_response(200, {"code": 0, "data": info})

        else:
            self._json_response(404, {"code": -1, "msg": "not found"})

    # -------------------------  POST  -------------------------
    def do_POST(self):
        body = self._read_body()
        path = urlparse(self.path).path

        if path == "/api/uvaTrack/CTest/add_server":
            result = _manager.add_server(
                server_id=body.get("server_id", ""),
                ip_address=body.get("ip_address", ""),
                capacity=int(body.get("capacity", 1)),
                tags=body.get("tags"),
                metadata=body.get("metadata"),
            )
            self._json_response(200, result)

        elif path == "/api/uvaTrack/CTest/add_device":
            result = _manager.add_device(
                device_id=body.get("device_id", ""),
                hardware_type=body.get("hardware_type", ""),
                is_simulated=body.get("is_simulated", True),
                supported_streams=body.get("supported_streams"),
                group_id=body.get("group_id", "default"),
                metadata=body.get("metadata"),
            )
            self._json_response(200, result)

        elif path == "/api/uvaTrack/CTest/assign_and_start_task":
            result = _manager.assign_and_start_task(
                device_id=body.get("device_id", ""),
                server_id=body.get("server_id", ""),
                task_config=body.get("task_config"),
            )
            self._json_response(200, result)

        elif path == "/api/uvaTrack/CTest/stop_task":
            result = _manager.stop_task(
                device_id=body.get("device_id", ""),
                reason=body.get("reason", "user_manual_stop"),
            )
            self._json_response(200, result)

        elif path == "/api/uvaTrack/CTest/submit_task_result":
            result = _manager.submit_task_result(
                task_id=body.get("task_id", ""),
                result_type=body.get("result_type", ""),
                payload=body.get("payload"),
                metadata=body.get("metadata"),
            )
            self._json_response(200, result)

        elif path == "/api/uvaTrack/CTest/update_device_telemetry":
            result = _manager.update_device_telemetry(
                device_id=body.get("device_id", ""),
                telemetry_type=body.get("telemetry_type", ""),
                data=body.get("data"),
                metadata=body.get("metadata"),
            )
            self._json_response(200, result)

        elif path == "/api/uvaTrack/CTest/heartbeat":
            target_type = body.get("target_type", "device")
            target_id = body.get("target_id", "")
            if target_type == "server":
                ok = _manager.refresh_server_heartbeat(target_id)
            else:
                ok = _manager.refresh_device_heartbeat(target_id, body.get("location"))
            self._json_response(200, {"code": 0 if ok else -1, "msg": "ok" if ok else "not found"})

        elif path == "/api/uvaTrack/CTest/remove_server":
            result = _manager.remove_server(
                server_id=body.get("server_id", ""),
                force_stop=body.get("force_stop", False),
            )
            self._json_response(200, result)

        elif path == "/api/uvaTrack/CTest/remove_device":
            result = _manager.remove_device(device_id=body.get("device_id", ""))
            self._json_response(200, result)

        else:
            self._json_response(404, {"code": -1, "msg": "not found"})

    # -------------------------  辅助  -------------------------
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

def start_edge_service(port: int = 15000, blocking: bool = True):
    global _manager
    # 重置单例以便测试
    CloudEdgeManager._instance = None
    CloudEdgeManager._init_lock = threading.Lock()
    _manager = CloudEdgeManager(
        heartbeat_interval=30.0,
        device_timeout=120.0,
        server_timeout=120.0,
    )

    server = HTTPServer(("0.0.0.0", port), EdgeServiceHandler)

    print()
    print("=" * 60)
    print("  边缘控制服务 (CloudEdgeManager) 已启动")
    print("=" * 60)
    print(f"    HTTP 地址:    http://127.0.0.1:{port}")
    print(f"    模式:         HTTP API 服务")
    print()
    print("    接口列表:")
    print(f"      POST /api/uvaTrack/CTest/add_server              — 注册服务器")
    print(f"      POST /api/uvaTrack/CTest/add_device              — 注册设备")
    print(f"      POST /api/uvaTrack/CTest/assign_and_start_task   — 分配任务")
    print(f"      POST /api/uvaTrack/CTest/stop_task               — 停止任务")
    print(f"      POST /api/uvaTrack/CTest/submit_task_result      — 提交计算结果")
    print(f"      POST /api/uvaTrack/CTest/update_device_telemetry — 上报遥测数据")
    print(f"      POST /api/uvaTrack/CTest/heartbeat               — 心跳")
    print(f"      GET  /api/uvaTrack/CTest/list_servers            — 服务器列表")
    print(f"      GET  /api/uvaTrack/CTest/list_devices            — 设备列表")
    print(f"      GET  /api/uvaTrack/CTest/task_info?task_id=xxx   — 任务详情")
    print(f"      GET  /api/uvaTrack/CTest/device_info?device_id=x — 设备详情")
    print("=" * 60)
    print()

    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            _manager.shutdown()
            server.server_close()
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server, _manager


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="边缘控制服务 HTTP 包装")
    parser.add_argument("--port", type=int, default=15000)
    args = parser.parse_args()
    start_edge_service(port=args.port)
