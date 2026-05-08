#!/usr/bin/env python3
"""
HTTP 多服务集成测试 — 模拟最真实的云边协同场景

三个独立 HTTP 服务：
  :15000  边缘控制服务  (CloudEdgeManager)
  :15001  模拟类脑盒子  (SimBrainBox)
  :15002  模拟无人设备  (SimDrone)

通信链路（全部走 HTTP）：
  用户/测试 ──HTTP──→ :15000 边缘服务 (注册/分配任务/查询)
  用户/测试 ──HTTP──→ :15001 类脑盒子 (下发任务)
  类脑盒子  ──HTTP──→ :15000 边缘服务 (submit_task_result 上报轨迹)
  类脑盒子  ──HTTP──→ :15002 无人设备 (下发航点 + 通知起飞)
  无人设备  ──HTTP──→ :15000 边缘服务 (update_device_telemetry 遥测上报)

运行：python tests/device_integration_test.py
"""
import os
import sys
import time
import json
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


# ---------------------------------------------------------------------------
#  测试主流程
# ---------------------------------------------------------------------------

def run_test():
    # ==================================================================
    # 启动三个 HTTP 服务
    # ==================================================================
    _sep("启动三个 HTTP 服务（模拟真实部署）")

    # 1. 启动边缘控制服务
    edge_server, edge_manager = start_edge_service(port=15000, blocking=False)
    time.sleep(0.3)

    # 2. 启动模拟无人设备（先启动，这样类脑盒子可以给它发命令）
    drone_server, drone_reporter, drone_core = start_drone_server(
        port=15002,
        device_id="drone_sim_01",
        edge_url=EDGE_URL,
        initial_position={"lat": 30.270, "lng": 120.150, "alt": 0.0},
        telemetry_interval=1.0,
        blocking=False,
    )
    time.sleep(0.3)

    # 3. 启动模拟类脑盒子
    brain_server, brain_core = start_brain_box_server(
        port=15001,
        server_id="svr_brain_sim_01",
        edge_url=EDGE_URL,
        drone_url=DRONE_URL,
        blocking=False,
    )
    time.sleep(0.3)

    print()
    print("    三个服务均已启动:")
    print(f"      :15000  边缘控制服务  (CloudEdgeManager)")
    print(f"      :15001  模拟类脑盒子  (SimBrainBox)")
    print(f"      :15002  模拟无人设备  (SimDrone)")
    print()

    # ==================================================================
    # 阶段 1：HTTP 验证各服务可达
    # ==================================================================
    _sep("阶段 1：验证各服务 HTTP 可达")

    print()
    print("  [HTTP GET] → 边缘服务 :15000/api/list_servers")
    r = http_get(f"{EDGE_URL}/api/list_servers")
    print(f"  [返回] code={r['code']}, 服务器数量={r.get('data', {}).get('total', 0)}")

    print()
    print("  [HTTP GET] → 类脑盒子 :15001/api/status")
    r = http_get(f"{BRAIN_URL}/api/status")
    brain_status = r.get("data", {})
    print(f"  [返回] server_id={brain_status.get('server_id')}, state={brain_status.get('state')}")
    print(f"         支持算法: {brain_status.get('algorithms')}")
    print(f"         边缘服务: {brain_status.get('edge_url')}")
    print(f"         无人机:   {brain_status.get('drone_url')}")

    print()
    print("  [HTTP GET] → 无人设备 :15002/api/status")
    r = http_get(f"{DRONE_URL}/api/status")
    drone_status = r.get("data", {})
    print(f"  [返回] device_id={drone_status.get('device_id')}")
    _kv("位置", drone_status.get("position"))
    _kv("电池", f"{drone_status.get('battery_pct')}%")
    _kv("飞行模式", drone_status.get("flight_mode"))
    _kv("GPS", f"fix_type={drone_status.get('gps_fix_type')}, 卫星={drone_status.get('satellites_visible')}")

    # ==================================================================
    # 阶段 2：通过边缘服务 HTTP 注册基础设施
    # ==================================================================
    _sep("阶段 2：HTTP 注册基础设施")

    print()
    print("  [HTTP POST] → :15000/api/add_server")
    r = http_post(f"{EDGE_URL}/api/add_server", {
        "server_id": "svr_brain_sim_01",
        "ip_address": "127.0.0.1",
        "capacity": 5,
        "tags": ["brain_box", "navigation", "simulated"],
        "metadata": {"hardware": "sim_neuromorphic"},
    })
    print(f"  [返回] code={r['code']}, msg={r['msg']}")

    print()
    print("  [HTTP POST] → :15000/api/add_device")
    r = http_post(f"{EDGE_URL}/api/add_device", {
        "device_id": "drone_sim_01",
        "hardware_type": "sim_quadcopter",
        "is_simulated": True,
        "supported_streams": ["video", "telemetry"],
        "group_id": "aerial",
        "metadata": {"frame": "X500"},
    })
    print(f"  [返回] code={r['code']}, msg={r['msg']}")

    # 查看注册结果
    print()
    print("  [HTTP GET] → :15000/api/list_servers")
    r = http_get(f"{EDGE_URL}/api/list_servers")
    for s in r.get("data", {}).get("servers", []):
        print(f"         - {s['server_id']} | {s['ip_address']} | status={s['status']} | load={s['current_load']}/{s['capacity']}")

    print()
    print("  [HTTP GET] → :15000/api/list_devices")
    r = http_get(f"{EDGE_URL}/api/list_devices")
    for d in r.get("data", {}).get("devices", []):
        print(f"         - {d['device_id']} | hw={d['hardware_type']} | status={d['status']} | simulated={d['is_simulated']}")

    # ==================================================================
    # 阶段 3：核心调度 — 分配任务 + 全链路 HTTP 通信
    # ==================================================================
    _sep("阶段 3：核心调度 — 全链路 HTTP 通信")

    # 3.1 通过边缘服务分配任务
    print()
    print("  [HTTP POST] → :15000/api/assign_and_start_task")
    print("    device_id  = drone_sim_01")
    print("    server_id  = svr_brain_sim_01")
    print("    algorithm  = linear_interpolation")
    print("    start/end  = (30.270,120.150) → (30.280,120.160)")

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
    r = http_post(f"{EDGE_URL}/api/assign_and_start_task", {
        "device_id": "drone_sim_01",
        "server_id": "svr_brain_sim_01",
        "task_config": task_config,
    })
    task_id = r.get("data", {}).get("task", {}).get("task_id", "")
    print(f"  [返回] code={r['code']}, task_id={task_id}")

    # 3.2 HTTP 调用类脑盒子处理任务
    print()
    print("  [HTTP POST] → :15001/api/task  (下发任务给类脑盒子)")
    print("    全链路通信：")
    print("      类脑盒子 → Navigator 生成轨迹")
    print("      类脑盒子 → HTTP POST :15000/api/submit_task_result  (上报轨迹)")
    print("      类脑盒子 → HTTP POST :15002/api/mission            (下发航点)")
    print("      类脑盒子 → HTTP POST :15002/api/arm                (通知起飞)")

    r = http_post(f"{BRAIN_URL}/api/task", {
        "task_id": task_id,
        "task_config": task_config,
    })
    trajectory = r.get("data", {})
    waypoints = trajectory.get("waypoints", [])
    print(f"  [返回] code={r['code']}")
    print(f"         航点数量: {len(waypoints)}")
    print(f"         总距离:   {trajectory.get('total_distance_m', 0):.1f}m")
    print(f"         预估时间: {trajectory.get('estimated_time_s', 0):.0f}s")
    print(f"         算法:     {trajectory.get('algorithm_used', 'N/A')}")
    if waypoints:
        print(f"         起点: ({waypoints[0]['lat']:.4f}, {waypoints[0]['lng']:.4f})")
        print(f"         终点: ({waypoints[-1]['lat']:.4f}, {waypoints[-1]['lng']:.4f})")

    # 3.3 等待无人机飞行
    print()
    print("  [等待] 无人机飞行中（HTTP 轮询 :15002/api/status）...")
    time.sleep(1.0)  # 给飞行线程一点启动时间

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
    # 阶段 4：通过边缘服务查询结果（验证 HTTP 回调已到达）
    # ==================================================================
    _sep("阶段 4：通过边缘服务 HTTP 查询结果")

    # 4.1 查询任务详情（含轨迹结果）
    print()
    print(f"  [HTTP GET] → :15000/api/task_info?task_id={task_id}")
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

    # 4.2 查询设备详情（含遥测）
    print()
    print("  [HTTP GET] → :15000/api/device_info?device_id=drone_sim_01")
    r = http_get(f"{EDGE_URL}/api/device_info?device_id=drone_sim_01")
    device_info = r.get("data", {})
    print(f"  [返回] status: {device_info.get('status', 'N/A')}")
    tel = device_info.get("latest_telemetry", {})
    if tel:
        tel_data = tel.get("data", {})
        print(f"         遥测类型: {tel.get('telemetry_type', 'N/A')}")
        print(f"         位置: {tel_data.get('position', 'N/A')}")
        print(f"         电池: {tel_data.get('battery_pct', 'N/A')}%")

    # 4.3 额外类型结果（验证通用接口灵活性）
    print()
    print("  [HTTP POST] → :15000/api/submit_task_result  (type=detection)")
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

    # 4.4 额外遥测上报
    print()
    print("  [HTTP POST] → :15000/api/update_device_telemetry  (type=sensor)")
    r = http_post(f"{EDGE_URL}/api/update_device_telemetry", {
        "device_id": "drone_sim_01",
        "telemetry_type": "sensor",
        "data": {
            "temperature_c": 35.2,
            "humidity_pct": 62.0,
            "barometer_hpa": 1013.25,
        },
        "metadata": {"source": "onboard_sensor"},
    })
    print(f"  [返回] code={r['code']}")

    # 再次查询任务，验证多类型结果
    r = http_get(f"{EDGE_URL}/api/task_info?task_id={task_id}")
    result_types = [res["result_type"] for res in r.get("data", {}).get("results", [])]
    print(f"  [验证] 任务结果类型列表: {result_types}")

    # ==================================================================
    # 阶段 5：停止任务 + 清理
    # ==================================================================
    _sep("阶段 5：停止任务 + 清理")

    print()
    print("  [HTTP POST] → :15000/api/stop_task")
    r = http_post(f"{EDGE_URL}/api/stop_task", {
        "device_id": "drone_sim_01",
        "reason": "test_complete",
    })
    print(f"  [返回] code={r['code']}")

    print()
    print("  [HTTP POST] → :15000/api/remove_device")
    r = http_post(f"{EDGE_URL}/api/remove_device", {"device_id": "drone_sim_01"})
    print(f"  [返回] code={r['code']}")

    print()
    print("  [HTTP POST] → :15000/api/remove_server")
    r = http_post(f"{EDGE_URL}/api/remove_server", {"server_id": "svr_brain_sim_01", "force_stop": True})
    print(f"  [返回] code={r['code']}")

    # 关停服务
    drone_reporter.stop()
    drone_core.stop()
    drone_server.shutdown()
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
    print("    HTTP 通信链路验证：")
    print("      用户   ──HTTP──→ :15000 边缘服务   (注册/分配/查询)")
    print("      用户   ──HTTP──→ :15001 类脑盒子   (下发任务)")
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
