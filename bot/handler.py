"""
handler.py — 消息处理器，桥接 Bot 适配器与 GuizhouAgent
"""
import asyncio
import time
import sys
import os
from typing import Optional

# 把 guizhou_agent 目录加入 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "guizhou_agent"))

from knowledge_base import KnowledgeBase
from agent import GuizhouAgent

# 历史记录配置
HISTORY_EXPIRE_SECONDS = 1800   # 30 分钟无活动则清理
REPLY_MAX_CHARS = 4000          # 单条消息最大字符数（Telegram 限制 4096）


class BotHandler:
    """消息处理器，对接到 GuizhouAgent"""

    def __init__(self):
        print("[BotHandler] 加载知识库...")
        self.kb = KnowledgeBase()
        print(f"[BotHandler] 知识库就绪: {self.kb.collection.count()} 条")
        self.agent = GuizhouAgent(self.kb)
        print("[BotHandler] Agent 就绪")

        # 会话历史: session_id → list[dict]
        self._sessions: dict[str, list[dict]] = {}
        # 最后活跃时间: session_id → timestamp
        self._last_active: dict[str, float] = {}

    async def handle(self, msg) -> str:
        """
        处理一条用户消息，返回回复文本。

        这是 BaseChannel._handle_incoming() 调用的回调函数。
        """
        self._cleanup_expired()
        self._last_active[msg.session_id] = time.time()

        user_question = msg.text.strip()
        if not user_question:
            return "请输入内容～"

        # 获取该会话的历史消息
        history = self._sessions.get(msg.session_id)

        answer, tool_log, sources, new_history = await asyncio.to_thread(
            self.agent.run,
            user_question=user_question,
            history=history,
        )

        # 更新会话历史
        self._sessions[msg.session_id] = new_history

        # 如果回复太长，分段
        return self._maybe_split(answer)

    def _maybe_split(self, text: str) -> str:
        """超长回复分段"""
        if len(text) <= REPLY_MAX_CHARS:
            return text
        # 按段落切分，每段不超过限制
        paragraphs = text.split("\n")
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) + 1 > REPLY_MAX_CHARS:
                if current:
                    chunks.append(current)
                current = p
            else:
                current = current + "\n" + p if current else p
        if current:
            chunks.append(current)
        # 用分隔符拼接，方便平台适配器识别分段
        return "\n---SPLIT---\n".join(chunks)

    def _cleanup_expired(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            sid for sid, ts in self._last_active.items()
            if now - ts > HISTORY_EXPIRE_SECONDS
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
            self._last_active.pop(sid, None)
        if expired:
            print(f"[BotHandler] 清理了 {len(expired)} 个过期会话")

    @property
    def active_sessions(self) -> int:
        """当前活跃会话数"""
        return len(self._sessions)
