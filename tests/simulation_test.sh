#!/bin/bash
# =============================================================================
#  CloudEdgeManager 模拟测试流程
#  脱离真实计算服务器和无人设备，通过 HTTP API 调用全部 14 个 subfunc
#
#  使用方式:
#    chmod +x tests/simulation_test.sh
#    ./tests/simulation_test.sh
#
#  可选环境变量:
#    API_BASE   API地址（默认 http://work.datashell.cn:8500/ai-master-svr/create-task/）
#    DEAL_PORT  端口标识（默认 6ecbc930-9685-4904-a895-a8f271eee499）
# =============================================================================

set -euo pipefail

API_BASE="${API_BASE:-http://work.datashell.cn:8500/ai-master-svr/create-task/}"
CAPABILITY_ID="1934867764779429889"
DEAL_PORT="${DEAL_PORT:-6ecbc930-9685-4904-a895-a8f271eee499}"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step=0

call_api() {
    local desc="$1"
    local param_json="$2"
    step=$((step + 1))
    local report_id
    report_id=$(python3 -c "import uuid; print(uuid.uuid4())")

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}步骤 ${step}: ${desc}${NC}"
    echo -e "${CYAN}report_id: ${report_id}${NC}"
    echo -e "${CYAN}param:${NC}"
    echo "$param_json" | python3 -m json.tool 2>/dev/null || echo "$param_json"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    local response
    response=$(curl -s --location --request POST "$API_BASE" \
        --data-urlencode "report_id=${report_id}" \
        --data-urlencode "capability_id=${CAPABILITY_ID}" \
        --data-urlencode "param=${param_json}" \
        --data-urlencode "deal_port=${DEAL_PORT}" \
        2>&1) || true

    echo -e "${GREEN}响应:${NC}"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    echo ""
}

echo "========================================================================"
echo "  CloudEdgeManager 模拟测试流程"
echo "  API: ${API_BASE}"
echo "  capability_id: ${CAPABILITY_ID}"
echo "========================================================================"

# ──────────────────────────────────────────────────────────────────────────────
#  阶段一：注册基础设施
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段一: 注册基础设施（服务器 + 设备）${NC}"

# 1. 添加模拟计算服务器
call_api "add_server — 注册模拟计算服务器 svr_sim_01" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"add_server","func_desc":"注册计算服务器节点到云端调度池","params":{"server_id":"svr_sim_01","ip_address":"10.0.0.100","capacity":5,"tags":["gpu","path_planning","simulation"]}}]}]'

# 2. 添加第二台模拟服务器
call_api "add_server — 注册第二台模拟服务器 svr_sim_02" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"add_server","func_desc":"注册计算服务器节点到云端调度池","params":{"server_id":"svr_sim_02","ip_address":"10.0.0.101","capacity":3,"tags":["cpu","analysis"]}}]}]'

# 3. 添加模拟边缘设备（无人机）
call_api "add_device — 注册模拟无人机 uav_sim_01" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"add_device","func_desc":"注册边缘设备到管控系统","params":{"device_id":"uav_sim_01","hardware_type":"dji_m300_rtk","is_simulated":true,"supported_streams":["video","lidar_point_cloud"]}}]}]'

# 4. 添加模拟边缘设备（机器狗）
call_api "add_device — 注册模拟机器狗 dog_sim_01" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"add_device","func_desc":"注册边缘设备到管控系统","params":{"device_id":"dog_sim_01","hardware_type":"unitree_b2","is_simulated":true,"supported_streams":["video"]}}]}]'

# ──────────────────────────────────────────────────────────────────────────────
#  阶段二：查看当前状态
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段二: 查看当前状态${NC}"

# 5. 查看服务器列表
call_api "list_servers — 查看所有服务器" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"list_servers","func_desc":"获取可用的计算服务器列表及当前负载状态","params":{"filter_by_status":"all"}}]}]'

# 6. 查看设备列表
call_api "list_devices — 查看所有设备" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"list_devices","func_desc":"获取已注册的边缘设备列表及在线状态","params":{"group_id":"all"}}]}]'

# ──────────────────────────────────────────────────────────────────────────────
#  阶段三：心跳与位置上报
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段三: 心跳与位置上报${NC}"

# 7. 服务器心跳
call_api "heartbeat — 服务器 svr_sim_01 心跳" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"heartbeat","func_desc":"设备或服务器心跳上报","params":{"target_type":"server","target_id":"svr_sim_01"}}]}]'

