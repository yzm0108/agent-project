# 多平台 Bot 扩展包 — 给贵AI 穿上 飞书 / 企业微信 的外壳
from .base import BaseChannel, InboundMessage, OutboundMessage
from .handler import BotHandler
from .feishu_bot import FeishuBot

__all__ = [
    "BaseChannel", "InboundMessage", "OutboundMessage",
    "BotHandler", "FeishuBot",
]
