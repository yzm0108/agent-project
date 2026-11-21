"""
agent.py — Agentic RAG 核心循环
"""

import os
import json
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI
from tools import ToolExecutor, get_tool_definitions

load_dotenv()

MAX_STEPS = 6
MAX_TOKENS = 12000
encoder = tiktoken.get_encoding("cl100k_base")

SYSTEM_PROMPT = """你是「贵AI」——一个**专业、专注**的贵州旅游和文化智能助手。

【核心角色铁律】（必须严格遵守，优先级最高）
- 你**只**负责贵州旅游与文化相关的内容：景点推荐、美食、路线规划、交通、天气、住宿、民俗、文化体验、特产、旅行注意事项等。
- 你**绝不**回答任何与贵州旅游无关的问题，包括但不限于：写代码、调试程序、数学题、通用文章写作、编程问题、技术咨询、闲聊其他城市等。
- 如果用户提出无关请求，你必须用**友好且坚定**的语气拒绝，并主动引导回贵州旅游话题。

【用户确认处理铁律】（极其重要）
- 当用户说"好的""可以""就这个""不用改了""确定了"等确认性话语时，**绝对不要**重新生成完整攻略
- 此时应回复：确认当前方案已锁定 + 简要列出关键信息（2-3行）+ 询问下一步
- 只有用户明确说"重新规划""换一条""改XX""不要XX""我改变主意"时，才生成新方案
- 每次生成新方案时，使用版本号标记（方案V1、方案V2...），方便用户回溯

【回复长度控制】（严格遵守）
- 首次规划或重大修改：允许较长，但控制在 2000 字以内
- 确认类回复：严格控制在 500 字以内，只做总结+询问下一步
- 具体问答（天气、交通等）：控制在 200 字以内
- 任何回复都不要大段重复之前说过的内容，用"如前所述"带过

拒绝示例（请自然使用类似风格）：
- 「抱歉呀，我是贵州旅游助手贵AI，只擅长帮你规划贵州旅行。要不要我推荐一些贵州好玩的景点或美食呢？」
- 「这个我不太方便回答～我最在行的是贵州旅游相关的问题，你有什么贵州的行程疑问吗？」

【工作流程】（必须按此顺序执行）
1. 收到用户消息后，先判断是否与贵州旅游直接相关。
2. 如果完全无关，直接按上面拒绝模板回复，不要尝试解答。
3. 如果相关，则使用 search_guizhou 工具搜索知识库。
4. 基于搜索结果，用热情、专业、亲切的语气回答。
5. 如果信息不足，诚实告知用户并可以追问细节。

【回答风格要求】
- 语气：热情友好，像本地旅游顾问一样亲切。
- 结构：使用分点、编号、小标题，让回答清晰易读。
- 推荐景点/美食时，一定说明理由（为什么值得去）。
- 不要编造信息，所有内容必须基于搜索结果。
- 保持角色一致性，永远不要说"我其实也会……"之类打破角色的话。

记住：你是一个纯粹的贵州旅游助手，这是你的唯一身份。"""


def _tool_result_text(tool_name: str, result, query: str = "") -> str:
    """把工具执行结果转成给 LLM 的文本。

    search_guizhou 返回结构化 list[dict]，这里负责序列化与提示；
    其他工具返回字符串，原样透传。
    """
    if tool_name == "search_guizhou":
        if result is None:
            return "知识库检索暂时不可用，请稍后再试。"
        if not result:
            return f"知识库中未找到关于'{query}'的相关信息，建议换个关键词再搜。"
        return "\n".join(
            f"[{r['category']}·{r['id']}] (相关度{r['score']}) {r['content']}"
            for r in result
        )
    return result if isinstance(result, str) else str(result)


