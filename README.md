# 🏔️ 贵AI — 贵州旅游智能助手

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.x-red)](https://streamlit.io/)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek--Chat-green)](https://platform.deepseek.com/)
[![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-orange)](https://www.trychroma.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-blue)](https://www.docker.com/)

> 从零构建 AI Agent 全栈项目 — 基于 Agentic RAG 的旅游智能助手，自主搜索知识库、规划行程、诚实回答。

---

## 🎯 核心亮点

| 能力 | 怎么做的 |
|------|---------|
| **真 Agent（非 if-else）** | LLM 自主决定调不调工具、调几个、搜什么 |
| **Agentic RAG** | 不只搜一次：结果不够→换词再搜→够了才回答 |
| **分类检索** | 知识库 6 大类，支持按分类过滤搜索 |
| **并行工具调用** | ThreadPoolExecutor，多工具同时执行 |
| **Memory 管理** | Token 计数 + 按轮裁剪 |
| **流式输出** | DeepSeek stream=True，token 逐字渲染 |
| **溯源标注** | 回答末尾标注信息来源文档 |
| **多轮对话记忆** | 跨轮上下文保留，支持指代消解 |
| **多平台接入** | Telegram + 飞书，适配器模式统一消息，同步/异步桥接 |

---

## 🏗️ 架构

```
              Streamlit 前端
                    │
           GuizhouAgent (ReAct 循环)
           Think→Act→Observe→Think...
           Memory管理 · 确认锁定 · 并行执行
            │                  │
     DeepSeek API         Ollama (本地 BGE)
     对话+工具调用          Embedding 向量化
                    │
         数据层
     ┌──────────┐  ┌──────────────┐
     │ ChromaDB │  │ 知识库 31条   │
     │ 持久向量  │  │ 6分类·语义搜索 │
     └──────────┘  └──────────────┘
```

---

## 🚀 快速开始

### 前提

- Python 3.12+ / [Ollama](https://ollama.com/) 已拉取 `bge-embed` / DeepSeek API Key

### 启动

```bash
git clone https://github.com/yzm0108/agent-project.git
cd agent-project/guizhou_agent
pip install openai python-dotenv chromadb tiktoken streamlit
# 创建 .env 填入 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL
streamlit run app.py
```

浏览器打开 **http://localhost:8501**

### Docker

```bash
docker compose up --build
```

---

## 📂 项目结构

```
agent-project/
├── guizhou_agent/
│   ├── app.py                 # Streamlit 前端
│   ├── agent.py               # Agentic RAG 核心循环
│   ├── knowledge_base.py      # ChromaDB + 分类检索
│   ├── tools.py               # 工具定义 + 并行执行
│   └── data/guizhou_kb.json   # 31 条种子知识
├── bot/
│   ├── base.py                # 适配器基类 + 统一消息格式
│   ├── handler.py             # 核心处理器（对接 Agent + 会话管理）
│   ├── telegram_bot.py        # Telegram 适配器
│   ├── feishu_bot.py          # 飞书适配器（Webhook + API）
│   ├── main.py                # 统一启动入口
│   ├── config.yaml            # 平台配置
│   └── README.md              # Bot 使用文档
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🐛 踩坑记录

### 字符串匹配 → 语义搜索
用户搜"Python 创造者是谁"，知识库写的是"Python 由 Guido van Rossum 创造"。
`in` 操作符匹配失败 → 换 BGE Embedding 语义搜索，召回率 40%→90%。

### Memory 裁剪拆散 tool_calls 配对
按单条消息裁剪时，保留了 `role: tool` 却丢了配对的 `tool_calls`，API 报 400。
→ 改为按"轮"裁剪（user 消息为边界），整轮全留或全丢。

### 流式输出静默失败
含 tool_calls 历史的对话用 stream=True 偶发空白。
→ try/except 兜底，流式失败自动切非流式。

### Docker 容器内连不上 Ollama
容器里 localhost 指向容器自身，Ollama 在宿主机。
→ 环境变量配置地址，Docker 内用 `host.docker.internal`。

### 用户说"好的"后 AI 重新生成 2000 字攻略
确认话术被当成"要新攻略"，LLM 把两条路线内容搞混。
→ 代码层拦截：上一轮是规划 + 短消息 = 直接锁定，不调 LLM。

---

## 🎓 技术要点

| 问题 | 答案 |
|---------|---------|
| Agent 和 LLM 区别？ | Agent 有工具调用+ReAct+Memory |
| RAG 怎么做？ | Embedding+ChromaDB+分类过滤+语义搜索 |
| Agentic RAG 是什么？ | Agent 自主决定搜不搜、搜几次、搜什么词 |
| 多平台 Bot 怎么设计？ | 适配器模式 + BaseChannel 统一接口 + 同步/异步桥接 |
| Memory 怎么管理？ | Token 计数+按轮裁剪+工具结果截断 |
| 遇到什么困难？ | 见踩坑记录 |

---

## 📊 技术栈

Python 3.12 · Streamlit · DeepSeek-Chat · Ollama BGE · ChromaDB · Docker · python-telegram-bot · aiohttp · Feishu Open API

---

*Built from scratch. No LangChain template. No if-else fake Agent.*
