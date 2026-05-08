"""
虚拟类脑盒子 (SimBrainBox)
封装 brain_box/ 中的 BrainBox 类进行本地集成测试。

核心思路：
  BrainBox 内部已包含 Navigator（轨迹生成）和 MAVLinkAdapter（模拟飞控），
  唯一缺失的是 EdgeServiceClient 在模拟模式下只打日志、不实际送达 CloudEdgeManager。
  本模块通过 monkey-patch EdgeServiceClient._post，将其路由到 CloudEdgeManager 实例，
  从而实现 brain_box 全套代码在本地的端到端测试。

替换真机时：
  BrainBox 的 EdgeServiceClient 切换为 HTTP 模式（simulated=False），
  MAVLinkAdapter 切换为真实 MAVLink 连接（simulated=False），
  边缘服务代码无需修改。
"""
import os
import sys
import logging
import importlib
from typing import Any, Dict, Optional

logger = logging.getLogger("sim_brain_box")


# ---------------------------------------------------------------------------
#  隔离导入 brain_box 模块
#  brain_box/ 和 edge_service/ 都有 models.py、config.py 等同名模块，
#  需要确保导入时互不干扰。
# ---------------------------------------------------------------------------

_brain_box_dir = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "brain_box")
)


def _import_brain_box():
    """
    在隔离的 sys.path 环境中导入 brain_box 的模块，
    避免与 edge_service 的同名模块冲突。
    """
    # 保存可能被 edge_service 污染的同名模块
    conflicting_names = ["models", "config", "main", "navigator", "edge_client", "mavlink_adapter"]
    saved_modules = {}
    for name in conflicting_names:
        if name in sys.modules:
            saved_modules[name] = sys.modules.pop(name)

    # 临时将 brain_box 放到 sys.path 最前面
    sys.path.insert(0, _brain_box_dir)

    try:
        bb_main = importlib.import_module("main")
        bb_config = importlib.import_module("config")

        BrainBox = bb_main.BrainBox
        BrainBoxConfig = bb_config.BrainBoxConfig
        EdgeServiceConfig = bb_config.EdgeServiceConfig
        MAVLinkConfig = bb_config.MAVLinkConfig
        NavigatorConfig = bb_config.NavigatorConfig

        return BrainBox, BrainBoxConfig, EdgeServiceConfig, MAVLinkConfig, NavigatorConfig
    finally:
        # 清理 brain_box 的模块缓存，恢复之前的模块
        for name in conflicting_names:
            sys.modules.pop(name, None)
        for name, mod in saved_modules.items():
            sys.modules[name] = mod
        sys.path.remove(_brain_box_dir)


BrainBox, BrainBoxConfig, EdgeServiceConfig, MAVLinkConfig, NavigatorConfig = _import_brain_box()


# ---------------------------------------------------------------------------
#  桥接函数
# ---------------------------------------------------------------------------

def _make_post_bridge(manager: Any, device_id: str) -> Any:
    """
    创建桥接函数，将 EdgeServiceClient._post 的调用
    路由到本地 CloudEdgeManager 实例的对应方法。

    映射关系：
      POST /heartbeat            → manager.refresh_server_heartbeat / refresh_device_heartbeat
      POST /submit_task_result   → manager.submit_task_result
      POST /update_device_telemetry → manager.update_device_telemetry
    """
    def _bridged_post(endpoint: str, payload: Dict[str, Any]) -> bool:
        try:
            if endpoint == "heartbeat":
                target_type = payload.get("target_type", "server")
                target_id = payload.get("target_id", "")
                if target_type == "server":
                    return manager.refresh_server_heartbeat(target_id)
                else:
                    return manager.refresh_device_heartbeat(target_id, location=payload.get("location"))

            elif endpoint == "submit_task_result":
                result = manager.submit_task_result(
                    task_id=payload["task_id"],
                    result_type=payload.get("result_type", ""),
                    payload=payload.get("payload", {}),
                    metadata=payload.get("metadata", {}),
                )
                return result.get("code", -1) == 0

            elif endpoint == "update_device_telemetry":
                result = manager.update_device_telemetry(
                    device_id=payload.get("device_id", device_id),
                    telemetry_type=payload.get("telemetry_type", ""),
                    data=payload.get("data", {}),
                    metadata=payload.get("metadata", {}),
                )
                return result.get("code", -1) == 0

            else:
                logger.warning("未知的桥接端点: %s", endpoint)
                return False
        except Exception:
            logger.exception("桥接调用失败: %s", endpoint)
            return False

    return _bridged_post


