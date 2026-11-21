"""
wecom_bot.py — 企业微信智能机器人适配器（长连接模式）
"""
import asyncio

import aiohttp
from bot.base import BaseChannel, InboundMessage, OutboundMessage
from aibot.client import WSClient, WSClientOptions


class WecomBot(BaseChannel):
    """企业微信适配器 — WebSocket 长连接，无需公网地址"""

    def __init__(self, bot_id: str, secret: str):
        super().__init__(platform_name="wecom")
        self.bot_id = bot_id
        self.secret = secret
        self._client: WSClient | None = None

    async def start(self):
        print(f"[WecomBot] 启动中（长连接模式）...")

        options = WSClientOptions(bot_id=self.bot_id, secret=self.secret)
        self._client = WSClient(options)

        @self._client.on("message.text")
        async def _on_text(frame):
            body = frame.get("body", {})
            if not body:
                return

            chatid = body.get("chatid", "")
            userid = body.get("from", {}).get("userid", "unknown")
            text = body.get("text", {}).get("content", "")
            response_url = body.get("response_url", "")

            if not text.strip():
                return

            if body.get("chattype") == "group" and " " in text:
                text = text.split(" ", 1)[1]

            inbound = InboundMessage(
                session_id=f"wecom_{chatid}",
                user_id=userid,
                user_name="企微用户",
                text=text.strip(),
                platform="wecom",
            )

            if self._callback is None:
                return
            reply_text = await self._callback(inbound)
            if not reply_text:
                return

            for segment in reply_text.split("\n---SPLIT---\n"):
                if response_url:
                    await self._reply_via_url(response_url, segment)

        await self._client.connect()
        print(f"[WecomBot] 已启动（长连接模式），等待消息...")
        while self._client.is_connected:
            await asyncio.sleep(30)

    async def _reply_via_url(self, response_url: str, text: str):
        """通过 response_url HTTP POST 回复消息"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    response_url,
                    json={"msgtype": "markdown", "markdown": {"content": text}},
                ) as resp:
                    result = await resp.json()
                    if result.get("errcode") != 0:
                        print(f"[WecomBot] 回复失败: {result}")
        except Exception as e:
            print(f"[WecomBot] 回复异常: {e}")

    async def send(self, msg: OutboundMessage):
        pass  # 企业微信通过 response_url 回复，不走 send
