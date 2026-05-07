## CloudEdgeManager — 云边协同管控工具 v0.0.0

### 加载配置
```json
{
    "dtype": "uvaTrack",
    "dir_name": "uvaTrack",
    "version": "0.0.0",
    "file_name": "jivf",
    "class_name": "CTest"
}
```

### 模块结构
```
v0_0_0/
├── jivf.py               # 工具入口类 CTest，平台通过 subfunc 分发调用
├── cloud_edge_manager.py  # 核心调度器（单例），维护服务器表、设备表、任务表
├── models.py              # 数据模型（ServerNode, EdgeDevice, TaskRecord, StreamChannel）
├── heartbeat.py           # 心跳监控守护线程，自动标记超时离线
├── stream_registry.py     # 流通道注册表，信令/媒体隔离
└── README.md
```

### 核心功能
| subfunc              | 说明                                             |
|----------------------|--------------------------------------------------|
| add_server           | 注册计算服务器节点到云端调度池                   |
| remove_server        | 从调度池中安全移除指定服务器                     |
| list_servers         | 获取可用的计算服务器列表及当前负载状态           |
| add_device           | 注册边缘设备（如机器狗、无人车）到管控系统       |
| remove_device        | 从系统中注销边缘设备                             |
| list_devices         | 获取已注册的边缘设备列表及在线状态               |
| assign_and_start_task| 指定设备连接服务器，下发路径规划及计算任务       |
| stop_task            | 中断指定设备与服务器之间的任务和数据流           |

### 扩展接口
| subfunc              | 说明                                             |
|----------------------|--------------------------------------------------|
| heartbeat            | 设备/服务器心跳上报                              |
| get_device_info      | 获取设备详细信息（含流通道和当前任务）           |
| get_task_info        | 查询任务详情                                     |
| update_location      | 设备位置上报                                     |

### 导航调度接口（边缘服务 ↔ 类脑盒子）
| subfunc              | 说明                                             |
|----------------------|--------------------------------------------------|
| dispatch_navigation  | 向类脑盒子下发导航指令（起点/终点/算法/参数）    |
| receive_trajectory   | 接收类脑盒子上报的导航轨迹                       |
| receive_drone_status | 接收类脑盒子转发的无人机位置/状态                |
| get_navigation_status| 查询导航指令状态及关联轨迹                       |
| get_drone_status     | 查询设备最新的无人机飞行状态                     |

### 设计特性
1. **心跳机制 (Heartbeat)**: 守护线程定期检测设备/服务器活跃状态，超时自动标记离线并释放资源
2. **数据流隔离**: 信令通道(WebSocket)与媒体通道(WebRTC/UDP)在端口和协议层面逻辑隔离
3. **模拟设备模式**: `is_simulated=true` 注册虚拟设备用于纯代码测试，跳过心跳检测
4. **任务抢占与恢复**: 重复分配时自动抢占旧任务，平滑释放服务器资源
5. **灵活扩展**: `custom_payloads` 字段支持任意自定义配置透传

### params JSON 示例

详见 `jivf.py` 文件头部注释。
