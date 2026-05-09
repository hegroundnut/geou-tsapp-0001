# 虚拟设备模拟测试

## 概述

本目录提供虚拟设备实现，用于在没有真实硬件的情况下端到端测试 CloudEdgeManager 的完整数据流。
**SimBrainBox 直接封装 `brain_box/` 中的完整代码栈**（Navigator + MAVLinkAdapter + EdgeServiceClient），
通过桥接机制让 EdgeServiceClient 的调用直达本地 CloudEdgeManager 实例。

```
┌─────────────────────────────────────────────────────────┐
│                  CloudEdgeManager                        │
│          (边缘控制服务 — 通用接口)                          │
│                                                          │
│  submit_task_result(task_id, result_type, payload)        │
│  update_device_telemetry(device_id, telemetry_type, data)│
└──────────┬───────────────────────────┬───────────────────┘
           │ 桥接                       │ 直接调用
    ┌──────▼──────────────┐    ┌────────▼────────┐
    │    SimBrainBox       │    │    SimDrone      │
    │  (封装 brain_box/)   │    │  (虚拟无人机)    │
    │                      │    │                  │
    │  BrainBox            │    │ 模拟飞行          │
    │   ├─ Navigator       │    │ GPS/速度/姿态     │
    │   ├─ MAVLinkAdapter  │──→ │ 电池/遥测上报     │
    │   └─ EdgeServiceClient│   │                  │
    │      (桥接到Manager) │    └──────────────────┘
    └──────────────────────┘
```

## 文件说明

| 文件 | 说明 |
|---|---|
| `sim_brain_box.py` | 封装 `brain_box/main.py` 中的 BrainBox，桥接 EdgeServiceClient → CloudEdgeManager |
| `sim_drone.py` | 虚拟无人机：模拟飞行 → 通过 `update_device_telemetry` 上报遥测 |
| `device_integration_test.py` | 集成测试：编排 CloudEdgeManager + SimBrainBox + SimDrone 完整流程 |
| `simulation_test.sh` | curl 自动化测试脚本（直接调用边缘服务 API） |
| `curl_commands.md` | 单独可复制的 curl 命令参考 |

## 运行集成测试

```bash
cd tests
python device_integration_test.py
```

测试覆盖 8 个阶段：注册 → 设备初始化 → 任务分配 → BrainBox 处理（轨迹生成+上报+模拟飞行） → 遥测验证 → SimDrone 飞行 → 多类型数据 → 清理。

## 桥接机制说明

SimBrainBox 通过 monkey-patch `EdgeServiceClient._post` 方法，将 HTTP 调用桥接为本地函数调用：

| EdgeServiceClient 调用 | 桥接到 CloudEdgeManager |
|---|---|
| `_post("heartbeat", ...)` | `refresh_server_heartbeat()` / `refresh_device_heartbeat()` |
| `_post("submit_task_result", ...)` | `submit_task_result(task_id, result_type, payload, metadata)` |
| `_post("update_device_telemetry", ...)` | `update_device_telemetry(device_id, telemetry_type, data, metadata)` |

**桥接的数据格式与 HTTP 调用完全一致**，因此切换真机时无需修改任何数据结构。

## 真机替换指南

### 替换类脑盒子 (SimBrainBox → 真机 brain_box/)

SimBrainBox 内部就是 `brain_box/main.py` 的 `BrainBox` 类，替换只需两步：

1. **EdgeServiceClient 切换 HTTP 模式**：
   ```python
   # brain_box/main.py 中
   self._edge_client = EdgeServiceClient(
       config=self._config.edge_service,
       simulated=False,  # ← 改为 False，启用真实 HTTP
   )
   ```
   配置环境变量：
   ```bash
   export EDGE_SERVICE_URL=http://<edge_server_ip>:8080
   export BRAIN_BOX_DEVICE_ID=brain_box_01
   export BRAIN_BOX_SERVER_ID=svr_brain_01
   ```

2. **MAVLinkAdapter 连接真实飞控**：
   ```python
   # brain_box/main.py 中
   self._mavlink = MAVLinkAdapter(
       config=self._config.mavlink,
       on_state_update=self._on_drone_state_update,
       simulated=False,  # ← 改为 False，连接真实 MAVLink
   )
   ```
   配置环境变量：
   ```bash
   export MAVLINK_CONN=udp:127.0.0.1:14550   # 或 /dev/ttyACM0
   ```

### 替换无人机 (SimDrone → 真机 MAVLink)

SimDrone 的遥测数据格式与 `brain_box/mavlink_adapter.py` 的 `_read_real_telemetry()` 输出一致：

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

只要真机输出遵循以上格式，即可无缝替换。
