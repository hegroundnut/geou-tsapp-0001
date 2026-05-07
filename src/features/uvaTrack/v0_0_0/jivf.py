"""
CloudEdgeManager 工具入口 — CTest 类
平台通过 ProcessTask 调用 subfuncs 中定义的方法，每个方法接收 params 字典。

支持的子功能:
  add_server          注册计算服务器节点到云端调度池
  remove_server       从调度池中安全移除指定服务器
  list_servers        获取可用的计算服务器列表及当前负载状态
  add_device          注册边缘设备（如机器狗、无人车）到管控系统
  remove_device       从系统中注销边缘设备
  list_devices        获取已注册的边缘设备列表及在线状态
  assign_and_start_task  核心调度：指定边缘设备连接特定服务器，下发路径规划及计算任务
  stop_task           中断指定设备与服务器之间的任务和数据流

扩展接口:
  heartbeat           设备/服务器心跳上报
  get_device_info     获取设备详细信息（含流通道）
  get_task_info       查询任务详情
  update_location     设备位置上报

导航调度接口（边缘服务 ↔ 类脑盒子）:
  dispatch_navigation    向类脑盒子下发导航指令
  receive_trajectory     接收类脑盒子上报的导航轨迹
  receive_drone_status   接收类脑盒子转发的无人机位置/状态
  get_navigation_status  查询导航指令状态及关联轨迹
  get_drone_status       查询设备最新的无人机状态

--- params JSON 格式示例 ---

add_server:
{
    "server_id": "svr_node_01",
    "ip_address": "192.168.1.100",
    "capacity": 5,
    "tags": ["gpu", "path_planning"]
}

remove_server:
{
    "server_id": "svr_node_01",
    "force_stop": true
}

list_servers:
{
    "filter_by_status": "active"
}

add_device:
{
    "device_id": "robot_dog_nx_01",
    "hardware_type": "jetson_xavier_nx",
    "is_simulated": false,
    "supported_streams": ["video", "lidar_point_cloud"]
}

remove_device:
{
    "device_id": "robot_dog_nx_01"
}

list_devices:
{
    "group_id": "all"
}

assign_and_start_task:
{
    "device_id": "robot_dog_nx_01",
    "server_id": "svr_node_01",
    "task_config": {
        "algorithm": "a_star_optimized",
        "frequency_hz": 10,
        "enable_video_stream": true,
        "stream_port": 8554,
        "custom_payloads": {
            "map_resolution": 0.05,
            "enable_local_slm": true
        }
    }
}

stop_task:
{
    "device_id": "robot_dog_nx_01",
    "reason": "user_manual_stop"
}

heartbeat:
{
    "target_type": "device",
    "target_id": "robot_dog_nx_01",
    "location": {"lat": 30.27, "lng": 120.15, "alt": 5.0}
}

get_device_info:
{
    "device_id": "robot_dog_nx_01"
}

get_task_info:
{
    "task_id": "task_a1b2c3d4e5f6"
}

update_location:
{
    "device_id": "robot_dog_nx_01",
    "location": {"lat": 30.27, "lng": 120.15, "alt": 5.0}
}

dispatch_navigation:
{
    "device_id": "robot_dog_nx_01",
    "server_id": "svr_node_01",
    "start_point": {"lat": 30.27, "lng": 120.15, "alt": 10.0},
    "end_point": {"lat": 30.28, "lng": 120.16, "alt": 10.0},
    "algorithm": "a_star_optimized",
    "nav_params": {"obstacle_avoidance": true, "max_speed_m_s": 5.0}
}

receive_trajectory:
{
    "instruction_id": "nav_a1b2c3d4e5f6",
    "device_id": "robot_dog_nx_01",
    "server_id": "svr_node_01",
    "waypoints": [
        {"lat": 30.270, "lng": 120.150, "alt": 10.0, "seq": 0, "speed_m_s": 3.0},
        {"lat": 30.275, "lng": 120.155, "alt": 10.0, "seq": 1, "speed_m_s": 5.0},
        {"lat": 30.280, "lng": 120.160, "alt": 10.0, "seq": 2, "speed_m_s": 3.0}
    ],
    "total_distance_m": 1200.5,
    "estimated_time_s": 240.0,
    "algorithm_used": "a_star_optimized"
}

receive_drone_status:
{
    "device_id": "robot_dog_nx_01",
    "position": {"lat": 30.271, "lng": 120.151, "alt": 10.2},
    "velocity": {"vx": 1.2, "vy": 0.5, "vz": 0.0},
    "attitude": {"roll": 0.01, "pitch": -0.02, "yaw": 1.57},
    "battery_pct": 85.0,
    "flight_mode": "GUIDED",
    "armed": true,
    "gps_fix_type": 3,
    "satellites_visible": 12
}

get_navigation_status:
{
    "instruction_id": "nav_a1b2c3d4e5f6"
}

get_drone_status:
{
    "device_id": "robot_dog_nx_01"
}
"""
import os
import sys
import json
import logging

_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from cloud_edge_manager import CloudEdgeManager

logger = logging.getLogger("uvaTrack")