# 8. 设备心跳（带位置）
call_api "heartbeat — 设备 uav_sim_01 心跳（带位置）" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"heartbeat","func_desc":"设备或服务器心跳上报","params":{"target_type":"device","target_id":"uav_sim_01","location":{"lat":30.270,"lng":120.150,"alt":5.0}}}]}]'

# 9. 设备位置上报
call_api "update_location — 设备 uav_sim_01 位置上报" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"update_location","func_desc":"设备位置上报，同时刷新心跳","params":{"device_id":"uav_sim_01","location":{"lat":30.271,"lng":120.151,"alt":6.0}}}]}]'

# ──────────────────────────────────────────────────────────────────────────────
#  阶段四：核心调度 — 任务分配与执行
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段四: 核心调度 — 任务分配与执行${NC}"

# 10. 分配任务：无人机 → 服务器（导航参数通过 custom_payloads 传递）
call_api "assign_and_start_task — 无人机 uav_sim_01 → 服务器 svr_sim_01 执行导航计算" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"assign_and_start_task","func_desc":"核心调度：指定边缘设备连接特定服务器执行计算任务","params":{"device_id":"uav_sim_01","server_id":"svr_sim_01","task_config":{"algorithm":"a_star_optimized","frequency_hz":10,"enable_video_stream":true,"stream_port":8554,"custom_payloads":{"start_point":{"lat":30.270,"lng":120.150,"alt":10.0},"end_point":{"lat":30.280,"lng":120.160,"alt":10.0},"nav_params":{"obstacle_avoidance":true,"max_speed_m_s":5.0},"map_resolution":0.05}}}}]}]'

echo ""
echo -e "${YELLOW}⚠ 注意: assign_and_start_task 返回的 task_id 需要在后续步骤中使用${NC}"
echo -e "${YELLOW}  请从上面的响应中提取 task_id 并替换下面命令中的 TASK_ID_HERE${NC}"
echo ""

# ──────────────────────────────────────────────────────────────────────────────
#  阶段五：通用数据交互 — 服务器提交结果 + 设备上报遥测
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段五: 通用数据交互${NC}"

# 11. 服务器提交轨迹计算结果（需替换 task_id）
call_api "submit_task_result — 服务器提交轨迹计算结果 (result_type=trajectory)" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"submit_task_result","func_desc":"服务器提交任务计算结果","params":{"task_id":"TASK_ID_HERE","result_type":"trajectory","payload":{"waypoints":[{"lat":30.270,"lng":120.150,"alt":10.0,"seq":0,"speed_m_s":3.0},{"lat":30.273,"lng":120.153,"alt":10.0,"seq":1,"speed_m_s":5.0},{"lat":30.276,"lng":120.156,"alt":10.0,"seq":2,"speed_m_s":5.0},{"lat":30.280,"lng":120.160,"alt":10.0,"seq":3,"speed_m_s":3.0}],"total_distance_m":1469.2,"estimated_time_s":294.0,"algorithm_used":"a_star_optimized"},"metadata":{"source":"svr_sim_01","compute_time_ms":125}}}]}]'

# 12. 服务器提交检测结果（第二种 result_type，展示通用性）
call_api "submit_task_result — 服务器提交障碍物检测结果 (result_type=detection)" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"submit_task_result","func_desc":"服务器提交任务计算结果","params":{"task_id":"TASK_ID_HERE","result_type":"detection","payload":{"obstacles":[{"id":"obs_001","type":"building","position":{"lat":30.274,"lng":120.154,"alt":0},"radius_m":15},{"id":"obs_002","type":"tree","position":{"lat":30.277,"lng":120.157,"alt":0},"radius_m":3}],"detection_model":"yolov8_custom","confidence_threshold":0.85},"metadata":{"source":"svr_sim_01"}}}]}]'

# 13. 设备上报无人机遥测（drone_status）
call_api "update_device_telemetry — 无人机 uav_sim_01 上报飞行状态 (telemetry_type=drone_status)" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"update_device_telemetry","func_desc":"设备上报遥测数据","params":{"device_id":"uav_sim_01","telemetry_type":"drone_status","data":{"position":{"lat":30.273,"lng":120.153,"alt":10.5},"velocity":{"vx":2.1,"vy":1.8,"vz":0.0},"attitude":{"roll":0.02,"pitch":-0.01,"yaw":1.57},"battery_pct":82.0,"flight_mode":"AUTO","armed":true,"gps_fix_type":3,"satellites_visible":14},"metadata":{"source":"mavlink","mavlink_msg_id":33}}}]}]'

