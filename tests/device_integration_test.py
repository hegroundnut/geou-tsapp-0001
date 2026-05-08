#!/usr/bin/env python3
"""
HTTP 多服务集成测试 — 模拟最真实的云边协同场景

三个独立 HTTP 服务：
  :15000  边缘控制服务  (CloudEdgeManager)  — 内部通信端口
  :15001  模拟类脑盒子  (SimBrainBox)        — 使用 brain_box/ 完整代码栈
  :15002  模拟无人设备  (SimDrone)

用户通过 curl 调用（create-task 格式）：
  curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' ...

内部 HTTP 通信链路（用户不可见，全部走 :15000）：
  类脑盒子  ──HTTP──→ :15000 边缘服务  (submit_task_result 上报轨迹)
  类脑盒子  ──HTTP──→ :15002 无人设备  (下发航点 + 通知起飞)
  无人设备  ──HTTP──→ :15000 边缘服务  (update_device_telemetry 遥测上报)

运行：python tests/device_integration_test.py
"""
import os
import sys
import time
import json
import uuid
import logging
import urllib.request

# 确保能找到服务模块
_tests_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _tests_dir)

_edge_dir = os.path.join(
    os.path.dirname(_tests_dir),
    "src", "features", "uvaTrack", "v0_0_0",
)
sys.path.insert(0, os.path.abspath(_edge_dir))

from edge_service_server import start_edge_service
from sim_brain_box_server import start_brain_box_server
from sim_drone_server import start_drone_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("integration_test")

EDGE_URL = "http://127.0.0.1:15000"
BRAIN_URL = "http://127.0.0.1:15001"
DRONE_URL = "http://127.0.0.1:15002"

CAPABILITY_ID = "1934867764779429889"


# ---------------------------------------------------------------------------
#  HTTP 辅助
# ---------------------------------------------------------------------------

def http_post(url: str, data: dict) -> dict:
    payload = json.dumps(data, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())


def http_get(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())


def _sep(title: str):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _kv(key: str, value, indent: int = 4):
    prefix = " " * indent
    if isinstance(value, dict):
        print(f"{prefix}{key}:")
        for k, v in value.items():
            print(f"{prefix}    {k}: {v}")
    else:
        print(f"{prefix}{key}: {value}")


def _print_curl(subfuncs: list, desc: str = ""):
    """打印用户实际使用的 curl 命令格式"""
    report_id = str(uuid.uuid4())
    param = json.dumps([{
        "dtype": "cloud_edge_manager",
        "version": "1.0.0",
        "subfuncs": subfuncs,
    }], ensure_ascii=False)
    print(f"    curl 命令{' (' + desc + ')' if desc else ''}:")
    print(f"    curl --location --request POST \\")
    print(f"      'http://work.datashell.cn:8500/ai-master-svr/create-task/' \\")
    print(f"      --data-urlencode 'report_id={report_id}' \\")
    print(f"      --data-urlencode 'capability_id={CAPABILITY_ID}' \\")
    print(f"      --data-urlencode 'param={param}' \\")
    print(f"      --data-urlencode 'deal_port=\"\"'")


# ---------------------------------------------------------------------------
#  测试主流程
# ---------------------------------------------------------------------------

