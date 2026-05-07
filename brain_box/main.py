"""
类脑盒子主程序入口
编排 MAVLink 适配器、边缘服务客户端、导航器之间的协作。

数据流：
  边缘控制服务 --[导航指令]--> 类脑盒子 --[轨迹]--> 无人机(MAVLink)
  无人机(MAVLink) --[位置/状态]--> 类脑盒子 --[转发]--> 边缘控制服务
"""
import time
import signal
import logging
import threading
from typing import Optional

from config import BrainBoxConfig
from models import (
    BrainBoxState,
    DroneState,
    NavigationInstruction,
    Waypoint,
)
from mavlink_adapter import MAVLinkAdapter
from edge_client import EdgeServiceClient
from navigator import Navigator

logger = logging.getLogger("brain_box")


class BrainBox:
    """
    类脑盒子核心控制器。

    生命周期：
      1. start() — 连接 MAVLink + 边缘服务，启动心跳和遥测转发
      2. handle_navigation(instruction) — 生成轨迹 → 上报边缘 → 下发无人机
      3. stop() — 优雅关闭所有连接和线程
    """

    def __init__(self, config: Optional[BrainBoxConfig] = None):
        self._config = config or BrainBoxConfig.from_env()
        self._state = BrainBoxState.IDLE
        self._lock = threading.Lock()

        self._navigator = Navigator(self._config.navigator)

        self._mavlink = MAVLinkAdapter(
            config=self._config.mavlink,
            on_state_update=self._on_drone_state_update,
            simulated=True,  # 默认模拟模式，真实环境改为 False
        )

        self._edge_client = EdgeServiceClient(
            config=self._config.edge_service,
            on_navigation_received=self._on_navigation_received,
            simulated=True,  # 默认模拟模式
        )

        self._status_forward_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_instruction: Optional[NavigationInstruction] = None

    @property
    def state(self) -> BrainBoxState:
        with self._lock:
            return self._state

    def start(self) -> bool:
        logger.info("Starting BrainBox...")

        # 1. 连接 MAVLink
        if not self._mavlink.connect():
            logger.error("Failed to connect MAVLink")
            return False

        # 2. 连接边缘服务
        if not self._edge_client.connect():
            logger.error("Failed to connect edge service")
            self._mavlink.disconnect()
            return False

        # 3. 启动状态转发线程
        self._stop_event.clear()
        self._status_forward_thread = threading.Thread(
            target=self._status_forward_loop,
            name="status-forward",
            daemon=True,
        )
        self._status_forward_thread.start()

        with self._lock:
            self._state = BrainBoxState.CONNECTED
        logger.info("BrainBox started successfully")
        return True

    def stop(self) -> None:
        logger.info("Stopping BrainBox...")
        self._stop_event.set()
        if self._status_forward_thread:
            self._status_forward_thread.join(timeout=3)
        self._edge_client.disconnect()
        self._mavlink.disconnect()
        with self._lock:
            self._state = BrainBoxState.IDLE
        logger.info("BrainBox stopped")

    # ------------------------------------------------------------------
    #  导航处理（核心流程）
    # ------------------------------------------------------------------

    def handle_navigation(self, instruction: NavigationInstruction) -> bool:
        """
        处理一条导航指令:
          1. 调用导航器生成轨迹
          2. 将轨迹上报给边缘控制服务
          3. 将轨迹航点下发给无人机
        """
        with self._lock:
            self._state = BrainBoxState.NAVIGATING
            self._current_instruction = instruction

        logger.info(
            "Processing navigation: %s (%s -> %s)",
            instruction.instruction_id,
            instruction.start_point,
            instruction.end_point,
        )

        # 步骤 1: 生成轨迹
        trajectory = self._navigator.plan(instruction)
        logger.info(
            "Trajectory generated: %d waypoints, %.1fm, ~%.0fs",
            len(trajectory.waypoints),
            trajectory.total_distance_m,
            trajectory.estimated_time_s,
        )

        # 步骤 2: 上报轨迹给边缘控制服务
        self._edge_client.report_trajectory(
            instruction_id=instruction.instruction_id,
            waypoints=trajectory.waypoints,
            total_distance_m=trajectory.total_distance_m,
            estimated_time_s=trajectory.estimated_time_s,
            algorithm_used=trajectory.algorithm_used,
        )
        logger.info("Trajectory reported to edge service")

        # 步骤 3: 下发航点到无人机
        if not self._mavlink.upload_mission(trajectory.waypoints):
            logger.error("Failed to upload mission to drone")
            with self._lock:
                self._state = BrainBoxState.ERROR
            return False

        # 切换飞行模式为 AUTO 并解锁
        self._mavlink.set_mode("AUTO")
        self._mavlink.arm()
        logger.info("Mission sent to drone, mode=AUTO, armed")
        return True

    # ------------------------------------------------------------------
    #  回调
    # ------------------------------------------------------------------

    def _on_navigation_received(self, instruction: NavigationInstruction) -> None:
        logger.info("Navigation instruction received: %s", instruction.instruction_id)
        self.handle_navigation(instruction)

    def _on_drone_state_update(self, drone_state: DroneState) -> None:
        pass  # 由转发线程统一处理，避免频率过高

    # ------------------------------------------------------------------
    #  状态转发循环
    # ------------------------------------------------------------------

    def _status_forward_loop(self) -> None:
        interval = self._config.mavlink.status_report_interval_s
        while not self._stop_event.is_set():
            try:
                drone_state = self._mavlink.state
                self._edge_client.forward_drone_status(
                    device_id=self._config.edge_service.device_id,
                    drone_state=drone_state,
                )
            except Exception:
                logger.exception("Status forward error")
            self._stop_event.wait(interval)


# ---------------------------------------------------------------------------
#  CLI 入口
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = BrainBoxConfig.from_env()
    brain_box = BrainBox(config)

    # 优雅退出
    def signal_handler(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        brain_box.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not brain_box.start():
        logger.error("BrainBox failed to start")
        return

    logger.info("BrainBox is running. Press Ctrl+C to stop.")

    # 模拟模式演示：注入一条导航指令
    demo_instruction = NavigationInstruction(
        instruction_id="nav_demo_001",
        task_id="task_demo_001",
        device_id=config.edge_service.device_id,
        server_id=config.edge_service.server_id,
        start_point={"lat": 30.270, "lng": 120.150, "alt": 10.0},
        end_point={"lat": 30.280, "lng": 120.160, "alt": 10.0},
        algorithm="linear_interpolation",
        nav_params={"speed_m_s": 5.0, "waypoint_interval_m": 100.0},
    )
    brain_box.handle_navigation(demo_instruction)

    # 保持运行
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        brain_box.stop()


if __name__ == "__main__":
    main()
