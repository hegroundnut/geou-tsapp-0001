# CloudEdgeManager 模拟测试 — curl 命令参考

> 所有命令均不依赖真实设备和服务器，使用 `is_simulated: true` 的虚拟设备。
> `TASK_ID_HERE` 需替换为 `assign_and_start_task` 返回的实际 task_id。

---

## 阶段一：注册基础设施

### 1. add_server — 注册模拟计算服务器

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111101' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"add_server","func_desc":"注册计算服务器节点到云端调度池","params":{"server_id":"svr_sim_01","ip_address":"10.0.0.100","capacity":5,"tags":["gpu","path_planning","simulation"]}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 2. add_device — 注册模拟无人机（is_simulated=true）

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111102' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"add_device","func_desc":"注册边缘设备到管控系统","params":{"device_id":"uav_sim_01","hardware_type":"dji_m300_rtk","is_simulated":true,"supported_streams":["video","lidar_point_cloud"]}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

---

## 阶段二：查看状态

### 3. list_servers — 查看服务器列表

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111103' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"list_servers","func_desc":"获取可用的计算服务器列表及当前负载状态","params":{"filter_by_status":"all"}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 4. list_devices — 查看设备列表

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111104' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"list_devices","func_desc":"获取已注册的边缘设备列表及在线状态","params":{"group_id":"all"}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

---

## 阶段三：心跳与位置

### 5. heartbeat — 服务器心跳

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111105' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"heartbeat","func_desc":"设备或服务器心跳上报","params":{"target_type":"server","target_id":"svr_sim_01"}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 6. heartbeat — 设备心跳（带位置）

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111106' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"heartbeat","func_desc":"设备或服务器心跳上报","params":{"target_type":"device","target_id":"uav_sim_01","location":{"lat":30.270,"lng":120.150,"alt":5.0}}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 7. update_location — 设备位置上报

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111107' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"update_location","func_desc":"设备位置上报，同时刷新心跳","params":{"device_id":"uav_sim_01","location":{"lat":30.271,"lng":120.151,"alt":6.0}}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

---

## 阶段四：核心调度

### 8. assign_and_start_task — 分配任务（导航参数在 custom_payloads 中）

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111108' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"assign_and_start_task","func_desc":"核心调度：指定边缘设备连接特定服务器执行计算任务","params":{"device_id":"uav_sim_01","server_id":"svr_sim_01","task_config":{"algorithm":"a_star_optimized","frequency_hz":10,"enable_video_stream":true,"stream_port":8554,"custom_payloads":{"start_point":{"lat":30.270,"lng":120.150,"alt":10.0},"end_point":{"lat":30.280,"lng":120.160,"alt":10.0},"nav_params":{"obstacle_avoidance":true,"max_speed_m_s":5.0},"map_resolution":0.05}}}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

> ⚠ **从响应中提取 `task_id`**，替换后续命令中的 `TASK_ID_HERE`

---

## 阶段五：通用数据交互

