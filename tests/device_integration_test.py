#!/usr/bin/env python3
"""
虚拟设备集成测试
编排 CloudEdgeManager + SimBrainBox（封装 brain_box/ 真实代码）+ SimDrone 的完整交互流程。

SimBrainBox 内部使用 brain_box/ 的完整代码栈：
  - Navigator 生成轨迹
  - MAVLinkAdapter（模拟模式）模拟无人机飞行
  - EdgeServiceClient 通过桥接直接调用 CloudEdgeManager

流程：
  1. 启动 CloudEdgeManager
  2. 注册服务器（类脑盒子）+ 设备（无人机）
  3. 启动 SimBrainBox（内含 brain_box 全套代码 + 模拟 MAVLink）
  4. 启动 SimDrone（独立遥测上报）
  5. 分配任务 → BrainBox.handle_navigation() 生成轨迹 → 桥接上报 → 模拟飞行
  6. 查询任务信息、设备信息，验证数据完整性
  7. 清理

真机替换时：
  - SimBrainBox → brain_box/main.py（EdgeServiceClient 切换 HTTP，MAVLinkAdapter 连真机）
  - SimDrone → 真实 MAVLink 飞控
  - CloudEdgeManager 代码无需任何修改
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


# ---------------------------------------------------------------------------
#  辅助
# ---------------------------------------------------------------------------

_pass_count = 0
_fail_count = 0


def _check(label: str, condition: bool, detail: str = ""):
    global _pass_count, _fail_count
    if condition:
        _pass_count += 1
        logger.info("  PASS %s %s", label, detail)
    else:
        _fail_count += 1
        logger.error("  FAIL %s %s", label, detail)


# ---------------------------------------------------------------------------
#  主测试
# ---------------------------------------------------------------------------

def run_test():
    global _pass_count, _fail_count
    _pass_count = 0
    _fail_count = 0

    # 重置单例（测试隔离）
    CloudEdgeManager._instance = None

    manager = CloudEdgeManager(
        heartbeat_interval=60,
        device_timeout=600,
        server_timeout=600,
    )

    brain_box_server_id = "svr_brain_sim_01"
    drone_device_id = "drone_sim_01"

    # ==================================================================
    logger.info("=" * 60)
    logger.info("Phase 1: 注册基础设施")
    logger.info("=" * 60)

    r = manager.add_server(
        server_id=brain_box_server_id,
        ip_address="127.0.0.1",
        capacity=5,
        tags=["brain_box", "navigation", "simulated"],
        metadata={"hardware": "sim_neuromorphic"},
    )
    _check("注册类脑服务器", r["code"] == 0, f"server_id={brain_box_server_id}")

    r = manager.add_device(
        device_id=drone_device_id,
        hardware_type="sim_quadcopter",
        is_simulated=True,
        supported_streams=["video", "telemetry"],
        group_id="aerial",
        metadata={"frame": "X500"},
    )
    _check("注册虚拟无人机", r["code"] == 0, f"device_id={drone_device_id}")

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 2: 初始化虚拟设备（使用 brain_box/ 完整代码）")
    logger.info("=" * 60)

    # SimBrainBox 封装 brain_box/main.py 中的 BrainBox，
    # 通过桥接让其 EdgeServiceClient 直接调用 CloudEdgeManager
    sim_brain = SimBrainBox(
        manager=manager,
        server_id=brain_box_server_id,
        device_id=drone_device_id,
    )
    ok = sim_brain.start()
    _check("SimBrainBox 启动（brain_box 代码栈）", ok)

    # SimDrone 独立上报遥测（补充 MAVLinkAdapter 模拟之外的遥测）
    sim_drone = SimDrone(
        device_id=drone_device_id,
        telemetry_callback=lambda dev_id, t_type, data, meta: manager.update_device_telemetry(
            device_id=dev_id, telemetry_type=t_type, data=data, metadata=meta,
        ),
        telemetry_interval_s=0.5,
        initial_position={"lat": 30.270, "lng": 120.150, "alt": 0.0},
    )
    sim_drone.start()
    _check("SimDrone 启动", True)

    # 等待遥测到达
    time.sleep(1.5)

    device_info = manager.get_device_info(drone_device_id)
    _check(
        "初始遥测已到达",
        device_info is not None and device_info.get("latest_telemetry") is not None,
        f"telemetry_type={device_info.get('latest_telemetry', {}).get('telemetry_type', 'N/A')}"
        if device_info else "",
    )

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 3: 分配导航任务")
    logger.info("=" * 60)

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
    _check("任务分配", r["code"] == 0)
    task_id = r["data"]["task"]["task_id"]
    logger.info("  task_id = %s", task_id)

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 4: BrainBox 处理任务（Navigator → 上报轨迹 → 模拟飞行）")
    logger.info("=" * 60)

    # 调用 brain_box 的 handle_navigation — 完整走一遍真实代码路径
    ok = sim_brain.handle_task(task_id, task_config)
    _check("BrainBox.handle_navigation 执行成功", ok)

    # 验证轨迹已通过桥接写入 CloudEdgeManager
    task_info = manager.get_task_info(task_id)
    _check(
        "轨迹已上报到边缘服务（通过桥接）",
        task_info is not None and len(task_info.get("results", [])) > 0,
        f"results count={len(task_info.get('results', []))}" if task_info else "",
    )
    if task_info and task_info.get("results"):
        first_result = task_info["results"][0]
        _check("结果类型为 trajectory", first_result.get("result_type") == "trajectory")
        waypoints = first_result.get("payload", {}).get("waypoints", [])
        _check("轨迹包含航点", len(waypoints) > 0, f"{len(waypoints)} 航点")
        if waypoints:
            _check(
                "航点格式正确（含 lat/lng/alt/seq）",
                all(k in waypoints[0] for k in ("lat", "lng", "alt", "seq")),
            )

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 5: 验证遥测持续上报")
    logger.info("=" * 60)

    # BrainBox 内部的 _status_forward_loop 也在通过桥接转发 MAVLink 模拟遥测
    time.sleep(2.0)

    device_info = manager.get_device_info(drone_device_id)
    telemetry = device_info.get("latest_telemetry", {}) if device_info else {}
    _check(
        "最新遥测类型为 drone_status",
        telemetry.get("telemetry_type") == "drone_status",
    )
    _check(
        "遥测包含位置数据",
        "position" in telemetry.get("data", {}),
    )
    _check(
        "遥测包含电池数据",
        "battery_pct" in telemetry.get("data", {}),
    )

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 6: SimDrone 独立飞行测试")
    logger.info("=" * 60)

    # SimDrone 也可以独立接收航点飞行（模拟另一架无人机）
    if task_info and task_info.get("results"):
        wps = task_info["results"][0].get("payload", {}).get("waypoints", [])
        if wps:
            sim_drone.upload_mission(wps)
            sim_drone.arm_and_fly()
            _check("SimDrone 接收航点并起飞", True)

            for _ in range(20):
                if sim_drone.mission_complete:
                    break
                time.sleep(0.5)

            _check("SimDrone 飞行任务完成", sim_drone.mission_complete)

            final_state = sim_drone.get_state()
            _check(
                "SimDrone 终点位置接近目标",
                abs(final_state["position"]["lat"] - 30.280) < 0.002
                and abs(final_state["position"]["lng"] - 120.160) < 0.002,
                f"pos=({final_state['position']['lat']:.4f}, {final_state['position']['lng']:.4f})",
            )
            _check("SimDrone 电池消耗", final_state["battery_pct"] < 100.0,
                   f"battery={final_state['battery_pct']}%")

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 7: 多类型结果提交测试")
    logger.info("=" * 60)

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
    _check("检测结果提交", r["code"] == 0)

    task_info = manager.get_task_info(task_id)
    _check(
        "任务包含多类型结果",
        task_info is not None and len(task_info.get("results", [])) == 2,
        f"results={[r.get('result_type') for r in task_info.get('results', [])]}"
        if task_info else "",
    )

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
    _check("传感器遥测提交", r["code"] == 0)

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 8: 清理")
    logger.info("=" * 60)

    sim_drone.stop()
    _check("SimDrone 停止", True)

    sim_brain.stop()
    _check("SimBrainBox 停止", True)

    r = manager.stop_task(device_id=drone_device_id, reason="test_complete")
    _check("任务停止", r["code"] == 0)

    r = manager.remove_device(device_id=drone_device_id)
    _check("移除无人机设备", r["code"] == 0)

    r = manager.remove_server(server_id=brain_box_server_id, force_stop=True)
    _check("移除类脑服务器", r["code"] == 0)

    manager.shutdown()

    # ==================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info("测试结果汇总")
    logger.info("=" * 60)
    total = _pass_count + _fail_count
    logger.info("通过: %d / %d", _pass_count, total)
    if _fail_count > 0:
        logger.error("失败: %d / %d", _fail_count, total)
    else:
        logger.info("全部通过!")
    logger.info("=" * 60)

    return _fail_count == 0


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
