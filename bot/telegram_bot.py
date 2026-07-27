"""
telegram_bot.py — Telegram 平台适配器

技术选型：python-telegram-bot（最成熟的 Telegram Bot 库，异步支持好）

创建 Bot 步骤（一分钟）：
1. Telegram 搜索 @BotFather
2. 发送 /newbot，按提示设置名称
3. 获得 Token（格式：123456:ABC-DEF1234gh）
4. 写入 config.yaml 的 telegram.token
"""
import asyncio
from bot.base import BaseChannel, InboundMessage, OutboundMessage


class TelegramBot(BaseChannel):
    """Telegram 适配器 — 把 Telegram 消息翻译成 InboundMessage"""

    def __init__(self, token: str):
        super().__init__(platform_name="telegram")
        self.token = token
        self._app = None

    async def start(self):
        """启动 Telegram Bot，开始轮询消息"""
        try:
            from telegram import Update
            from telegram.ext import Application, MessageHandler, filters, ContextTypes
        except ImportError:
            raise ImportError(
                "需要 python-telegram-bot: pip install python-telegram-bot"
            )

        print(f"[TelegramBot] 启动中...")

        self._app = Application.builder().token(self.token).build()

        # 注册消息处理器
        async def on_telegram_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.message is None or update.message.text is None:
                return

            user = update.effective_user
            chat_id = update.message.chat_id
            inbound = InboundMessage(
                session_id=f"tg_{chat_id}",
                user_id=str(user.id) if user else "unknown",
                user_name=user.full_name if user else "未知用户",
                text=update.message.text,
                platform="telegram",
            )

            # 回调 → handler → 返回回复
            reply = await self._handle_incoming(inbound)

            # 发送回复（处理分段）
            if reply:
                for segment in reply.split("\n---SPLIT---\n"):
                    await update.message.reply_text(segment)

        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, on_telegram_msg)
        )

        print(f"[TelegramBot] 已启动，等待消息...")
        await self._app.run_polling()

    async def send(self, msg: OutboundMessage):
        """主动推送消息（预留接口，非轮询模式下使用）"""
        if self._app is None:
            return
        # session_id 格式: tg_123456789
        chat_id = msg.session_id.replace("tg_", "")
        for segment in msg.text.split("\n---SPLIT---\n"):
            await self._app.bot.send_message(chat_id=int(chat_id), text=segment)
