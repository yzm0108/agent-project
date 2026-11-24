"""
feishu_bot.py — 飞书平台适配器（长连接模式）

使用飞书官方 lark-oapi SDK 的 WebSocket 长连接接收事件：
- 不需要公网地址 / ngrok
- 客户端主动连接飞书网关，app_id + app_secret 认证
- 回复仍走飞书开放 API（tenant_access_token + im/v1/messages）

接入步骤：
1. 访问 https://open.feishu.cn/ 创建企业自建应用
2. 开启机器人能力
3. 获取 App ID / App Secret → 写入 config.yaml 或环境变量
4. 事件订阅 → 选择「使用长连接接收事件」，订阅 im.message.receive_v1
5. 权限：im:message:receive_v1、im:message:send_v1
"""
import asyncio
import json
import re
import threading
import time

import aiohttp

from bot.base import BaseChannel, InboundMessage, OutboundMessage


class FeishuBot(BaseChannel):
    """飞书适配器 — WebSocket 长连接接收消息，HTTP API 发送回复"""

    def __init__(self, app_id: str, app_secret: str, port: int = 8080):
        super().__init__(platform_name="feishu")
        self.app_id = app_id
        self.app_secret = app_secret
        self.port = port  # 兼容旧配置，长连接模式不再使用
        self._tenant_token: str | None = None
        self._token_expire: float = 0.0
        self._seen_event_ids: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client = None

    # ===== 启动 =====

    async def start(self):
        """启动飞书长连接（SDK 在独立线程中运行自己的事件循环）"""
        print("[FeishuBot] 启动中（长连接模式）...")
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(
            target=self._run_ws_client, daemon=True, name="feishu-ws"
        )
        self._thread.start()

        while self._thread.is_alive():
            await asyncio.sleep(5)
        print("[FeishuBot] 长连接线程已退出")

    def _run_ws_client(self):
        """在独立线程中导入并启动 lark-oapi，避免与主事件循环冲突"""
        try:
            print("[FeishuBot] 正在加载飞书 SDK（首次导入较慢）...")
            import lark_oapi as lark

            print("[FeishuBot] SDK 已加载，建立 WebSocket 长连接...")
            handler = (
                lark.EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(self._on_message_event)
                .build()
            )
            self._client = lark.ws.Client(
                self.app_id,
                self.app_secret,
                event_handler=handler,
                log_level=lark.LogLevel.INFO,
            )
            self._client.start()
        except Exception as e:
            print(f"[FeishuBot] 长连接异常: {type(e).__name__}: {e}")

    def _on_message_event(self, data):
        """飞书事件回调（运行在 SDK 线程），转交主事件循环处理"""
        try:
            header = getattr(data, "header", None)
            event = getattr(data, "event", None)
            message = getattr(event, "message", None) if event else None
            if message is None:
                return
            if getattr(message, "message_type", "") != "text":
                return

            event_id = getattr(header, "event_id", "") if header else ""
            if event_id and event_id in self._seen_event_ids:
                return
            if event_id:
                self._seen_event_ids.add(event_id)
                if len(self._seen_event_ids) > 1000:
                    self._seen_event_ids.clear()

            chat_id = getattr(message, "chat_id", "")
            content_str = getattr(message, "content", "{}")
            try:
                text = json.loads(content_str).get("text", "")
            except (json.JSONDecodeError, TypeError):
                return
            text = re.sub(r"@_user_\d+", "", text).strip()
            if not text or not chat_id:
                return

            sender = getattr(event, "sender", None)
            sender_id = getattr(sender, "sender_id", None) if sender else None
            user_id = getattr(sender_id, "open_id", "unknown") if sender_id else "unknown"

            inbound = InboundMessage(
                session_id=f"feishu_{chat_id}",
                user_id=user_id,
                user_name="飞书用户",
                text=text,
                platform="feishu",
                timestamp=time.time(),
            )

            if self._loop is None or not self._loop.is_running():
                print("[FeishuBot] 主事件循环未运行，消息丢弃")
                return
            fut = asyncio.run_coroutine_threadsafe(
                self._handle_incoming(inbound), self._loop
            )
            fut.add_done_callback(self._log_future_error)
        except Exception as e:
            print(f"[FeishuBot] 消息解析异常: {type(e).__name__}: {e}")

    @staticmethod
    def _log_future_error(fut):
        try:
            fut.result()
        except Exception as e:
            print(f"[FeishuBot] 消息处理异常: {type(e).__name__}: {e}")

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
                        print("[FeishuBot] 发送成功")
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
