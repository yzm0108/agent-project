# 🔌 多平台 Bot 扩展

给「贵AI」穿上 Telegram / 飞书的外壳 — 同一套 Agent，多端服务。

## 架构

```
Telegram 用户 ──→ TelegramBot (适配器) ──┐
                                          ├──→ BotHandler ──→ GuizhouAgent
飞书用户    ──→ FeishuBot   (适配器) ──┘
```

**核心设计**：
- **适配器模式**：TelegramBot / FeishuBot 实现统一的 BaseChannel 接口
- **会话隔离**：每个 session_id 独立维护对话历史，互不干扰
- **零侵入**：不修改 `guizhou_agent/` 一行代码，直接复用

## 快速开始

### 1. 安装依赖

```bash
pip install -r bot/requirements.txt
```

### 2. 配置

```bash
cp bot/config.yaml bot/config.local.yaml   # 复制一份本地配置
```

编辑 `bot/config.local.yaml`，填入你的密钥：

```yaml
telegram:
  token: "123456:ABC-DEF1234gh"    # 从 @BotFather 获取

feishu:
  app_id: "cli_xxxxx"              # 从飞书开放平台获取
  app_secret: "xxxxx"
```

或者用环境变量（推荐，避免密钥提交到 git）：

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234gh"
export FEISHU_APP_ID="cli_xxxxx"
export FEISHU_APP_SECRET="xxxxx"
```

### 3. 启动

```bash
# 只启动 Telegram
python bot/main.py --platform telegram

# 只启动飞书
python bot/main.py --platform feishu

# 同时启动两个平台
python bot/main.py --platform all
```

## 平台接入指南

### Telegram（最简单，一分钟）

1. Telegram 搜索 **@BotFather**
2. 发送 `/newbot`，按提示设置名称
3. 获得 Token
4. 启动后直接在 Telegram 里跟你的 Bot 对话

### 飞书（需要公网地址）

1. 访问 [飞书开放平台](https://open.feishu.cn/) 创建企业自建应用
2. 开启「机器人」能力
3. 获取 App ID 和 App Secret
4. 本地开发用 ngrok 暴露端口：

```bash
ngrok http 8080
# 把 https://xxx.ngrok.io/feishu/webhook 填入飞书后台「事件订阅」
```

5. 订阅事件：`im.message.receive_v1`
6. 添加权限：`im:message:receive_v1`、`im:message:send_v1`

## 文件说明

| 文件 | 职责 |
|------|------|
| `base.py` | 适配器基类 + 统一消息格式（InboundMessage / OutboundMessage） |
| `handler.py` | 核心处理器 — 持有 GuizhouAgent，管理会话历史 |
| `telegram_bot.py` | Telegram 适配器 |
| `feishu_bot.py` | 飞书适配器（Webhook + HTTP API） |
| `main.py` | 统一启动入口 |
| `config.yaml` | 配置文件（模板） |

## 设计要点

| 问题 | 答案 |
|------|---------|
| 多平台 Bot 怎么设计的？ | 适配器模式，BaseChannel 统一接口，新增平台不改核心代码 |
| 不同平台的会话怎么隔离？ | handler 用 session_id 为 key 维护独立 history dict，30 分钟过期 |
| 飞书接入的难点？ | token 管理（提前 5 分钟刷新）、webhook 验证、消息格式转换 |
| 怎么对接已有的 Agent？ | 复用 agent.run() 接口，传入 history，取回 new_history 更新会话 |
