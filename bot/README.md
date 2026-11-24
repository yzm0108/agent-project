# 🔌 多平台 Bot 扩展

给「贵AI」穿上 飞书 / 企业微信 的外壳 — 同一套 Agent，多端服务。

## 架构

```
飞书用户   ──→ FeishuBot (长连接 + API)   ──┐
                                              ├──→ BotHandler ──→ GuizhouAgent
企微用户   ──→ WecomBot  (长连接)          ──┘
```

**核心设计**：
- **适配器模式**：FeishuBot / WecomBot 实现统一的 BaseChannel 接口
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
feishu:
  app_id: "cli_xxxxx"              # 从飞书开放平台获取
  app_secret: "xxxxx"

wecom:
  bot_id: "xxxxx"                  # 从企业微信管理后台获取
  secret: "xxxxx"
```

或者用环境变量（推荐，避免密钥提交到 git）：

```bash
export FEISHU_APP_ID="cli_xxxxx"
export FEISHU_APP_SECRET="xxxxx"
export WECOM_BOT_ID="xxxxx"
export WECOM_BOT_SECRET="xxxxx"
```

### 3. 启动

```bash
# 只启动飞书
python bot/main.py --platform feishu

# 只启动企业微信
python bot/main.py --platform wecom

# 同时启动两个平台
python bot/main.py --platform all
```

## 平台接入指南

### 飞书（长连接，无需公网地址）

1. 访问 [飞书开放平台](https://open.feishu.cn/) 创建企业自建应用
2. 开启「机器人」能力
3. 获取 App ID 和 App Secret
4. 事件订阅 → 选择「使用长连接接收事件」
5. 订阅事件：`im.message.receive_v1`
6. 添加权限：`im:message:receive_v1`、`im:message:send_v1`

> 长连接由 `lark-oapi` SDK 主动连出，不需要 ngrok，也不需要公网 IP。

### 企业微信（长连接，无需公网地址）

1. 在企业微信管理后台创建智能机器人，选「API 模式」
2. 开启「长连接」收发消息
3. 获取 Bot ID 和 Secret
4. 运行后自动建立 WebSocket 长连接，无需公网地址

> ⚠️ 企微长连接模式回复仅支持 `markdown` / `template_card`，不支持 `text`。

## 文件说明

| 文件 | 职责 |
|------|------|
| `base.py` | 适配器基类 + 统一消息格式（InboundMessage / OutboundMessage） |
| `handler.py` | 核心处理器 — 持有 GuizhouAgent，管理会话历史 |
| `feishu_bot.py` | 飞书适配器（WebSocket 长连接 + HTTP API） |
| `wecom_bot.py` | 企业微信适配器（WebSocket 长连接） |
| `main.py` | 统一启动入口 |
| `config.yaml` | 配置文件（模板） |

## 设计要点

| 问题 | 答案 |
|------|---------|
| 多平台 Bot 怎么设计的？ | 适配器模式，BaseChannel 统一接口，新增平台不改核心代码 |
| 不同平台的会话怎么隔离？ | handler 用 session_id 为 key 维护独立 history dict，30 分钟过期 |
| 飞书接入的难点？ | 长连接 SDK 在独立线程跑事件循环、回调跨线程回主循环、token 管理（提前 5 分钟刷新） |
| 企微接入的难点？ | 长连接 SDK 的 reply() 是 async，需 await；仅支持 markdown/template_card |
| 怎么对接已有的 Agent？ | 复用 agent.run() 接口，传入 history，取回 new_history 更新会话 |
