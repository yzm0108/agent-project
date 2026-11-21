"""
main.py — 多平台 Bot 统一启动入口

用法:
    # 只启动飞书
    python bot/main.py --platform feishu

    # 只启动企业微信
    python bot/main.py --platform wecom

    # 同时启动所有已配置平台
    python bot/main.py --platform all

配置:
    在 config.yaml 中填入你的 Bot Token / App ID 等。
    所有密钥也可以通过环境变量传入（会覆盖 config.yaml）。
"""
import os
import re
import sys
import asyncio
import argparse
import yaml
from dotenv import load_dotenv

# 把项目根目录加入路径，方便 import bot 和 guizhou_agent
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, "guizhou_agent", ".env"))

from bot.handler import BotHandler
from bot.feishu_bot import FeishuBot


def load_config():
    """加载 config.yaml + 环境变量覆盖"""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")

    if not os.path.exists(config_path):
        print("[main] 未找到 config.yaml，将使用 config.example.yaml 作为模板")
        example_path = os.path.join(os.path.dirname(__file__), "config.example.yaml")
        if os.path.exists(example_path):
            config_path = example_path

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 解析 ${ENV_VAR} 占位符
    def resolve_env(value):
        if isinstance(value, str):
            pattern = r"\$\{(\w+)\}"
            def replace(m):
                return os.getenv(m.group(1), "")
            return re.sub(pattern, replace, value)
        elif isinstance(value, dict):
            return {k: resolve_env(v) for k, v in value.items()}
        return value
    config = resolve_env(config)

    return config


async def main():
    parser = argparse.ArgumentParser(description="贵AI 多平台 Bot")
    parser.add_argument(
        "--platform",
        choices=["feishu", "wecom", "all"],
        default="all",
        help="启动哪个平台（默认 all）",
    )
    args = parser.parse_args()
    config = load_config()

    print("=" * 50)
    print("  贵AI — 贵州旅游智能助手（多平台版）")
    print("=" * 50)

    # 创建 Handler，内部加载知识库和 Agent
    handler = BotHandler()

    # 收集要启动的适配器
    adapters = []

    if args.platform in ("feishu", "all"):
        feishu_cfg = config.get("feishu", {})
        feishu_app_id = feishu_cfg.get("app_id", "")
        feishu_app_secret = feishu_cfg.get("app_secret", "")
        if not feishu_app_id or not feishu_app_secret:
            print("[main] ⚠️  未配置飞书 App ID/Secret，跳过飞书")
        else:
            feishu_port = feishu_cfg.get("port", 8080)
            feishu = FeishuBot(
                app_id=feishu_app_id,
                app_secret=feishu_app_secret,
                port=feishu_port,
            )
            feishu.on_message(handler.handle)
            adapters.append(("飞书", feishu))

    if args.platform in ("wecom", "all"):
        # 延迟导入：只跑飞书时，不需要安装企业微信 SDK
        from bot.wecom_bot import WecomBot

        wecom_cfg = config.get("wecom", {})
        wecom_bot_id = wecom_cfg.get("bot_id", "")
        wecom_secret = wecom_cfg.get("secret", "")
        if not wecom_bot_id or not wecom_secret:
            print("[main] ⚠️  未配置企业微信 Bot ID/Secret，跳过企业微信")
        else:
            wecom = WecomBot(bot_id=wecom_bot_id, secret=wecom_secret)
            wecom.on_message(handler.handle)
            adapters.append(("企业微信", wecom))

    if not adapters:
        print("[main] ❌ 没有可启动的平台，请检查 config.yaml")
        return

    print(f"\n[main] 启动平台: {', '.join(name for name, _ in adapters)}")
    print(f"[main] 知识库条目: {handler.kb.collection.count()} 条\n")

    # 并发启动所有适配器
    tasks = [asyncio.create_task(adapter.start()) for _, adapter in adapters]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