class CTest:
    """
    云边协同管控工具入口类。

    由平台框架通过 _load_train_version 自动实例化，
    每个公开方法对应 toolconfig.yml 中的一个 subfunc。
    """

    def __init__(self, node_cfg, process_comm, proc_modules_obj, progress_callback):
        self.node_cfg = node_cfg
        self.process_comm = process_comm
        self.proc_modules_obj = proc_modules_obj
        self.progress_callback = progress_callback

        heartbeat_cfg = node_cfg.get("heartbeat_config", {})
        self._manager = CloudEdgeManager(
            heartbeat_interval=heartbeat_cfg.get("check_interval_s", 5.0),
            device_timeout=heartbeat_cfg.get("device_timeout_s", 15.0),
            server_timeout=heartbeat_cfg.get("server_timeout_s", 30.0),
            on_task_stopped=self._on_task_stopped_callback,
        )

    # ------------------------------------------------------------------
    #  回调
    # ------------------------------------------------------------------

    def _on_task_stopped_callback(self, task):
        logger.info(
            "Task stopped callback: task_id=%s reason=%s",
            task.task_id,
            task.stop_reason,
        )

    # ------------------------------------------------------------------
    #  辅助：统一结果处理
    # ------------------------------------------------------------------

    def _handle_result(self, func_name, result):
        if result.get("code", -1) == 0:
            self.progress_callback(
                100,
                json.dumps(result, ensure_ascii=False, default=str),
                "ok",
            )
        else:
            self.progress_callback(
                -1,
                json.dumps(result, ensure_ascii=False, default=str),
                "failed",
            )
        return result

    # ==================================================================
    #  服务器管理
    # ==================================================================

    def add_server(self, params):
        """注册计算服务器节点到云端调度池"""
        self.progress_callback(10, f"正在注册服务器: {params.get('server_id')}")
        result = self._manager.add_server(
            server_id=params["server_id"],
            ip_address=params["ip_address"],
            capacity=params.get("capacity", 10),
            tags=params.get("tags", []),
            metadata=params.get("metadata", {}),
        )
        return self._handle_result("add_server", result)

    def remove_server(self, params):
        """从调度池中安全移除指定的服务器"""
        self.progress_callback(10, f"正在移除服务器: {params.get('server_id')}")
        result = self._manager.remove_server(
            server_id=params["server_id"],
            force_stop=bool(params.get("force_stop", False)),
        )
        return self._handle_result("remove_server", result)

    def list_servers(self, params):
        """获取可用的计算服务器列表及当前负载状态"""
        self.progress_callback(10, "正在查询服务器列表")
        result = self._manager.list_servers(
            filter_by_status=params.get("filter_by_status", "all"),
        )
        return self._handle_result("list_servers", result)

    # ==================================================================
    #  设备管理
    # ==================================================================

    def add_device(self, params):
        """注册边缘设备（如机器狗、无人车）到管控系统"""
        self.progress_callback(10, f"正在注册设备: {params.get('device_id')}")
        result = self._manager.add_device(
            device_id=params["device_id"],
            hardware_type=params["hardware_type"],
            is_simulated=bool(params.get("is_simulated", False)),
            supported_streams=params.get("supported_streams", []),
            group_id=params.get("group_id", "default"),
            metadata=params.get("metadata", {}),
        )
        return self._handle_result("add_device", result)

    def remove_device(self, params):
        """从系统中注销边缘设备"""
        self.progress_callback(10, f"正在注销设备: {params.get('device_id')}")
        result = self._manager.remove_device(
            device_id=params["device_id"],
        )
        return self._handle_result("remove_device", result)

    def list_devices(self, params):
        """获取已注册的边缘设备列表及在线状态"""
        self.progress_callback(10, "正在查询设备列表")
        result = self._manager.list_devices(
            group_id=params.get("group_id", "all"),
        )
        return self._handle_result("list_devices", result)

    # ==================================================================
    #  核心调度
    # ==================================================================

    def assign_and_start_task(self, params):
        """核心调度：指定边缘设备连接特定服务器，下发路径规划及计算任务"""
        device_id = params["device_id"]
        server_id = params["server_id"]
        self.progress_callback(
            10,
            f"正在调度: 设备 {device_id} -> 服务器 {server_id}",
        )
        result = self._manager.assign_and_start_task(
            device_id=device_id,
            server_id=server_id,
            task_config=params.get("task_config", {}),
        )
        return self._handle_result("assign_and_start_task", result)

    def stop_task(self, params):
        """中断指定设备与服务器之间的任务和数据流"""
        device_id = params["device_id"]
        self.progress_callback(10, f"正在停止设备 {device_id} 的任务")
        result = self._manager.stop_task(
            device_id=device_id,
            reason=params.get("reason", "user_manual_stop"),
        )
        return self._handle_result("stop_task", result)

    # ==================================================================
    #  扩展接口
    # ==================================================================

    def heartbeat(self, params):
        """设备/服务器心跳上报"""
        target_type = params.get("target_type", "device")
        target_id = params.get("target_id", "")
        location = params.get("location")

        self.progress_callback(10, f"心跳上报: {target_type}/{target_id}")

        if target_type == "device":
            ok = self._manager.refresh_device_heartbeat(target_id, location=location)
        elif target_type == "server":
            ok = self._manager.refresh_server_heartbeat(target_id)
        else:
            result = {"code": -1, "msg": f"未知目标类型: {target_type}", "data": {}}
            return self._handle_result("heartbeat", result)

        result = {
            "code": 0 if ok else -1,
            "msg": "success" if ok else f"{target_type} {target_id} 不存在",
            "data": {"target_type": target_type, "target_id": target_id},
        }
        return self._handle_result("heartbeat", result)

    def get_device_info(self, params):
        """获取设备详细信息（含流通道和当前任务）"""
        device_id = params["device_id"]
        self.progress_callback(10, f"查询设备详情: {device_id}")
        info = self._manager.get_device_info(device_id)
        if info is None:
            result = {"code": -1, "msg": f"设备 {device_id} 不存在", "data": {}}
        else:
            result = {"code": 0, "msg": "success", "data": info}
        return self._handle_result("get_device_info", result)

    def get_task_info(self, params):
        """查询任务详情"""
        task_id = params["task_id"]
        self.progress_callback(10, f"查询任务详情: {task_id}")
        info = self._manager.get_task_info(task_id)
        if info is None:
            result = {"code": -1, "msg": f"任务 {task_id} 不存在", "data": {}}
        else:
            result = {"code": 0, "msg": "success", "data": info}
        return self._handle_result("get_task_info", result)

    def update_location(self, params):
        """设备位置上报"""
        device_id = params["device_id"]
        location = params.get("location", {})
        self.progress_callback(10, f"位置上报: {device_id}")
        ok = self._manager.refresh_device_heartbeat(device_id, location=location)
        result = {
            "code": 0 if ok else -1,
            "msg": "success" if ok else f"设备 {device_id} 不存在",
            "data": {"device_id": device_id, "location": location},
        }
        return self._handle_result("update_location", result)

    # ==================================================================
    #  导航调度接口（边缘服务 ↔ 类脑盒子）
    # ==================================================================

    def dispatch_navigation(self, params):
        """向类脑盒子下发导航指令"""
        device_id = params["device_id"]
        server_id = params["server_id"]
        self.progress_callback(
            10, f"下发导航指令: 设备 {device_id} -> 服务器 {server_id}"
        )
        result = self._manager.dispatch_navigation(
            device_id=device_id,
            server_id=server_id,
            start_point=params["start_point"],
            end_point=params["end_point"],
            algorithm=params.get("algorithm", "default"),
            nav_params=params.get("nav_params", {}),
        )
        return self._handle_result("dispatch_navigation", result)

    def receive_trajectory(self, params):
        """接收类脑盒子上报的导航轨迹"""
        instruction_id = params["instruction_id"]
        self.progress_callback(10, f"接收轨迹: instruction={instruction_id}")
        result = self._manager.receive_trajectory(
            instruction_id=instruction_id,
            device_id=params["device_id"],
            server_id=params["server_id"],
            waypoints=params.get("waypoints", []),
            total_distance_m=params.get("total_distance_m", 0),
            estimated_time_s=params.get("estimated_time_s", 0),
            algorithm_used=params.get("algorithm_used", ""),
            metadata=params.get("metadata", {}),
        )
        return self._handle_result("receive_trajectory", result)

    def receive_drone_status(self, params):
        """接收类脑盒子转发的无人机位置/状态"""
        device_id = params["device_id"]
        self.progress_callback(10, f"接收无人机状态: {device_id}")
        result = self._manager.receive_drone_status(
            device_id=device_id,
            position=params.get("position"),
            velocity=params.get("velocity"),
            attitude=params.get("attitude"),
            battery_pct=params.get("battery_pct", 0),
            flight_mode=params.get("flight_mode", "unknown"),
            armed=params.get("armed", False),
            gps_fix_type=params.get("gps_fix_type", 0),
            satellites_visible=params.get("satellites_visible", 0),
            raw_mavlink=params.get("raw_mavlink", {}),
        )
        return self._handle_result("receive_drone_status", result)

    def get_navigation_status(self, params):
        """查询导航指令状态及关联轨迹"""
        instruction_id = params["instruction_id"]
        self.progress_callback(10, f"查询导航状态: {instruction_id}")
        info = self._manager.get_navigation_status(instruction_id)
        if info is None:
            result = {"code": -1, "msg": f"导航指令 {instruction_id} 不存在", "data": {}}
        else:
            result = {"code": 0, "msg": "success", "data": info}
        return self._handle_result("get_navigation_status", result)

    def get_drone_status(self, params):
        """查询设备最新的无人机状态"""
        device_id = params["device_id"]
        self.progress_callback(10, f"查询无人机状态: {device_id}")
        info = self._manager.get_drone_status(device_id)
        if info is None:
            result = {"code": -1, "msg": f"设备 {device_id} 无状态数据", "data": {}}
        else:
            result = {"code": 0, "msg": "success", "data": info}
        return self._handle_result("get_drone_status", result)