class GuizhouAgent:
    """贵州旅游 Agent"""

    def __init__(self, knowledge_base):
        self.llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL"),
        )
        self.executor = ToolExecutor(knowledge_base)
        self.kb = knowledge_base
        self.tool_defs = get_tool_definitions(self.kb.categories)

    def run(self, user_question, history=None, on_step=None, on_stream=None):
        if history is None:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        else:
            messages = list(history)

        messages.append({"role": "user", "content": user_question})

        tool_log = []
        sources = set()

        for step in range(1, MAX_STEPS + 1):
            if self._count_tokens(messages) > MAX_TOKENS:
                messages = self._trim_messages(messages)

            # LLM 调用（流式 + tools）
            resp = self.llm.chat.completions.create(
                model="deepseek-v4-flash",
                messages=messages,
                tools=self.tool_defs,
                timeout=30,
                extra_body={"thinking": {"type": "disabled"}},
            )
            msg = resp.choices[0].message

            # 不调工具 → 最终回答（流式输出）
            if msg.tool_calls is None:
                if on_step:
                    on_step(step, "done", None)

                if on_stream:
                    stream = self.llm.chat.completions.create(
                        model="deepseek-v4-flash",
                        messages=messages,
                        stream=True,
                        timeout=30,
                        extra_body={"thinking": {"type": "disabled"}},
                    )
                    full_answer = ""
                    try:
                        for chunk in stream:
                            if chunk.choices[0].delta.content:
                                token = chunk.choices[0].delta.content
                                full_answer += token
                                on_stream(token)
                    except Exception:
                        pass
                    if not full_answer:
                        full_answer = msg.content or ""
                        on_stream(full_answer)
                    messages.append({"role": "assistant", "content": full_answer})
                    return full_answer, tool_log, list(sources), messages
                else:
                    answer = msg.content or ""
                    messages.append({"role": "assistant", "content": answer})
                    return answer, tool_log, list(sources), messages

            # LLM 要求调工具
            if on_step:
                on_step(step, "thinking", [(tc.function.name, tc.function.arguments) for tc in msg.tool_calls])

            results = self.executor.execute_parallel(msg.tool_calls)

            # 存 assistant 消息（洗掉 XML 脏内容）
            clean = None
            if msg.content and "<|tool" not in msg.content and "<tool_calls>" not in msg.content:
                clean = msg.content

            messages.append({
                "role": "assistant",
                "content": clean,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            # 记录每个 tool_call 的参数（生成给 LLM 的提示文本需要 query）
            tool_args = {}
            for tc in msg.tool_calls:
                try:
                    tool_args[tc.id] = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except (json.JSONDecodeError, AttributeError):
                    tool_args[tc.id] = {}

            for tc_id, tool_name, result in results:
                args = tool_args.get(tc_id, {})
                text = _tool_result_text(tool_name, result, args.get("query", ""))
                short = text if len(text) <= 300 else text[:300] + "..."
                tool_log.append((step, tool_name, result))
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": short})

                if tool_name == "search_guizhou" and result:
                    for r in result:
                        if r.get("id"):
                            sources.add(r["id"])

                if on_step:
                    on_step(step, "tool_result", (tool_name, result))

        # 超出步数
        messages.append({"role": "user", "content": "请基于以上搜索结果给出完整回答。"})
        if on_stream:
            stream = self.llm.chat.completions.create(
                model="deepseek-v4-flash", messages=messages, stream=True,
                timeout=30, extra_body={"thinking": {"type": "disabled"}},
            )
            full_answer = ""
            try:
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        full_answer += token
                        on_stream(token)
            except Exception:
                pass
            if not full_answer:
                full_answer = "抱歉，生成回答时出现了问题，请再试一次。"
            messages.append({"role": "assistant", "content": full_answer})
            return full_answer, tool_log, list(sources), messages
        else:
            final = self.llm.chat.completions.create(model="deepseek-v4-flash", messages=messages,
                timeout=30, extra_body={"thinking": {"type": "disabled"}})
            answer = final.choices[0].message.content or ""
            messages.append({"role": "assistant", "content": answer})
            return answer, tool_log, list(sources), messages

    def _count_tokens(self, messages):
        total = 0
        for m in messages:
            content = m.get("content", "") or ""
            total += len(encoder.encode(content))
        return total

    def _trim_messages(self, messages):
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        rounds = []
        current = []
        for m in other_msgs:
            if m.get("role") == "user" and current:
                rounds.append(current)
                current = []
            current.append(m)
        if current:
            rounds.append(current)
        kept = []
        for r in reversed(rounds):
            r_tokens = sum(len(encoder.encode(m.get("content", "") or "")) for m in r)
            if self._count_tokens(system_msgs + sum(kept, []) + r) <= MAX_TOKENS:
                kept.insert(0, r)
            else:
                break
        trimmed = system_msgs + sum(kept, [])
        if len(messages) - len(trimmed) > 0:
            trimmed.insert(1, {"role": "system", "content": f"[已省略 {len(messages) - len(trimmed)} 条历史消息]"})
        return trimmed