# 14. 设备上报传感器遥测（第二种 telemetry_type，展示通用性）
call_api "update_device_telemetry — 无人机 uav_sim_01 上报传感器数据 (telemetry_type=sensor)" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"update_device_telemetry","func_desc":"设备上报遥测数据","params":{"device_id":"uav_sim_01","telemetry_type":"sensor","data":{"temperature_c":42.5,"humidity_pct":65.0,"wind_speed_m_s":3.2,"wind_direction_deg":180,"barometric_alt_m":10.3},"metadata":{"source":"onboard_sensors"}}}]}]'

# ──────────────────────────────────────────────────────────────────────────────
#  阶段六：查询详情
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段六: 查询详情${NC}"

# 15. 查询任务详情（含计算结果列表）
call_api "get_task_info — 查询任务详情（含 results 列表）" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"get_task_info","func_desc":"查询指定任务的详细信息","params":{"task_id":"TASK_ID_HERE"}}]}]'

# 16. 查询设备详情（含最新遥测）
call_api "get_device_info — 查询设备详情（含 latest_telemetry）" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"get_device_info","func_desc":"获取设备详细信息","params":{"device_id":"uav_sim_01"}}]}]'

# ──────────────────────────────────────────────────────────────────────────────
#  阶段七：任务抢占测试
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段七: 任务抢占测试（重新分配设备到另一台服务器）${NC}"

# 17. 重新分配（触发任务抢占）
call_api "assign_and_start_task — 任务抢占：uav_sim_01 从 svr_sim_01 → svr_sim_02" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"assign_and_start_task","func_desc":"核心调度：指定边缘设备连接特定服务器执行计算任务","params":{"device_id":"uav_sim_01","server_id":"svr_sim_02","task_config":{"algorithm":"rrt_star","frequency_hz":5,"enable_video_stream":false,"custom_payloads":{"start_point":{"lat":30.280,"lng":120.160,"alt":10.0},"end_point":{"lat":30.290,"lng":120.170,"alt":15.0}}}}}]}]'

# ──────────────────────────────────────────────────────────────────────────────
#  阶段八：清理 — 停止任务、注销设备和服务器
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}▶ 阶段八: 清理${NC}"

# 18. 停止任务
call_api "stop_task — 停止 uav_sim_01 的任务" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"stop_task","func_desc":"中断指定设备与服务器之间的任务和数据流","params":{"device_id":"uav_sim_01","reason":"simulation_complete"}}]}]'

# 19. 注销设备
call_api "remove_device — 注销 uav_sim_01" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"remove_device","func_desc":"从系统中注销边缘设备","params":{"device_id":"uav_sim_01"}}]}]'

call_api "remove_device — 注销 dog_sim_01" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"remove_device","func_desc":"从系统中注销边缘设备","params":{"device_id":"dog_sim_01"}}]}]'

# 20. 移除服务器
call_api "remove_server — 移除 svr_sim_01" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"remove_server","func_desc":"从调度池中安全移除指定的服务器","params":{"server_id":"svr_sim_01","force_stop":false}}]}]'

call_api "remove_server — 移除 svr_sim_02" \
'[{"dtype":"uvaTrack","version":"0.0.0","subfuncs":[{"func_name":"remove_server","func_desc":"从调度池中安全移除指定的服务器","params":{"server_id":"svr_sim_02","force_stop":false}}]}]'

# ──────────────────────────────────────────────────────────────────────────────
#  完成
# ──────────────────────────────────────────────────────────────────────────────

echo ""
echo "========================================================================"
echo "  模拟测试完成！共执行 ${step} 步"
echo ""
echo "  覆盖的 subfunc:"
echo "    ✓ add_server / remove_server / list_servers"
echo "    ✓ add_device / remove_device / list_devices"
echo "    ✓ assign_and_start_task / stop_task"
echo "    ✓ heartbeat / update_location"
echo "    ✓ submit_task_result (trajectory + detection)"
echo "    ✓ update_device_telemetry (drone_status + sensor)"
echo "    ✓ get_task_info / get_device_info"
echo "    ✓ 任务抢占测试"
echo "========================================================================"
