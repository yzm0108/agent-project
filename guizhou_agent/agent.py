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


class GuizhouAgent:
    """贵州旅游 Agent"""

    def __init__(self, knowledge_base):
        self.llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL"),
        )
        self.executor = ToolExecutor(knowledge_base)
        self.kb = knowledge_base
        self.tool_defs = get_tool_definitions()

    def run(self, user_question, history=None, on_step=None, on_stream=None):
        if history is None:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        else:
            messages = list(history)

        # 确认锁定：用户说确认话术时跳过 LLM 调用，直接返回锁定结果
        shortcut = self._maybe_confirm_choice(history, user_question)
        if shortcut:
            messages.append({"role": "user", "content": user_question})
            messages.append({"role": "assistant", "content": shortcut})
            return shortcut, [], [], messages

        messages.append({"role": "user", "content": user_question})

        tool_log = []
        sources = set()

        for step in range(1, MAX_STEPS + 1):
            if self._count_tokens(messages) > MAX_TOKENS:
                messages = self._trim_messages(messages)

            # LLM 调用（流式 + tools）
            resp = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                tools=self.tool_defs,
            )
            msg = resp.choices[0].message

            # 不调工具 → 最终回答（流式输出）
            if msg.tool_calls is None:
                if on_step:
                    on_step(step, "done", None)

                if on_stream:
                    stream = self.llm.chat.completions.create(
                        model="deepseek-chat",
                        messages=messages,
                        stream=True,
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
      
            for tc_id, tool_name, result in results:
                short = result if len(result) <= 300 else result[:300] + "..."
                tool_log.append((step, tool_name, result))
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": short})

                if tool_name == "search_guizhou":
                    for line in result.split("\n"):
                        if "·" in line and "]" in line:
                            try:
                                sources.add(line.split("·")[1].split("]")[0].strip())
                            except (IndexError, ValueError):
                                pass

                if on_step:
                    on_step(step, "tool_result", (tool_name, result))

        # 超出步数
        messages.append({"role": "user", "content": "请基于以上搜索结果给出完整回答。"})
        if on_stream:
            stream = self.llm.chat.completions.create(
                model="deepseek-chat", messages=messages, stream=True
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
            final = self.llm.chat.completions.create(model="deepseek-chat", messages=messages)
            answer = final.choices[0].message.content or ""
            messages.append({"role": "assistant", "content": answer})
            return answer, tool_log, list(sources), messages

    def _count_tokens(self, messages):
        total = 0
        for m in messages:
            content = m.get("content", "") or ""
            total += len(encoder.encode(content))
        return total

    def _has_pending_options(self, history):
        """检查上一轮 AI 是否给了多个方案需要用户选择"""
        if not history:
            return False
        # 取最后一条 assistant 消息
        last_assistant = ""
        for m in reversed(history):
            if m.get("role") == "assistant" and m.get("content"):
                last_assistant = m["content"]
                break
        if not last_assistant:
            return False
        # 检测多方案标记
        import re
        patterns = [
            r'方案\s*[A-Z一二三四五]',   # 方案A、方案一
            r'选项\s*\d',                 # 选项1
            r'推荐方案[一二三四五]',       # 推荐方案一
            r'第\s*[一二三]\s*[个种]',    # 第一个、第二种
            r'路线\s*[A-Z]',              # 路线A
        ]
        return any(re.search(p, last_assistant) for p in patterns)

    def _last_assistant_was_plan(self, history):
        """上一轮 AI 是否给了行程规划（而不是纯问答）"""
        if not history:
            return False
        for m in reversed(history):
            if m.get("role") == "assistant" and m.get("content"):
                content = m["content"]
                # 含行程规划关键词
                plan_keywords = ["Day", "第", "天", "行程", "方案", "规划", "路线", "攻略",
                                 "黄果树", "荔波", "苗寨", "贵阳", "景点", "住宿", "交通"]
                return any(kw in content for kw in plan_keywords)
        return False

    def _maybe_confirm_choice(self, history, user_input):
        """上一轮是规划 + 用户回复短且不像新问题 → 确认锁定"""
        if not history:
            return None
        if not self._last_assistant_was_plan(history):
            return None

        msg = user_input.strip()

        # 是新问题？（含疑问词 或 问号 或 很长）→ 放行给 LLM
        question_words = ["什么", "怎么", "哪里", "哪个", "如何", "多少", "多久", "多远", "?"]
        if any(w in msg for w in question_words) or len(msg) > 15:
            return None

        # 是修改请求？→ 放行
        modify_words = ["改", "换", "不要", "别", "不想要", "去掉", "取消", "重新"]
        if any(w in msg for w in modify_words):
            return None

        # 其余都算确认
        return (
            "好的，方案已锁定！✅\n\n"
            "接下来我可以帮你：\n"
            "1. 📋 生成详细行程清单（每天几点去哪、吃什么、住哪里）\n"
            "2. 🏨 推荐具体酒店/民宿\n"
            "3. 🚗 查交通（高铁时刻、大巴班次）\n"
            "4. 🌤️ 查出行日期的天气\n\n"
            "你想让我帮你做哪个？或者还有其他想调整的吗？"
        )

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
