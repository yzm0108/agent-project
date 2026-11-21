"""
base.py — 适配器基类，定义统一消息格式与平台接口
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InboundMessage:
    """用户发来的消息（统一格式，屏蔽平台差异）"""
    session_id: str       # 会话标识（如 "wecom_xxx"、"feishu_abc"）
    user_id: str          # 用户 ID
    user_name: str        # 用户昵称
    text: str             # 消息文本
    platform: str         # 来源平台（"feishu" / "wecom"）
    timestamp: float = 0.0


@dataclass
class OutboundMessage:
    """Agent 要回复的消息"""
    session_id: str
    text: str
    platform: str


class BaseChannel(ABC):
    """
    所有平台适配器的基类。

    子类需要实现：
    - start(): 启动通道，开始接收消息
    - send(msg): 发送一条消息

    子类可以调用：
    - on_message(callback): 注册消息回调，收到用户消息时调用
    """

    def __init__(self, platform_name: str):
        self.platform = platform_name
        self._callback = None  # 消息回调函数: async (InboundMessage) -> str

    def on_message(self, callback):
        """注册消息处理回调。callback 签名为 async (InboundMessage) -> str（返回回复文本）"""
        self._callback = callback

    async def _handle_incoming(self, msg: InboundMessage):
        """收到用户消息 → 调用回调 → 发送回复"""
        if self._callback is None:
            return
        reply = await self._callback(msg)
        if reply:
            await self.send(OutboundMessage(
                session_id=msg.session_id,
                text=reply,
                platform=self.platform,
            ))

    @abstractmethod
    async def start(self):
        """启动适配器，开始监听消息"""
        ...

    @abstractmethod
    async def send(self, msg: OutboundMessage):
        """发送一条消息到对应平台"""
        ...