### 9. submit_task_result — 提交轨迹计算结果

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111109' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"submit_task_result","func_desc":"服务器提交任务计算结果","params":{"task_id":"TASK_ID_HERE","result_type":"trajectory","payload":{"waypoints":[{"lat":30.270,"lng":120.150,"alt":10.0,"seq":0,"speed_m_s":3.0},{"lat":30.273,"lng":120.153,"alt":10.0,"seq":1,"speed_m_s":5.0},{"lat":30.276,"lng":120.156,"alt":10.0,"seq":2,"speed_m_s":5.0},{"lat":30.280,"lng":120.160,"alt":10.0,"seq":3,"speed_m_s":3.0}],"total_distance_m":1469.2,"estimated_time_s":294.0,"algorithm_used":"a_star_optimized"},"metadata":{"source":"svr_sim_01","compute_time_ms":125}}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 10. submit_task_result — 提交障碍物检测结果（展示通用性）

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111110' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"submit_task_result","func_desc":"服务器提交任务计算结果","params":{"task_id":"TASK_ID_HERE","result_type":"detection","payload":{"obstacles":[{"id":"obs_001","type":"building","position":{"lat":30.274,"lng":120.154},"radius_m":15},{"id":"obs_002","type":"tree","position":{"lat":30.277,"lng":120.157},"radius_m":3}],"detection_model":"yolov8_custom","confidence_threshold":0.85},"metadata":{"source":"svr_sim_01"}}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 11. update_device_telemetry — 上报无人机飞行状态

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111111' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"update_device_telemetry","func_desc":"设备上报遥测数据","params":{"device_id":"uav_sim_01","telemetry_type":"drone_status","data":{"position":{"lat":30.273,"lng":120.153,"alt":10.5},"velocity":{"vx":2.1,"vy":1.8,"vz":0.0},"attitude":{"roll":0.02,"pitch":-0.01,"yaw":1.57},"battery_pct":82.0,"flight_mode":"AUTO","armed":true,"gps_fix_type":3,"satellites_visible":14},"metadata":{"source":"mavlink","mavlink_msg_id":33}}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 12. update_device_telemetry — 上报传感器数据（展示通用性）

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111112' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"update_device_telemetry","func_desc":"设备上报遥测数据","params":{"device_id":"uav_sim_01","telemetry_type":"sensor","data":{"temperature_c":42.5,"humidity_pct":65.0,"wind_speed_m_s":3.2,"wind_direction_deg":180,"barometric_alt_m":10.3},"metadata":{"source":"onboard_sensors"}}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

---

## 阶段六：查询详情

### 13. get_task_info — 查询任务详情（含 results 列表）

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111113' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"get_task_info","func_desc":"查询指定任务的详细信息","params":{"task_id":"TASK_ID_HERE"}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 14. get_device_info — 查询设备详情（含 latest_telemetry）

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111114' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"get_device_info","func_desc":"获取设备详细信息","params":{"device_id":"uav_sim_01"}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

---

## 阶段七：清理

### 15. stop_task — 停止任务

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111115' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"stop_task","func_desc":"中断指定设备与服务器之间的任务和数据流","params":{"device_id":"uav_sim_01","reason":"simulation_complete"}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 16. remove_device — 注销设备

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111116' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"remove_device","func_desc":"从系统中注销边缘设备","params":{"device_id":"uav_sim_01"}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

### 17. remove_server — 移除服务器

```bash
curl --location --request POST 'http://work.datashell.cn:8500/ai-master-svr/create-task/' \
--data-urlencode 'report_id=11111111-1111-1111-1111-111111111117' \
--data-urlencode 'capability_id=1934867764779429889' \
--data-urlencode 'param=[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"remove_server","func_desc":"从调度池中安全移除指定的服务器","params":{"server_id":"svr_sim_01","force_stop":false}}]}]' \
--data-urlencode 'deal_port="6ecbc930-9685-4904-a895-a8f271eee499"'
```

---

## 测试流程总结

```
注册基础设施                  查看状态                   心跳/位置
┌─────────────┐         ┌──────────────┐          ┌──────────────┐
│ add_server  │───▶     │ list_servers │───▶      │ heartbeat    │
│ add_device  │         │ list_devices │          │ update_loc   │
└─────────────┘         └──────────────┘          └──────┬───────┘
                                                         │
        核心调度                                          ▼
┌───────────────────────┐                    ┌──────────────────┐
│ assign_and_start_task │◀───────────────────│  (获取 task_id)  │
└───────────┬───────────┘                    └──────────────────┘
            │
            ▼
    通用数据交互                    查询详情
┌────────────────────────┐   ┌─────────────────┐
│ submit_task_result     │──▶│ get_task_info    │
│  (trajectory/detection)│   │  (含 results)    │
│ update_device_telemetry│──▶│ get_device_info  │
│  (drone_status/sensor) │   │  (含 telemetry)  │
└────────────────────────┘   └─────────────────┘
            │
            ▼
        清理
┌────────────────┐
│ stop_task      │
│ remove_device  │
│ remove_server  │
└────────────────┘
```
