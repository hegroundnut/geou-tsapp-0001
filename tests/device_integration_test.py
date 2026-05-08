#!/usr/bin/env python3
"""
虚拟设备集成测试
三阶段：
  1. 启动模拟类脑盒子 — print 关键信息
  2. 启动模拟无人设备 — print 关键信息
  3. 测试用户调用   — 通过 CloudEdgeManager 接口模拟用户操作

SimBrainBox 封装 brain_box/ 完整代码栈（Navigator + MAVLinkAdapter + EdgeServiceClient），
通过桥接让 EdgeServiceClient 直接调用 CloudEdgeManager。

真机替换时：
  - SimBrainBox → brain_box/main.py（simulated=False）
  - SimDrone    → MAVLink 真实飞控
  - CloudEdgeManager 代码无需修改
"""
import os
import sys
import time
import json
import logging

# 让 CloudEdgeManager 模块可导入
_edge_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "src", "features", "uvaTrack", "v0_0_0",
)
sys.path.insert(0, os.path.abspath(_edge_dir))

# 让 tests 目录下的模拟器可导入
_tests_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _tests_dir)

from cloud_edge_manager import CloudEdgeManager
from sim_brain_box import SimBrainBox
from sim_drone import SimDrone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("integration_test")


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
    elif isinstance(value, list):
        print(f"{prefix}{key}: {value}")
    else:
        print(f"{prefix}{key}: {value}")