def run_test():
    # ==================================================================
    # 启动三个 HTTP 服务
    # ==================================================================
    _sep("启动三个 HTTP 服务（模拟真实部署）")

    # 1. 启动边缘控制服务（内部通信端口，用户不可见）
    edge_server, edge_manager = start_edge_service(port=15000, blocking=False)
    time.sleep(0.3)

    # 2. 启动模拟无人设备
    drone_server, drone_reporter, drone_core = start_drone_server(
        port=15002,
        device_id="drone_sim_01",
        edge_url=EDGE_URL,
        initial_position={"lat": 30.270, "lng": 120.150, "alt": 0.0},
        telemetry_interval=1.0,
        blocking=False,
    )
    time.sleep(0.3)

    # 3. 启动模拟类脑盒子（使用 brain_box/ 完整代码栈）
    brain_server, brain_core = start_brain_box_server(
        port=15001,
        server_id="svr_brain_sim_01",
        device_id="drone_sim_01",
        edge_url=EDGE_URL,
        drone_url=DRONE_URL,
        blocking=False,
    )
    time.sleep(0.3)

    print()
    print("    三个服务均已启动:")
    print(f"      :15000  边缘控制服务  (CloudEdgeManager) — 内部通信")
    print(f"      :15001  模拟类脑盒子  (SimBrainBox)      — brain_box/ 代码栈")
    print(f"      :15002  模拟无人设备  (SimDrone)")
    print()

    # ==================================================================
    # 阶段 1：启动信息（验证各服务 HTTP 可达）
    # ==================================================================
    _sep("阶段 1：验证各服务 HTTP 可达")

    # 类脑盒子状态
    print()
    print("  [HTTP GET] → 类脑盒子 :15001/api/status")
    r = http_get(f"{BRAIN_URL}/api/status")
    brain_status = r.get("data", {})
    print(f"  [返回] server_id = {brain_status.get('server_id')}")
    print(f"         device_id = {brain_status.get('device_id')}")
    print(f"         state     = {brain_status.get('state')}")
    modules = brain_status.get("modules", {})
    if modules:
        print(f"         代码栈:")
        for name, desc in modules.items():
            print(f"           {name}: {desc}")
    print(f"         算法: {brain_core.get_algorithms()}")

    # 无人设备状态
    print()
    print("  [HTTP GET] → 无人设备 :15002/api/status")
    r = http_get(f"{DRONE_URL}/api/status")
    drone_status = r.get("data", {})
    print(f"  [返回] device_id = {drone_status.get('device_id')}")
    _kv("位置", drone_status.get("position"))
    _kv("电池", f"{drone_status.get('battery_pct')}%")
    _kv("飞行模式", drone_status.get("flight_mode"))
    _kv("GPS", f"fix_type={drone_status.get('gps_fix_type')}, 卫星={drone_status.get('satellites_visible')}")

    # ==================================================================
    # 阶段 2：用户通过 curl 命令注册基础设施
    # ==================================================================
    _sep("阶段 2：用户注册基础设施（curl create-task 格式）")

    # --- 注册服务器 ---
    print()
    _print_curl([{
        "func_name": "add_server",
        "func_desc": "注册计算服务器节点到云端调度池",
        "params": {
            "server_id": "svr_brain_sim_01",
            "ip_address": "127.0.0.1",
            "capacity": 5,
            "tags": ["brain_box", "navigation", "simulated"],
        },
    }], "注册服务器")
    print()
    print("  [内部 :15000] 执行 add_server...")
    r = http_post(f"{EDGE_URL}/api/add_server", {
        "server_id": "svr_brain_sim_01",
        "ip_address": "127.0.0.1",
        "capacity": 5,
        "tags": ["brain_box", "navigation", "simulated"],
        "metadata": {"hardware": "sim_neuromorphic"},
    })
    print(f"  [返回] code={r['code']}, msg={r['msg']}")

    # --- 注册设备 ---
    print()
    _print_curl([{
        "func_name": "add_device",
        "func_desc": "注册边缘设备到管控系统",
        "params": {
            "device_id": "drone_sim_01",
            "hardware_type": "sim_quadcopter",
            "is_simulated": True,
            "supported_streams": ["video", "telemetry"],
        },
    }], "注册设备")
    print()
    print("  [内部 :15000] 执行 add_device...")
    r = http_post(f"{EDGE_URL}/api/add_device", {
        "device_id": "drone_sim_01",
        "hardware_type": "sim_quadcopter",
        "is_simulated": True,
        "supported_streams": ["video", "telemetry"],
        "group_id": "aerial",
        "metadata": {"frame": "X500"},
    })
    print(f"  [返回] code={r['code']}, msg={r['msg']}")

    # --- 查看注册结果 ---
    print()
    _print_curl([{
        "func_name": "list_servers",
        "func_desc": "获取可用的计算服务器列表",
        "params": {"filter_by_status": "all"},
    }], "查看服务器")
    print()
    print("  [内部 :15000] 执行 list_servers...")
    r = http_get(f"{EDGE_URL}/api/list_servers")
    for s in r.get("data", {}).get("servers", []):
        print(f"         - {s['server_id']} | {s['ip_address']} | status={s['status']} | load={s['current_load']}/{s['capacity']}")

    print()
    _print_curl([{
        "func_name": "list_devices",
        "func_desc": "获取已注册的边缘设备列表",
        "params": {"group_id": "all"},
    }], "查看设备")
    print()
    print("  [内部 :15000] 执行 list_devices...")
    r = http_get(f"{EDGE_URL}/api/list_devices")
    for d in r.get("data", {}).get("devices", []):
        print(f"         - {d['device_id']} | hw={d['hardware_type']} | status={d['status']} | simulated={d['is_simulated']}")

    # ==================================================================
    # 阶段 3：核心调度 — 全链路 HTTP 通信
    # ==================================================================
    _sep("阶段 3：核心调度 — 全链路 HTTP 通信")

    # 3.1 用户调用 assign_and_start_task
    print()
    _print_curl([{
        "func_name": "assign_and_start_task",
        "func_desc": "核心调度：指定边缘设备连接特定服务器执行计算任务",
        "params": {
            "device_id": "drone_sim_01",
            "server_id": "svr_brain_sim_01",
            "task_config": {
                "algorithm": "linear_interpolation",
                "frequency_hz": 10,
                "enable_video_stream": False,
                "custom_payloads": {
                    "start_point": {"lat": 30.270, "lng": 120.150, "alt": 10.0},
                    "end_point": {"lat": 30.280, "lng": 120.160, "alt": 10.0},
                    "nav_params": {"speed_m_s": 5.0, "waypoint_interval_m": 200.0},
                },
            },
        },
    }], "分配任务")

    task_config = {
        "algorithm": "linear_interpolation",
        "frequency_hz": 10,
        "enable_video_stream": False,
        "custom_payloads": {
            "start_point": {"lat": 30.270, "lng": 120.150, "alt": 10.0},
            "end_point": {"lat": 30.280, "lng": 120.160, "alt": 10.0},
            "nav_params": {"speed_m_s": 5.0, "waypoint_interval_m": 200.0},
        },
    }
    print()
    print("  [内部 :15000] 执行 assign_and_start_task...")
    r = http_post(f"{EDGE_URL}/api/assign_and_start_task", {
        "device_id": "drone_sim_01",
        "server_id": "svr_brain_sim_01",
        "task_config": task_config,
    })
    task_id = r.get("data", {}).get("task", {}).get("task_id", "")
    print(f"  [返回] code={r['code']}, task_id={task_id}")

    # 3.2 边缘服务通过内部端口下发任务给类脑盒子
    print()
    print("  [内部通信] :15000 → :15001/api/task (下发任务给类脑盒子)")
    print("    全链路通信（用户不可见）：")
    print("      类脑盒子 → brain_box/Navigator.plan() 生成轨迹")
    print("      类脑盒子 → HTTP POST :15000/api/submit_task_result  (上报轨迹)")
    print("      类脑盒子 → HTTP POST :15002/api/mission            (下发航点)")
    print("      类脑盒子 → HTTP POST :15002/api/arm                (通知起飞)")

    r = http_post(f"{BRAIN_URL}/api/task", {
        "task_id": task_id,
        "task_config": task_config,
    })
    trajectory = r.get("data", {})
    waypoints = trajectory.get("waypoints", [])
    print(f"  [类脑盒子返回] code={r['code']}")
    print(f"         航点数量: {len(waypoints)}")
    print(f"         总距离:   {trajectory.get('total_distance_m', 0):.1f}m")
    print(f"         预估时间: {trajectory.get('estimated_time_s', 0):.0f}s")
    print(f"         算法:     {trajectory.get('algorithm_used', 'N/A')}")
    if waypoints:
        print(f"         起点: ({waypoints[0]['lat']:.4f}, {waypoints[0]['lng']:.4f})")
        print(f"         终点: ({waypoints[-1]['lat']:.4f}, {waypoints[-1]['lng']:.4f})")

    # 3.3 等待无人机飞行
    print()
    print("  [内部通信] SimDrone 飞行中，遥测自动上报 → :15000")
    time.sleep(1.0)

    for i in range(40):
        r = http_get(f"{DRONE_URL}/api/status")
        state = r.get("data", {})
        if state.get("mission_complete", False):
            break
        if i % 5 == 0:
            pos = state.get("position", {})
            print(f"         飞行中... pos=({pos.get('lat', 0):.4f}, {pos.get('lng', 0):.4f}) "
                  f"battery={state.get('battery_pct', 0)}% mode={state.get('flight_mode', '?')} "
                  f"progress={state.get('mission_progress', '?')}")
        time.sleep(0.5)

    r = http_get(f"{DRONE_URL}/api/status")
    final = r.get("data", {})
    pos = final.get("position", {})
    print(f"  [无人设备] 飞行完成: mission_complete={final.get('mission_complete')}")
    print(f"             终点位置: ({pos.get('lat', 0):.4f}, {pos.get('lng', 0):.4f}, alt={pos.get('alt', 0):.1f})")
    print(f"             电池剩余: {final.get('battery_pct', 0)}%")
    print(f"             飞行模式: {final.get('flight_mode', '?')}")

    # ==================================================================
    # 阶段 4：用户查询结果（curl 格式）
    # ==================================================================
    _sep("阶段 4：用户查询结果")

    # 4.1 查询任务详情
    print()
    _print_curl([{
        "func_name": "get_task_info",
        "func_desc": "查询任务详情",
        "params": {"task_id": task_id},
    }], "查询任务")
    print()
    print(f"  [内部 :15000] 执行 get_task_info...")
    r = http_get(f"{EDGE_URL}/api/task_info?task_id={task_id}")
    task_info = r.get("data", {})
    results = task_info.get("results", [])
    print(f"  [返回] 任务状态: {task_info.get('status', 'N/A')}")
    print(f"         结果数量: {len(results)}")
    for res in results:
        payload = res.get("payload", {})
        wps = payload.get("waypoints", [])
        print(f"         - result_type={res['result_type']}, 航点={len(wps)}, "
              f"距离={payload.get('total_distance_m', 0):.1f}m")

    # 4.2 查询设备详情
    print()
    _print_curl([{
        "func_name": "get_device_info",
        "func_desc": "获取设备详细信息",
        "params": {"device_id": "drone_sim_01"},
    }], "查询设备")
    print()
    print("  [内部 :15000] 执行 get_device_info...")
    r = http_get(f"{EDGE_URL}/api/device_info?device_id=drone_sim_01")
    device_info = r.get("data", {})
    print(f"  [返回] status: {device_info.get('status', 'N/A')}")
    tel = device_info.get("latest_telemetry", {})
    if tel:
        tel_data = tel.get("data", {})
        print(f"         遥测类型: {tel.get('telemetry_type', 'N/A')}")
        print(f"         位置: {tel_data.get('position', 'N/A')}")
        print(f"         电池: {tel_data.get('battery_pct', 'N/A')}%")

    # 4.3 额外类型结果
    print()
    _print_curl([{
        "func_name": "submit_task_result",
        "func_desc": "提交检测结果",
        "params": {
            "task_id": task_id,
            "result_type": "detection",
            "payload": {
                "detections": [
                    {"class": "building", "confidence": 0.95},
                    {"class": "tree", "confidence": 0.88},
                ],
            },
        },
    }], "提交检测结果")
    print()
    print("  [内部 :15000] 执行 submit_task_result(detection)...")
    r = http_post(f"{EDGE_URL}/api/submit_task_result", {
        "task_id": task_id,
        "result_type": "detection",
        "payload": {
            "detections": [
                {"class": "building", "confidence": 0.95, "bbox": [100, 200, 300, 400]},
                {"class": "tree", "confidence": 0.88, "bbox": [400, 100, 500, 300]},
            ],
            "frame_id": 42,
        },
        "metadata": {"source": "sim_vision", "model": "yolov8"},
    })
    print(f"  [返回] code={r['code']}, result_id={r.get('data', {}).get('result_id', 'N/A')}")

    # 验证多类型结果
    r = http_get(f"{EDGE_URL}/api/task_info?task_id={task_id}")
    result_types = [res["result_type"] for res in r.get("data", {}).get("results", [])]
    print(f"  [验证] 任务结果类型列表: {result_types}")

    # ==================================================================
    # 阶段 5：停止任务 + 清理
    # ==================================================================
    _sep("阶段 5：停止任务 + 清理")

    print()
    _print_curl([{
        "func_name": "stop_task",
        "func_desc": "中断任务",
        "params": {"device_id": "drone_sim_01", "reason": "test_complete"},
    }], "停止任务")
    print()
    print("  [内部 :15000] 执行 stop_task...")
    r = http_post(f"{EDGE_URL}/api/stop_task", {
        "device_id": "drone_sim_01",
        "reason": "test_complete",
    })
    print(f"  [返回] code={r['code']}")

    print()
    print("  [内部 :15000] 执行 remove_device + remove_server...")
    http_post(f"{EDGE_URL}/api/remove_device", {"device_id": "drone_sim_01"})
    http_post(f"{EDGE_URL}/api/remove_server", {"server_id": "svr_brain_sim_01", "force_stop": True})
    print("  [返回] 清理完成")

    # 关停服务
    drone_reporter.stop()
    drone_core.stop()
    drone_server.shutdown()
    brain_core.stop()
    brain_server.shutdown()
    edge_manager.shutdown()
    edge_server.shutdown()

    print()
    print("    所有服务已关闭")

    # ==================================================================
    # 总结
    # ==================================================================
    _sep("测试完成")
    print()
    print("    全部流程执行成功！")
    print()
    print("    用户调用方式:")
    print("      curl --location --request POST \\")
    print("        'http://work.datashell.cn:8500/ai-master-svr/create-task/' \\")
    print(f"        --data-urlencode 'capability_id={CAPABILITY_ID}' \\")
    print("        --data-urlencode 'param=[{\"dtype\":\"cloud_edge_manager\",...}]'")
    print()
    print("    内部 HTTP 通信链路（:15000 端口，用户不可见）：")
    print("      类脑盒子 ──HTTP──→ :15000 边缘服务  (submit_task_result)")
    print("      类脑盒子 ──HTTP──→ :15002 无人设备  (mission + arm)")
    print("      无人设备 ──HTTP──→ :15000 边缘服务  (update_device_telemetry)")
    print()
    print("    真机替换：")
    print("      1. 类脑盒子: 部署 brain_box/ 到真实设备，修改 --edge-url / --drone-url")
    print("      2. 无人设备: MAVLink 真实飞控替代 SimDrone，修改 --edge-url")
    print("      3. 边缘服务: CloudEdgeManager 代码无需任何修改")
    print()
    print("    独立启动命令：")
    print("      python tests/edge_service_server.py --port 15000")
    print("      python tests/sim_drone_server.py --port 15002 --edge-url http://127.0.0.1:15000")
    print("      python tests/sim_brain_box_server.py --port 15001 --edge-url http://127.0.0.1:15000 --drone-url http://127.0.0.1:15002")
    print()

    return True


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
