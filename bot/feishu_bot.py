"""
feishu_bot.py — 飞书平台适配器

技术选型：aiohttp（轻量异步 HTTP）+ 飞书开放 API

接入步骤：
1. 访问 https://open.feishu.cn/ 创建企业自建应用
2. 在「机器人」页面开启机器人能力
3. 获取 App ID 和 App Secret → 写入 config.yaml
4. 在「事件订阅」中配置请求地址：https://你的域名/feishu/webhook
5. 订阅事件：im.message.receive_v1
6. 添加权限：im:message:receive_v1、im:message:send_v1

本地开发可配合 ngrok: ngrok http 8080
然后把 https://xxx.ngrok.io/feishu/webhook 填入飞书后台

飞书消息格式比较复杂（支持富文本卡片），这里只处理纯文本消息。
"""
import json
import time
import aiohttp
from aiohttp import web
from bot.base import BaseChannel, InboundMessage, OutboundMessage


class FeishuBot(BaseChannel):
    """飞书适配器 — 通过 Webhook 接收消息，HTTP API 发送回复"""

    def __init__(self, app_id: str, app_secret: str, port: int = 8080):
        super().__init__(platform_name="feishu")
        self.app_id = app_id
        self.app_secret = app_secret
        self.port = port
        self._tenant_token: str | None = None
        self._token_expire: float = 0.0
        self._seen_event_ids: set[str] = set()
        self._startup_time = time.time()

    # ===== 启动 =====

    async def start(self):
        """启动 HTTP 服务器接收飞书事件"""
        print(f"[FeishuBot] 启动中 (0.0.0.0:{self.port})...")
        print(f"[FeishuBot] Webhook 地址: http://你的IP:{self.port}/feishu/webhook")

        # 先获取 token
        await self._get_tenant_token()

        app = web.Application()
        app.router.add_post("/feishu/webhook", self._handle_webhook)
        app.router.add_get("/feishu/webhook", self._handle_challenge)  # 飞书首次配置时会发 GET 验证

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()

        print(f"[FeishuBot] 已启动，等待消息...")
        # 永久保持运行
        while True:
            await asyncio.sleep(3600)

    async def _handle_challenge(self, request: web.Request) -> web.Response:
        """飞书首次配置事件订阅时的 URL 验证"""
        body = await request.json()
        challenge = body.get("challenge")
        if challenge:
            return web.json_response({"challenge": challenge})
        return web.json_response({"error": "no challenge"}, status=400)

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """接收飞书推送的事件"""
        body = await request.json()

        # 飞书会先发 challenge 验证
        if body.get("type") == "url_verification":
            return web.json_response({"challenge": body["challenge"]})

        # 处理消息事件
        header = body.get("header", {})
        if header.get("event_type") != "im.message.receive_v1":
            return web.json_response({"code": 0})

        create_time_ms = int(header.get("create_time", 0))
        if create_time_ms and create_time_ms / 1000 < self._startup_time - 5:
            return web.json_response({"code": 0})

        event_id = header.get("event_id", "")
        if event_id and event_id in self._seen_event_ids:
            return web.json_response({"code": 0})
        if event_id:
            self._seen_event_ids.add(event_id)
            if len(self._seen_event_ids) > 1000:
                self._seen_event_ids.clear()

        event = body.get("event", {})
        message = event.get("message", {})
        content_str = message.get("content", "{}")
        try:
            content = json.loads(content_str)
            text = content.get("text", "")
        except json.JSONDecodeError:
            text = ""

        if not text.strip():
            return web.json_response({"code": 0})

        sender = event.get("sender", {}).get("sender_id", {})
        user_id = sender.get("open_id", "unknown")
        chat_id = event.get("message", {}).get("chat_id", "")

        inbound = InboundMessage(
            session_id=f"feishu_{chat_id}",
            user_id=user_id,
            user_name="飞书用户",
            text=text,
            platform="feishu",
        )

        reply = await self._handle_incoming(inbound)

        if reply:
            for segment in reply.split("\n---SPLIT---\n"):
                await self._send_text(chat_id, segment)

        return web.json_response({"code": 0})

    # ===== 发送消息 =====

    async def send(self, msg: OutboundMessage):
        chat_id = msg.session_id.replace("feishu_", "")
        for segment in msg.text.split("\n---SPLIT---\n"):
            await self._send_text(chat_id, segment)

    async def _send_text(self, receive_id: str, text: str):
        """通过飞书 API 发送文本消息"""
        token = await self._get_tenant_token()
        if not token:
            print("[FeishuBot] 无法获取 token，消息发送失败")
            return

        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {"receive_id_type": "chat_id"}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, params=params, headers=headers, json=body
                ) as resp:
                    result = await resp.json()
                    if result.get("code") != 0:
                        print(f"[FeishuBot] 发送失败: {result}")
                    else:
                        print(f"[FeishuBot] 发送成功")
        except Exception as e:
            print(f"[FeishuBot] 发送异常: {e}")

    # ===== Token 管理 =====

    async def _get_tenant_token(self) -> str | None:
        """获取飞书 tenant_access_token（带缓存，提前 5 分钟刷新）"""
        if self._tenant_token and time.time() < self._token_expire - 300:
            return self._tenant_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        body = {"app_id": self.app_id, "app_secret": self.app_secret}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body) as resp:
                    data = await resp.json()
                    if data.get("code") != 0:
                        print(f"[FeishuBot] Token 获取失败: {data}")
                        return None
                    self._tenant_token = data["tenant_access_token"]
                    self._token_expire = time.time() + data.get("expire", 7200)
                    return self._tenant_token
        except Exception as e:
            print(f"[FeishuBot] Token 获取异常: {e}")
            return None


# 需要 asyncio（飞书用 asyncio.sleep）
import asyncio
