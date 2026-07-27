"""
app.py — 贵AI：贵州旅游智能助手
启动：cd guizhou_agent && streamlit run app.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from knowledge_base import KnowledgeBase
from agent import GuizhouAgent

st.set_page_config(
    page_title="贵AI - 贵州旅游助手",
    page_icon="🏔️",
    layout="wide",
)

@st.cache_resource
def load_kb():
    return KnowledgeBase()


kb = load_kb()
agent = GuizhouAgent(kb)

col1, col2 = st.columns([3, 1])
with col1:
    st.title("🏔️ 贵AI — 贵州旅游智能助手")
    st.caption("问景点、查美食、看天气、做攻略。基于 Agentic RAG，自主搜索知识库，诚实回答。")
with col2:
    st.metric("📚 知识库", f"{kb.collection.count()} 条", f"{len(kb.categories)} 个分类")

with st.sidebar:
    st.header("⚙️ 控制面板")

    # 分类统计
    st.subheader("知识库分类")
    for cat, count in kb.get_by_category().items():
        st.text(f"  {cat}: {count} 条")

    st.divider()

    # 添加知识
    st.subheader("✏️ 添加新知识")
    new_cat = st.selectbox("分类", kb.categories)
    new_text = st.text_area("内容", placeholder="输入一条新知识...", key="new_kb")
    if st.button("添加到知识库"):
        if new_text.strip():
            new_id = f"user_{kb.collection.count()}"
            full_text = new_text.strip()
            emb = kb._embed(full_text)
            kb.collection.add(
                ids=[new_id],
                documents=[full_text],
                embeddings=[emb],
                metadatas=[{"category": new_cat}],
            )
            # 同时更新内存中的 documents
            kb.documents.append({"id": new_id, "category": new_cat, "content": full_text})
            st.success(f"已添加！知识库共 {kb.collection.count()} 条")
            st.rerun()
        else:
            st.warning("请输入内容")

    st.divider()

    # 查看知识
    with st.expander("📖 浏览知识库", expanded=False):
        for d in kb.documents:
            st.caption(f"**[{d['category']}]** {d['content'][:80]}...")
            st.divider()

    st.divider()
    if st.button("🗑️ 清除对话记忆"):
        st.session_state.conversation = []
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.caption("💡 试试问：")
    st.caption("- 贵阳三天两夜怎么玩？")
    st.caption("- 贵州有什么必吃的美食？")
    st.caption("- 今天贵阳天气怎么样？")
    st.caption("- 黄果树瀑布怎么去？")

if "messages" not in st.session_state:
    st.session_state.messages = []  # 前端展示用
if "conversation" not in st.session_state:
    st.session_state.conversation = []  # Agent 的跨轮记忆（messages 格式）

for msg in st.session_state.messages:
    role = msg["role"]
    with st.chat_message(role):
        st.markdown(msg.get("content", ""))

        sources = msg.get("sources", [])
        if sources and role == "assistant":
            source_texts = []
            for sid in sources[:5]:
                doc = kb.get_doc_by_id(sid)
                if doc:
                    source_texts.append(f"[{doc['category']}] {doc['content'][:50]}...")
            if source_texts:
                with st.expander("📎 信息来源", expanded=False):
                    for s in source_texts:
                        st.caption(f"• {s}")

        tool_log = msg.get("tool_log", [])
        if tool_log:
            with st.expander("🔍 Agent 搜索过程", expanded=False):
                for step, tool_name, result in tool_log:
                    st.caption(f"**第{step}步 · {tool_name}**")
                    st.text(result[:300])

if prompt := st.chat_input("问一个关于贵州的问题..."):
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Agent 运行
    steps_display = []

    def collect_step(step, step_type, data):
        """回调：实时更新搜索状态"""
        if step_type == "thinking":
            # data = [(tool_name, args_json), ...]
            names = [t[0] for t in data]
            status.update(label=f"🔍 第{step}步：Agent 决定调用 {', '.join(names)}")
        elif step_type == "tool_result":
            tool_name, result = data
            status.update(label=f"✅ 第{step}步：{tool_name} 执行完成")
        elif step_type == "done":
            status.update(label="✍️ 正在生成回答...")
        steps_display.append((step, step_type, data))

    with st.chat_message("assistant"):
        # 搜索期间显示"思考中..."，防止显示 raw tool_call XML
        status = st.status("🔍 正在搜索知识库...", expanded=True)
        answer_placeholder = st.empty()
        answer_placeholder.markdown("🤔 *正在思考...*")

        streamed = [""]

        def on_stream(token):
            streamed[0] += token
            answer_placeholder.markdown(streamed[0] + "▌")

        answer, tool_log, sources, conversation = agent.run(
            prompt,
            history=st.session_state.conversation,
            on_step=collect_step,
            on_stream=on_stream,
        )
        st.session_state.conversation = conversation

        status.update(label=f"✅ 完成（{len(tool_log)} 次搜索）", state="complete", expanded=False)
        answer_placeholder.markdown(answer)

        # 搜索完成，更新状态
        status.update(label=f"✅ 搜索完成（共 {len(tool_log)} 次工具调用）", state="complete", expanded=False)

        if sources:
            source_texts = []
            for sid in sources[:5]:
                doc = kb.get_doc_by_id(sid)
                if doc:
                    source_texts.append(f"[{doc['category']}] {doc['content'][:60]}...")
            if source_texts:
                with st.expander("📎 信息来源", expanded=True):
                    for s in source_texts:
                        st.caption(f"• {s}")

        if tool_log:
            with st.expander("🔍 Agent 搜索过程", expanded=False):
                for step, tool_name, result in tool_log:
                    st.caption(f"**第{step}步 · {tool_name}**")
                    st.text(result[:300])

    # 保存到历史
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources,
        "tool_log": tool_log,
    })
