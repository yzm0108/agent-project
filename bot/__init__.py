# 多平台 Bot 扩展包 — 给贵AI 穿上 Telegram / 飞书的外壳
from .base import BaseChannel, InboundMessage, OutboundMessage
from .handler import BotHandler
from .telegram_bot import TelegramBot
from .feishu_bot import FeishuBot

__all__ = [
    "BaseChannel", "InboundMessage", "OutboundMessage",
    "BotHandler", "TelegramBot", "FeishuBot",
]