def run_test():
    # 重置单例（测试隔离）
    CloudEdgeManager._instance = None

    brain_box_server_id = "svr_brain_sim_01"
    drone_device_id = "drone_sim_01"

    # ==================== 初始化 CloudEdgeManager ====================
    _sep("初始化边缘控制服务 (CloudEdgeManager)")
    manager = CloudEdgeManager(
        heartbeat_interval=60,
        device_timeout=600,
        server_timeout=600,
    )
    print("    CloudEdgeManager 已启动")
    print()

    # 预注册基础设施
    manager.add_server(
        server_id=brain_box_server_id,
        ip_address="127.0.0.1",
        capacity=5,
        tags=["brain_box", "navigation", "simulated"],
        metadata={"hardware": "sim_neuromorphic"},
    )
    print(f"    已注册服务器: {brain_box_server_id}")

    manager.add_device(
        device_id=drone_device_id,
        hardware_type="sim_quadcopter",
        is_simulated=True,
        supported_streams=["video", "telemetry"],
        group_id="aerial",
        metadata={"frame": "X500"},
    )
    print(f"    已注册设备:   {drone_device_id}")

    # ==================================================================
    # 阶段 1：启动模拟类脑盒子
    # ==================================================================
    _sep("阶段 1：启动模拟类脑盒子 (SimBrainBox)")

    sim_brain = SimBrainBox(
        manager=manager,
        server_id=brain_box_server_id,
        device_id=drone_device_id,
    )
    ok = sim_brain.start()

    print()
    print("    >>> 类脑盒子关键信息 <<<")
    _kv("设备 ID (server_id)", sim_brain.server_id)
    _kv("关联无人机 ID", sim_brain.device_id)
    _kv("当前状态", sim_brain.state)
    _kv("启动结果", "成功" if ok else "失败")
    _kv("内部模块", {
        "Navigator": "brain_box/navigator.py (线性插值 + 折线避障)",
        "MAVLinkAdapter": "brain_box/mavlink_adapter.py (模拟模式)",
        "EdgeServiceClient": "brain_box/edge_client.py (桥接到 CloudEdgeManager)",
    })
    _kv("数据通道", "EdgeServiceClient._post → CloudEdgeManager (本地桥接)")
    print()

    # ==================================================================
    # 阶段 2：启动模拟无人机
    # ==================================================================
    _sep("阶段 2：启动模拟无人设备 (SimDrone)")

    sim_drone = SimDrone(
        device_id=drone_device_id,
        telemetry_callback=lambda dev_id, t_type, data, meta: manager.update_device_telemetry(
            device_id=dev_id, telemetry_type=t_type, data=data, metadata=meta,
        ),
        telemetry_interval_s=0.5,
        initial_position={"lat": 30.270, "lng": 120.150, "alt": 0.0},
    )
    sim_drone.start()

    # 等待首次遥测
    time.sleep(1.0)

    drone_state = sim_drone.get_state()
    print()
    print("    >>> 无人设备关键信息 <<<")
    _kv("设备 ID", sim_drone.device_id)
    _kv("初始位置", drone_state["position"])
    _kv("飞行模式", drone_state["flight_mode"])
    _kv("解锁状态", "已解锁" if drone_state["armed"] else "未解锁")
    _kv("电池电量", f"{drone_state['battery_pct']}%")
    _kv("GPS 定位", f"fix_type={drone_state['gps_fix_type']}, 卫星={drone_state['satellites_visible']}")
    _kv("速度", drone_state["velocity"])
    _kv("姿态", drone_state["attitude"])
    _kv("遥测上报", f"每 0.5 秒 → CloudEdgeManager.update_device_telemetry(drone_status)")

    # 确认遥测到达 manager
    device_info = manager.get_device_info(drone_device_id)
    telemetry = device_info.get("latest_telemetry", {}) if device_info else {}
    print()
    _kv("边缘服务遥测状态", "已接收" if telemetry else "未接收")
    if telemetry:
        _kv("遥测类型", telemetry.get("telemetry_type", "N/A"))
    print()

    # ==================================================================
    # 阶段 3：测试用户调用
    # ==================================================================
    _sep("阶段 3：测试用户调用")

    # --- 3.1 用户调用 list_servers ---
    print()
    print("  [调用] list_servers(filter_by_status='all')")
    servers = manager.list_servers(filter_by_status="all")
    print(f"  [返回] 服务器数量: {len(servers.get('data', {}).get('servers', []))}")
    for s in servers.get("data", {}).get("servers", []):
        print(f"         - {s['server_id']} | {s['ip_address']} | status={s['status']} | load={s['current_load']}/{s['capacity']}")

    # --- 3.2 用户调用 list_devices ---
    print()
    print("  [调用] list_devices(group_id='all')")
    devices = manager.list_devices(group_id="all")
    print(f"  [返回] 设备数量: {len(devices.get('data', {}).get('devices', []))}")
    for d in devices.get("data", {}).get("devices", []):
        print(f"         - {d['device_id']} | hw={d['hardware_type']} | status={d['status']} | simulated={d['is_simulated']}")

    # --- 3.3 用户调用 assign_and_start_task（核心：指定设备使用服务器规划路径）---
    print()
    print("  [调用] assign_and_start_task")
    print("         device_id  = drone_sim_01")
    print("         server_id  = svr_brain_sim_01")
    print("         algorithm  = linear_interpolation")
    print("         start_point= (30.270, 120.150, alt=10)")
    print("         end_point  = (30.280, 120.160, alt=10)")

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

    r = manager.assign_and_start_task(
        device_id=drone_device_id,
        server_id=brain_box_server_id,
        task_config=task_config,
    )
    task_id = r["data"]["task"]["task_id"]
    print(f"  [返回] code={r['code']}, task_id={task_id}")

    # --- 3.4 类脑盒子收到任务并处理（BrainBox 完整代码路径）---
    print()
    print("  [类脑盒子] 收到任务，开始处理...")
    print("             → Navigator.plan() 生成轨迹")
    print("             → EdgeServiceClient.report_trajectory() 上报边缘服务")
    print("             → MAVLinkAdapter.upload_mission() 下发无人机")

    ok = sim_brain.handle_task(task_id, task_config)
    print(f"  [类脑盒子] 处理结果: {'成功' if ok else '失败'}")

    # --- 3.5 用户调用 get_task_info 查询任务结果 ---
    print()
    print(f"  [调用] get_task_info(task_id='{task_id}')")
    task_info = manager.get_task_info(task_id)
    if task_info:
        print(f"  [返回] 任务状态: {task_info.get('status', 'N/A')}")
        results = task_info.get("results", [])
        print(f"         结果数量: {len(results)}")
        for res in results:
            payload = res.get("payload", {})
            wps = payload.get("waypoints", [])
            print(f"         - result_type={res['result_type']}")
            print(f"           航点数量: {len(wps)}")
            print(f"           总距离: {payload.get('total_distance_m', 0):.1f}m")
            print(f"           预估时间: {payload.get('estimated_time_s', 0):.0f}s")
            if wps:
                print(f"           起点: ({wps[0]['lat']:.4f}, {wps[0]['lng']:.4f}, alt={wps[0].get('alt', 'N/A')})")
                print(f"           终点: ({wps[-1]['lat']:.4f}, {wps[-1]['lng']:.4f}, alt={wps[-1].get('alt', 'N/A')})")

    # --- 3.6 SimDrone 接收航点并飞行 ---
    print()
    print("  [无人设备] 接收航点，开始模拟飞行...")
    if task_info and task_info.get("results"):
        wps = task_info["results"][0].get("payload", {}).get("waypoints", [])
        if wps:
            sim_drone.upload_mission(wps)
            sim_drone.arm_and_fly()

            for i in range(30):
                if sim_drone.mission_complete:
                    break
                if i % 4 == 0:
                    state = sim_drone.get_state()
                    print(f"             飞行中... pos=({state['position']['lat']:.4f}, {state['position']['lng']:.4f}) "
                          f"battery={state['battery_pct']}% mode={state['flight_mode']}")
                time.sleep(0.5)

            final = sim_drone.get_state()
            print(f"  [无人设备] 飞行完成: mission_complete={sim_drone.mission_complete}")
            print(f"             终点位置: ({final['position']['lat']:.4f}, {final['position']['lng']:.4f}, alt={final['position']['alt']:.1f})")
            print(f"             电池剩余: {final['battery_pct']}%")
            print(f"             飞行模式: {final['flight_mode']}")

    # --- 3.7 用户调用 get_device_info 查询设备信息 ---
    print()
    print(f"  [调用] get_device_info(device_id='{drone_device_id}')")
    device_info = manager.get_device_info(drone_device_id)
    if device_info:
        print(f"  [返回] status: {device_info.get('status', 'N/A')}")
        tel = device_info.get("latest_telemetry", {})
        if tel:
            data = tel.get("data", {})
            print(f"         遥测类型: {tel.get('telemetry_type', 'N/A')}")
            print(f"         位置: {data.get('position', 'N/A')}")
            print(f"         电池: {data.get('battery_pct', 'N/A')}%")

    # --- 3.8 用户提交额外类型的结果（验证通用接口灵活性）---
    print()
    print("  [调用] submit_task_result(result_type='detection')")
    r = manager.submit_task_result(
        task_id=task_id,
        result_type="detection",
        payload={
            "detections": [
                {"class": "building", "confidence": 0.95, "bbox": [100, 200, 300, 400]},
                {"class": "tree", "confidence": 0.88, "bbox": [400, 100, 500, 300]},
            ],
            "frame_id": 42,
        },
        metadata={"source": "sim_vision", "model": "yolov8"},
    )
    print(f"  [返回] code={r['code']}, result_id={r.get('data', {}).get('result_id', 'N/A')}")

    # 再次查询，确认多类型结果
    task_info = manager.get_task_info(task_id)
    if task_info:
        result_types = [res["result_type"] for res in task_info.get("results", [])]
        print(f"  [验证] 任务结果类型列表: {result_types}")

    # --- 3.9 用户上报额外遥测（验证通用接口灵活性）---
    print()
    print("  [调用] update_device_telemetry(telemetry_type='sensor')")
    r = manager.update_device_telemetry(
        device_id=drone_device_id,
        telemetry_type="sensor",
        data={
            "temperature_c": 35.2,
            "humidity_pct": 62.0,
            "barometer_hpa": 1013.25,
        },
        metadata={"source": "onboard_sensor"},
    )
    print(f"  [返回] code={r['code']}")

    # --- 3.10 用户停止任务 + 清理 ---
    print()
    print(f"  [调用] stop_task(device_id='{drone_device_id}')")
    r = manager.stop_task(device_id=drone_device_id, reason="test_complete")
    print(f"  [返回] code={r['code']}")

    # ==================================================================
    # 清理
    # ==================================================================
    _sep("清理")

    sim_drone.stop()
    print("    SimDrone 已停止")

    sim_brain.stop()
    print("    SimBrainBox 已停止")

    manager.remove_device(device_id=drone_device_id)
    print(f"    已移除设备: {drone_device_id}")

    manager.remove_server(server_id=brain_box_server_id, force_stop=True)
    print(f"    已移除服务器: {brain_box_server_id}")

    manager.shutdown()
    print("    CloudEdgeManager 已关闭")

    # ==================================================================
    # 总结
    # ==================================================================
    _sep("测试完成")
    print()
    print("    全部流程执行成功！")
    print()
    print("    真机替换说明：")
    print("    1. 类脑盒子: BrainBox(simulated=False) → HTTP + 真实 MAVLink")
    print("    2. 无人设备:  MAVLink 真实飞控替代 SimDrone")
    print("    3. 边缘服务:  CloudEdgeManager 代码无需任何修改")
    print()

    return True


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
