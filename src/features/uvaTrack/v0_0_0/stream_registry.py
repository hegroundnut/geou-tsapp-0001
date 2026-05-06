"""
流通道注册表 — 数据流隔离管理
将控制信令流（低频小包: 路径规划指令、位置上报）与高带宽媒体流（视频、激光雷达点云）
在端口与协议层面进行逻辑隔离，防止大带宽数据阻塞关键导航指令。
"""
import threading
from typing import Dict, List, Optional, Any

from models import StreamChannel, ChannelType


class StreamRegistry:
    """
    流通道注册表，管理所有设备的数据通道。

    设计原则:
    - 信令通道 (SIGNALING): 走 HTTP/WebSocket，承载路径下发、状态上报等低频控制消息
    - 媒体通道 (MEDIA): 走 WebRTC/UDP，承载视频流、点云数据等高带宽数据
    - 端口独占: 每个端口只能分配给一个通道，避免冲突
    """

    def __init__(self):
        self._channels: Dict[str, StreamChannel] = {}
        self._lock = threading.Lock()
        self._port_allocations: Dict[int, str] = {}  # port -> channel_id

    def register_channel(
        self,
        device_id: str,
        channel_type: ChannelType,
        protocol: str,
        port: int,
        stream_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[StreamChannel]:
        with self._lock:
            if port in self._port_allocations:
                return None
            channel = StreamChannel(
                channel_id=StreamChannel.generate_channel_id(),
                device_id=device_id,
                channel_type=channel_type,
                protocol=protocol,
                port=port,
                stream_type=stream_type,
                metadata=metadata or {},
            )
            self._channels[channel.channel_id] = channel
            self._port_allocations[port] = channel.channel_id
            return channel

    def unregister_channel(self, channel_id: str) -> Optional[StreamChannel]:
        with self._lock:
            channel = self._channels.pop(channel_id, None)
            if channel:
                self._port_allocations.pop(channel.port, None)
            return channel

    def get_channels_by_device(self, device_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                ch.to_dict()
                for ch in self._channels.values()
                if ch.device_id == device_id
            ]

    def close_device_channels(self, device_id: str) -> int:
        with self._lock:
            to_remove = [
                cid
                for cid, ch in self._channels.items()
                if ch.device_id == device_id
            ]
            for cid in to_remove:
                ch = self._channels.pop(cid)
                self._port_allocations.pop(ch.port, None)
            return len(to_remove)

    def is_port_available(self, port: int) -> bool:
        with self._lock:
            return port not in self._port_allocations

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [ch.to_dict() for ch in self._channels.values()]
