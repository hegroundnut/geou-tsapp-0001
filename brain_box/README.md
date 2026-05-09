# 类脑盒子（BrainBox）

类脑盒子端程序，作为计算服务器运行，对接边缘控制服务和无人机。

## 架构

```
边缘控制服务 (CloudEdgeManager)
    │
    ├── HTTP/WebSocket ──▶ 下发导航指令
    │
    ◀── HTTP ────────── 接收轨迹回传
    ◀── HTTP ────────── 接收无人机状态转发
    │
类脑盒子 (BrainBox)
    │
    ├── MAVLink ──────▶ 下发导航航点给无人机
    ◀── MAVLink ────── 接收无人机遥测数据
    │
无人机 (Drone / ArduPilot)
```

## 模块结构

```
brain_box/
├── main.py              # 主程序入口和编排逻辑
├── config.py            # 配置管理（支持环境变量）
├── models.py            # 数据模型
├── mavlink_adapter.py   # MAVLink 通信适配层
├── edge_client.py       # 边缘服务 HTTP 客户端
├── navigator.py         # 导航轨迹生成（可插拔算法）
├── requirements.txt     # Python 依赖
└── README.md
```

## 核心流程

1. **接收导航指令** — 边缘控制服务通过 `dispatch_navigation` 下发导航指令（起点/终点/算法/参数）
2. **生成导航轨迹** — `Navigator` 根据算法生成航点序列
3. **上报轨迹** — 通过 `EdgeServiceClient.report_trajectory` 回传给边缘控制服务
4. **下发无人机** — 通过 `MAVLinkAdapter.upload_mission` 将航点下发到飞控
5. **状态转发** — 后台线程持续将无人机遥测数据（位置/速度/姿态/电池等）转发给边缘服务

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 模拟模式运行（无需真实硬件）
python main.py

# 配置环境变量连接真实服务
export EDGE_SERVICE_URL=http://192.168.1.10:8080
export MAVLINK_CONN=udp:192.168.1.20:14550
python main.py
```

## 环境变量配置

| 变量名 | 说明 | 默认值 |
|---|---|---|
| `EDGE_SERVICE_URL` | 边缘控制服务地址 | `http://127.0.0.1:8080` |
| `BRAIN_BOX_DEVICE_ID` | 本机设备ID | `brain_box_01` |
| `BRAIN_BOX_SERVER_ID` | 本机服务器ID | `svr_brain_01` |
| `EDGE_HEARTBEAT_INTERVAL` | 心跳间隔（秒） | `5.0` |
| `MAVLINK_CONN` | MAVLink 连接串 | `udp:127.0.0.1:14550` |
| `MAVLINK_BAUD` | 串口波特率 | `57600` |
| `MAVLINK_STATUS_INTERVAL` | 状态上报间隔（秒） | `1.0` |
| `NAV_ALGORITHM` | 默认导航算法 | `linear_interpolation` |
| `NAV_DEFAULT_SPEED` | 默认飞行速度（m/s） | `3.0` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

## 自定义导航算法

```python
from navigator import Navigator
from models import Waypoint

def my_custom_algorithm(start, end, params, config):
    # 实现自定义轨迹生成逻辑
    return [
        Waypoint(lat=start["lat"], lng=start["lng"], alt=10, seq=0, speed_m_s=3),
        Waypoint(lat=end["lat"], lng=end["lng"], alt=10, seq=1, speed_m_s=3),
    ]

nav = Navigator(config.navigator)
nav.register_algorithm("my_algo", my_custom_algorithm)
```

## 模拟模式

当 `pymavlink` 未安装或手动设置 `simulated=True` 时，系统自动降级为模拟模式：
- MAVLink 适配器生成虚拟遥测数据（位置沿航点移动）
- 边缘服务客户端模拟 HTTP 请求

适合纯代码测试和算法验证，无需连接真实硬件。
