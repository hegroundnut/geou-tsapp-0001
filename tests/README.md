# 虚拟设备模拟测试

## 概述

本目录提供虚拟设备实现，用于在没有真实硬件的情况下端到端测试 CloudEdgeManager 的完整数据流。

```
┌─────────────────────────────────────────────────────────┐
│                  CloudEdgeManager                        │
│          (边缘控制服务 — 通用接口)                          │
│                                                          │
│  submit_task_result(task_id, result_type, payload)        │
│  update_device_telemetry(device_id, telemetry_type, data)│
└──────────┬────────────────────────────┬──────────────────┘
           │                            │
    ┌──────▼──────┐            ┌────────▼────────┐
    │ SimBrainBox │            │    SimDrone      │
    │ (虚拟类脑)   │──航点──→   │  (虚拟无人机)    │
    │             │            │                  │
    │ 接收任务     │            │ 模拟飞行          │
    │ 生成轨迹     │            │ GPS/速度/姿态     │
    │ 上报结果     │            │ 电池/遥测上报     │
    └─────────────┘            └──────────────────┘
```

## 文件说明

| 文件 | 说明 |
|---|---|
| `sim_brain_box.py` | 虚拟类脑盒子：接收任务配置 → 生成轨迹 → 通过 `submit_task_result` 上报 |
| `sim_drone.py` | 虚拟无人机：模拟飞行 → 通过 `update_device_telemetry` 上报遥测 |
| `device_integration_test.py` | 集成测试：编排 CloudEdgeManager + SimBrainBox + SimDrone 完整流程 |
| `simulation_test.sh` | curl 自动化测试脚本（直接调用边缘服务 API） |
| `curl_commands.md` | 单独可复制的 curl 命令参考 |

## 运行集成测试

```bash
cd tests
python device_integration_test.py
```

测试覆盖 8 个阶段、20+ 个检查点：注册 → 遥测 → 任务分配 → 轨迹生成 → 飞行模拟 → 多类型数据 → 清理。

## 真机替换指南

### 设计原则

虚拟设备与真实设备使用 **完全相同的数据格式**，通过 CloudEdgeManager 的 2 个通用接口通信：

- `submit_task_result(task_id, result_type, payload, metadata)` — 提交计算结果
- `update_device_telemetry(device_id, telemetry_type, data, metadata)` — 上报遥测数据

替换时 **无需修改边缘控制服务的任何代码**，只需切换设备端的通信方式。

### 替换类脑盒子 (SimBrainBox → 真机 brain_box/)

| 虚拟 | 真机 | 说明 |
|---|---|---|
| `SimBrainBox.on_task_assigned()` | `brain_box/main.py → BrainBox.handle_navigation()` | 任务处理入口 |
| `result_callback()` 直接调用 manager | `brain_box/edge_client.py → EdgeServiceClient.submit_task_result()` | HTTP POST |
| `waypoint_callback()` 直接传列表 | `brain_box/mavlink_adapter.py → MAVLinkAdapter.upload_mission()` | MAVLink 协议 |
| 内置 `_linear_interpolation` | `brain_box/navigator.py → Navigator.plan()` | 可插拔算法 |

**步骤：**
1. 在类脑盒子上部署 `brain_box/` 目录
2. 配置环境变量：
   ```bash
   export EDGE_SERVICE_URL=http://<edge_server_ip>:8080
   export BRAIN_BOX_DEVICE_ID=brain_box_01
   export BRAIN_BOX_SERVER_ID=svr_brain_01
   ```
3. 启动：`python brain_box/main.py`
4. 在边缘服务注册：`add_server(server_id="svr_brain_01", ...)`

### 替换无人机 (SimDrone → 真机 MAVLink)

| 虚拟 | 真机 | 说明 |
|---|---|---|
| `SimDrone._flight_loop()` | 真实飞控 (ArduPilot/PX4) | 自主飞行 |
| `SimDrone._telemetry_loop()` | `brain_box/mavlink_adapter.py → _read_real_telemetry()` | MAVLink 消息解析 |
| `telemetry_callback()` 直接调用 manager | `brain_box/edge_client.py → forward_drone_status()` | HTTP POST |
| `SimDrone.upload_mission()` | `MAVLinkAdapter.upload_mission()` | MAVLink mission_item_int |

**步骤：**
1. 类脑盒子上配置 MAVLink 连接：
   ```bash
   export MAVLINK_CONN=udp:127.0.0.1:14550   # 或 /dev/ttyACM0
   ```
2. `brain_box/main.py` 将 `simulated=False` 传入 `MAVLinkAdapter`
3. 遥测数据格式不变，边缘服务自动接收

### 数据格式对齐

轨迹结果（`result_type="trajectory"`）：
```json
{
    "waypoints": [
        {"lat": 30.270, "lng": 120.150, "alt": 10.0, "seq": 0, "speed_m_s": 5.0},
        {"lat": 30.275, "lng": 120.155, "alt": 10.0, "seq": 1, "speed_m_s": 5.0}
    ],
    "total_distance_m": 640.25,
    "estimated_time_s": 128.05,
    "algorithm_used": "linear_interpolation"
}
```

无人机遥测（`telemetry_type="drone_status"`）：
```json
{
    "position": {"lat": 30.271, "lng": 120.151, "alt": 10.2},
    "velocity": {"vx": 1.2, "vy": 0.5, "vz": 0.0},
    "attitude": {"roll": 0.01, "pitch": -0.02, "yaw": 1.57},
    "battery_pct": 85.0,
    "flight_mode": "AUTO",
    "armed": true,
    "gps_fix_type": 3,
    "satellites_visible": 12
}
```

只要真机输出的数据遵循以上格式，即可无缝替换。
