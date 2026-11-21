# 2026-07-31 开发记录

## 学习

- `bot/` 目录全架构：适配器模式（BaseChannel）、async/await 异步编程、会话管理、per-session 并发锁

## BUG 修复

| 问题 | 文件 | 根因 | 修法 |
|------|------|------|------|
| 飞书消息收不到回复 | feishu_bot.py | `event.type` 字段不存在，event_type 在 `header.event_type` | 改字段路径 |
| 飞书重复推送 | feishu_bot.py | 重启后 `_seen_event_ids` 清空，旧消息被重新处理 | event_id 去重 + `_startup_time` 时间过滤 |
| 确认锁误判 | agent.py | 关键词匹配猜不准用户意图（`_maybe_confirm_choice` / `_last_assistant_was_plan`） | 删除确认锁，交给 LLM 判断 |
| 工具说明模糊 | tools.py | get_weather 描述写"贵州省内各城市"，LLM 自己猜支持范围 | 写明仅支持 8 个城市 |

## 新功能

| 功能 | 详情 |
|------|------|
| 企业微信长连接 | 官方 SDK `aibot`（wecom-aibot-python-sdk），WebSocket 收发消息，无需公网地址 |
| 模型升级 | `deepseek-chat` → `deepseek-v4-flash`（2026-07-24 旧模型名已停用） |
| 超时保护 | agent.py 4 处 LLM 调用全部 `timeout=30` + `extra_body={"thinking": {"type": "disabled"}}` |
| 并发安全 | handler.py 加 per-session `asyncio.Lock`，同用户排队，不同用户并行 |
| 回复格式适配 | 企业微信仅支持 `markdown` / `template_card`，不支持 `text` |

## 当前状态

| 平台 | 模式 | 状态 |
|------|------|------|
| 企业微信 | WebSocket 长连接 | ✅ 运行中 |
| 飞书 | Webhook + ngrok | ✅ 运行中 |
| Telegram | 适配器已写好 | ⏸️ 等账号 |

## 踩坑记录

| 坑 | 教训 |
|------|------|
| 飞书/企微 SDK 的 `reply()` / `send_message()` 是 async，漏了 `await` | SDK 方法不一定是同步的 |
| 企微 `send_message` 返回 40008，不支持 `msgtype: "text"` | 长连接模式仅支持 markdown / template_card |
| `is_connected` 是属性不是方法 | 看源码比猜重要 |
| `loop.run_until_complete()` 不能在已有事件循环里调 | 异步上下文和同步代码的边界 |
| ngrok 版本 3.3.1 太旧被拒 | 需 ≥ 3.20.0 |

---

## 2026-08-08 更新

- **移除 Telegram 平台**：删除 `bot/telegram_bot.py`，清理 `main.py` / `__init__.py` / `config.yaml` / `requirements.txt` 中的 Telegram 引用，文档同步更新
- 现在支持的平台：飞书（Webhook）、企业微信（长连接）

---

## 2026-11-20 更新（简历同步 + 工程修正）

- **Docker**：`Dockerfile` 启动命令从旧文件名 `11_agentic_rag.py` 改为 `streamlit run guizhou_agent/app.py`；compose 补 `8501` 端口映射、`env_file`、`host.docker.internal`。
- **Ollama 地址**：`knowledge_base.py` 改为读取 `OLLAMA_BASE_URL`，容器内可连宿主机；`chroma_db` 默认路径改为项目根目录，避免 Docker 卷挂载失效。
- **企业微信 SDK**：`bot/requirements.txt` 补 `wecom-aibot-python-sdk>=1.0.2`；`bot/main.py` 改为延迟导入，只跑飞书时无需安装企微 SDK。
- **README**：删除已废弃的“确认锁定”描述，踩坑记录补充天气三级兜底、飞书事件去重。
- **待修改问题**：按当前代码重写，已修复项与仍待处理项分开。

## 2026-11-21 更新（分类与工具异常收尾）

- **分类**：自定义分类改为独立选项“＋ 自定义分类”；空分类会提示；单条添加捕获 `ValueError` / 未知异常，批量导入拦截空分类。
- **工具异常**：`ToolExecutor.execute_one` 统一返回可读错误字符串（参数错误 / 未知工具 / 执行异常），不打断 Agent 主循环；`execute_parallel` 对非法 JSON 参数返回空 dict。
- **展示**：`_format_tool_result` 对 `None` / 空列表给出“检索失败 / 未找到结果”提示。
