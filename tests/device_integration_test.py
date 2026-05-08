#!/usr/bin/env python3
"""
虚拟设备集成测试
编排 CloudEdgeManager + SimBrainBox + SimDrone 的完整交互流程。

流程：
  1. 启动 CloudEdgeManager
  2. 注册服务器（类脑盒子作为计算服务器）+ 设备（无人机）
  3. 启动 SimDrone（开始上报遥测）
  4. 分配任务 → SimBrainBox 生成轨迹 → 上报边缘 → 下发 SimDrone
  5. SimDrone 模拟飞行 → 持续上报遥测
  6. 查询任务信息、设备信息，验证数据完整性
  7. 清理

真机替换时无需修改本测试中 CloudEdgeManager 的任何调用，
只需将 SimBrainBox/SimDrone 替换为实际 HTTP 客户端或 MAVLink 连接。
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
        logger.info("  ✓ %s %s", label, detail)
    else:
        _fail_count += 1
        logger.error("  ✗ %s %s", label, detail)


def _pp(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


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
        heartbeat_interval=60,   # 测试中不需要频繁心跳
        device_timeout=600,
        server_timeout=600,
    )

    brain_box_server_id = "svr_brain_sim_01"
    drone_device_id = "drone_sim_01"

    logger.info("=" * 60)
    logger.info("Phase 1: 注册基础设施")
    logger.info("=" * 60)

    # 注册类脑盒子作为计算服务器
    r = manager.add_server(
        server_id=brain_box_server_id,
        ip_address="127.0.0.1",
        capacity=5,
        tags=["brain_box", "navigation", "simulated"],
        metadata={"hardware": "sim_neuromorphic"},
    )
    _check("注册类脑服务器", r["code"] == 0, f"server_id={brain_box_server_id}")

    # 注册无人机作为边缘设备
    r = manager.add_device(
        device_id=drone_device_id,
        hardware_type="sim_quadcopter",
        is_simulated=True,
        supported_streams=["video", "telemetry"],
        group_id="aerial",
        metadata={"frame": "X500"},
    )
    _check("注册虚拟无人机", r["code"] == 0, f"device_id={drone_device_id}")

    # ---------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 2: 初始化虚拟设备")
    logger.info("=" * 60)

    # 创建 SimDrone，遥测回调直接调用 manager 的通用接口
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

    # 创建 SimBrainBox，result_callback 直接调用 manager 的通用接口
    sim_brain = SimBrainBox(
        device_id=brain_box_server_id,
        server_id=brain_box_server_id,
        result_callback=lambda task_id, r_type, payload, meta: manager.submit_task_result(
            task_id=task_id, result_type=r_type, payload=payload, metadata=meta,
        ),
        waypoint_callback=lambda wps: (
            sim_drone.upload_mission(wps),
            sim_drone.arm_and_fly(),
        ),
    )
    _check("SimBrainBox 启动", True)

    # 等待至少一条遥测到达
    time.sleep(1.0)

    # 验证遥测已上报
    device_info = manager.get_device_info(drone_device_id)
    _check(
        "初始遥测已到达",
        device_info is not None and device_info.get("latest_telemetry") is not None,
        f"telemetry_type={device_info.get('latest_telemetry', {}).get('telemetry_type', 'N/A')}"
        if device_info else "",
    )

    # ---------------------------------------------------------------
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

    # ---------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 4: SimBrainBox 处理任务（生成轨迹 → 上报 → 下发无人机）")
    logger.info("=" * 60)

    trajectory = sim_brain.on_task_assigned(task_id, task_config)
    _check("轨迹生成", len(trajectory.get("waypoints", [])) > 0,
           f"{len(trajectory.get('waypoints', []))} 航点")
    _check("轨迹距离", trajectory.get("total_distance_m", 0) > 0,
           f"{trajectory.get('total_distance_m')}m")

    # 验证结果已写入 manager
    task_info = manager.get_task_info(task_id)
    _check(
        "轨迹已上报到边缘服务",
        task_info is not None and len(task_info.get("results", [])) > 0,
        f"results count={len(task_info.get('results', []))}" if task_info else "",
    )
    if task_info and task_info.get("results"):
        first_result = task_info["results"][0]
        _check("结果类型为 trajectory", first_result.get("result_type") == "trajectory")
        _check(
            "轨迹包含航点",
            len(first_result.get("payload", {}).get("waypoints", [])) > 0,
        )

    # ---------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 5: SimDrone 模拟飞行")
    logger.info("=" * 60)

    _check("无人机已接收航点", sim_drone.is_flying or not sim_drone.mission_complete)

    # 等待飞行（最多 10 秒）
    for i in range(20):
        if sim_drone.mission_complete:
            break
        time.sleep(0.5)

    _check("飞行任务完成", sim_drone.mission_complete)

    # 查看飞行后位置
    final_state = sim_drone.get_state()
    _check(
        "终点位置接近目标",
        abs(final_state["position"]["lat"] - 30.280) < 0.002
        and abs(final_state["position"]["lng"] - 120.160) < 0.002,
        f"pos=({final_state['position']['lat']:.4f}, {final_state['position']['lng']:.4f})",
    )
    _check("电池消耗", final_state["battery_pct"] < 100.0,
           f"battery={final_state['battery_pct']}%")

    # ---------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 6: 验证遥测持续上报")
    logger.info("=" * 60)

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
    _check(
        "遥测来源标记",
        telemetry.get("metadata", {}).get("source") == "sim_mavlink",
    )

    # ---------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 7: 多类型结果提交测试")
    logger.info("=" * 60)

    # 模拟另一种计算结果（如图像检测）
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

    # 多类型遥测
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

    # ---------------------------------------------------------------
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

    # ---------------------------------------------------------------
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