# ---------------------------------------------------------------------------
#  SimBrainBox
# ---------------------------------------------------------------------------

class SimBrainBox:
    """
    虚拟类脑盒子 — 封装 brain_box/main.py 中的 BrainBox。

    使用 brain_box 的完整代码栈（Navigator + MAVLinkAdapter + EdgeServiceClient），
    通过桥接让 EdgeServiceClient 直接调用 CloudEdgeManager 实例。

    用法：
        sim = SimBrainBox(manager, server_id="svr_brain_01", device_id="drone_01")
        sim.start()
        sim.handle_task(task_id, task_config)
        sim.stop()
    """

    def __init__(
        self,
        manager: Any,
        server_id: str = "svr_brain_sim_01",
        device_id: str = "drone_sim_01",
        config: Optional[BrainBoxConfig] = None,
    ):
        """
        Args:
            manager:   CloudEdgeManager 实例，桥接目标
            server_id: 类脑盒子作为计算服务器的 ID
            device_id: 关联的无人机设备 ID（用于遥测转发）
        """
        self._manager = manager
        self.server_id = server_id
        self.device_id = device_id

        if config is None:
            config = BrainBoxConfig(
                edge_service=EdgeServiceConfig(
                    device_id=device_id,
                    server_id=server_id,
                ),
                mavlink=MAVLinkConfig(),
                navigator=NavigatorConfig(),
            )

        # 在隔离环境中实例化 BrainBox
        sys.path.insert(0, _brain_box_dir)
        try:
            self._brain_box = BrainBox(config=config)
        finally:
            sys.path.remove(_brain_box_dir)

        # 桥接：替换 EdgeServiceClient._post，路由到 CloudEdgeManager
        # 保持 _simulated=True 让 connect() 正常通过，但 _post 已被桥接替换
        self._brain_box._edge_client._post = _make_post_bridge(manager, device_id)

    @property
    def brain_box(self) -> BrainBox:
        return self._brain_box

    @property
    def state(self) -> str:
        return self._brain_box.state.value

    def start(self) -> bool:
        ok = self._brain_box.start()
        if ok:
            logger.info("[SimBrainBox:%s] 启动成功（使用 brain_box 完整代码栈）", self.server_id)
        return ok

    def handle_task(self, task_id: str, task_config: Dict[str, Any]) -> bool:
        """
        处理一条导航任务。

        内部调用 BrainBox.handle_navigation()，执行完整流程：
          1. Navigator 生成轨迹
          2. EdgeServiceClient.report_trajectory → 桥接 → CloudEdgeManager.submit_task_result
          3. MAVLinkAdapter.upload_mission → 模拟下发航点
          4. MAVLinkAdapter 模拟飞行 + 遥测 → EdgeServiceClient.forward_drone_status → 桥接

        nav_config 从 task_config["custom_payloads"] 提取。
        """
        custom = task_config.get("custom_payloads", {})
        nav_config = {
            "start_point": custom.get("start_point", {}),
            "end_point": custom.get("end_point", {}),
            "algorithm": task_config.get("algorithm", custom.get("algorithm", "default")),
            "nav_params": custom.get("nav_params", {}),
        }
        logger.info("[SimBrainBox:%s] 处理任务 %s", self.server_id, task_id)
        return self._brain_box.handle_navigation(task_id, nav_config)

    def stop(self) -> None:
        self._brain_box.stop()
        logger.info("[SimBrainBox:%s] 已停止", self.server_id)
