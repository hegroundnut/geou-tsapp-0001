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
├── models.py              # 数据模型（ServerNode, EdgeDevice, TaskRecord, StreamChannel, TaskResult, DeviceTelemetry）
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
| add_device           | 注册边缘设备到管控系统                           |
| remove_device        | 从系统中注销边缘设备                             |
| list_devices         | 获取已注册的边缘设备列表及在线状态               |
| assign_and_start_task| 指定设备连接服务器执行计算任务                   |
| stop_task            | 中断指定设备与服务器之间的任务和数据流           |

### 扩展接口
| subfunc              | 说明                                             |
|----------------------|--------------------------------------------------|
| heartbeat            | 设备/服务器心跳上报                              |
| get_device_info      | 获取设备详细信息（含流通道、遥测和当前任务）     |
| get_task_info        | 查询任务详情（含计算结果列表）                   |
| update_location      | 设备位置上报                                     |

### 通用数据交互接口
| subfunc                  | 说明                                                                 |
|--------------------------|----------------------------------------------------------------------|
| submit_task_result       | 服务器提交任务计算结果（通用，result_type 标识类型，payload 为数据） |
| update_device_telemetry  | 设备/服务器上报遥测数据（通用，telemetry_type 标识类型，data 为数据）|

### 设计特性
1. **心跳机制 (Heartbeat)**: 守护线程定期检测设备/服务器活跃状态，超时自动标记离线并释放资源
2. **数据流隔离**: 信令通道(WebSocket)与媒体通道(WebRTC/UDP)在端口和协议层面逻辑隔离
3. **模拟设备模式**: `is_simulated=true` 注册虚拟设备用于纯代码测试，跳过心跳检测
4. **任务抢占与恢复**: 重复分配时自动抢占旧任务，平滑释放服务器资源
5. **灵活扩展**: `custom_payloads` 字段支持任意自定义配置透传
6. **低耦合设计**: 通用数据交互接口（submit_task_result / update_device_telemetry）与具体设备类型无关，通过 result_type / telemetry_type 标识数据类型，payload / data 由调用方自定义格式，可随时更换设备实现

### params JSON 示例

详见 `jivf.py` 文件头部注释。
