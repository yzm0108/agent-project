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

BATCH_MAX_CHARS = 1000   # 粘贴直接输入的总字数上限，超出请走文件导入


def _decode_text(data: bytes) -> str:
    """上传文件解码：优先 UTF-8，失败回退 GBK（Windows 文本常见编码）"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace")


def _run_import(kb, raw_text: str, category: str) -> None:
    """执行批量导入并展示结果"""
    if not raw_text or not raw_text.strip():
        st.warning("没有可导入的内容")
        return
    if not category or not category.strip():
        st.warning("请选择或填写分类")
        return

    try:
        result = kb.import_texts(raw_text, category)
    except ValueError as e:
        st.warning(f"导入失败：{e}")
        return
    except Exception as e:
        st.error(f"导入失败：{type(e).__name__}: {e}")
        return

    if result["imported"] > 0:
        st.success(f"✅ 成功导入 {result['imported']} 条，知识库共 {kb.collection.count()} 条")

    notes = []
    if result["skipped_duplicate"]:
        notes.append(f"重复跳过 {result['skipped_duplicate']} 条")
    if result["skipped_short"]:
        notes.append(f"过短过滤 {result['skipped_short']} 条")
    if notes:
        st.info("；".join(notes))
    if result["imported"] == 0 and not notes:
        st.warning("未识别到有效条目，请检查内容是否用空行分隔")


def _format_tool_result(result) -> str:
    """把 tool_log 里的结果转成展示文本（兼容结构化 dict、字符串和空结果）"""
    if result is None:
        return "检索失败或工具暂不可用"
    if isinstance(result, list):
        if not result:
            return "未找到相关结果"
        if isinstance(result[0], dict):
            return "\n".join(
                f"[{r.get('category', '')}·{r.get('id', '')}] (相关度{r.get('score', '')}) {r.get('content', '')}"
                for r in result
            )
    return str(result)


CUSTOM_CATEGORY_OPTION = "＋ 自定义分类"


def _category_select(key: str, help: str = None) -> str:
    """分类选择：现有分类 + 自定义分类输入"""
    cats = list(kb.categories)
    options = cats + [CUSTOM_CATEGORY_OPTION]
    cat = st.selectbox("分类", options, key=key, help=help)
    if cat == CUSTOM_CATEGORY_OPTION:
        cat = st.text_input("自定义分类", key=f"{key}_custom").strip()
        if not cat:
            st.caption("⚠️ 请填写自定义分类名称")
    return cat


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
    tab_single, tab_batch = st.tabs(["单条添加", "批量导入"])

    with tab_single:
        new_cat = _category_select("single_cat")
        new_text = st.text_area("内容", placeholder="输入一条新知识...", key="new_kb")
        if st.button("添加到知识库", key="btn_single"):
            text = new_text.strip()
            if not text:
                st.warning("请输入内容")
            elif not new_cat.strip():
                st.warning("请选择或填写分类")
            else:
                try:
                    kb.add_document(text, new_cat)  # id 由 add_document 自动生成
                    st.success(f"已添加！知识库共 {kb.collection.count()} 条")
                    st.rerun()
                except ValueError as e:
                    st.warning(f"添加失败：{e}")
                except Exception as e:
                    st.error(f"添加失败：{type(e).__name__}: {e}")

    with tab_batch:
        batch_cat = _category_select("batch_cat",
                                     help="一个文件视为同一分类，请在导入前确认内容类型一致")
        batch_mode = st.radio("输入方式", ["粘贴文本", "上传文件"], horizontal=True,
                              key="batch_mode")
        if batch_mode == "粘贴文本":
            batch_text = st.text_area(
                "多条内容（空行分隔，空行数量随意）",
                placeholder="例如：\n黄果树瀑布位于安顺市...\n\n酸汤鱼是贵州苗族特色菜...",
                key="batch_text", height=160,
            )
            st.caption(f"{len(batch_text)} / {BATCH_MAX_CHARS} 字")
            if len(batch_text) > BATCH_MAX_CHARS:
                st.error(f"已超出 {BATCH_MAX_CHARS} 字上限，请删减或改用文件导入（本次未导入）")
            if st.button("导入", key="btn_batch_text"):
                if len(batch_text) > BATCH_MAX_CHARS:
                    st.error(f"超出 {BATCH_MAX_CHARS} 字上限，未导入，请删减或改用文件导入")
                else:
                    _run_import(kb, batch_text, batch_cat)
        else:
            uploaded = st.file_uploader("上传 .txt / .md 文件", type=["txt", "md"],
                                        key="batch_file")
            if st.button("导入", key="btn_batch_file"):
                if uploaded is None:
                    st.warning("请先选择文件")
                else:
                    content = _decode_text(uploaded.read())
                    _run_import(kb, content, batch_cat)

    st.divider()

    # 查看知识
    with st.expander("📖 浏览知识库", expanded=False):
        for d in kb.all_documents():
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
                    st.text(_format_tool_result(result)[:300])

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
                    st.text(_format_tool_result(result)[:300])

    # 保存到历史
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources,
        "tool_log": tool_log,
    })
