"""
tools.py — 工具定义与并行执行
"""

import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 贵州各城市天气数据（模拟）
WEATHER_DB = {
    "贵阳": {"temperature": 23, "condition": "多云转晴", "humidity": "65%", "tip": "适合外出"},
    "遵义": {"temperature": 26, "condition": "晴天", "humidity": "55%", "tip": "注意防晒"},
    "安顺": {"temperature": 22, "condition": "阴天", "humidity": "70%", "tip": "可能下雨，建议带伞"},
    "黔东南": {"temperature": 24, "condition": "阵雨", "humidity": "80%", "tip": "记得带伞"},
    "黔南": {"temperature": 25, "condition": "多云", "humidity": "60%", "tip": "适合出游"},
    "毕节": {"temperature": 20, "condition": "小雨", "humidity": "75%", "tip": "温度偏低，带外套"},
    "铜仁": {"temperature": 27, "condition": "晴天", "humidity": "58%", "tip": "天气不错"},
    "六盘水": {"temperature": 19, "condition": "阴转多云", "humidity": "68%", "tip": "中国凉都，常年凉爽"},
}


# 工具实现

def search_guizhou(kb, query: str, category: str = None) -> str:
    """在贵州知识库中搜索信息，可指定分类过滤"""
    results = kb.search(query, top_k=3, category=category)
    if not results or results[0][0] < 0.2:
        return f"知识库中未找到关于'{query}'的相关信息，建议换个关键词再搜。"

    lines = []
    for sim, content, doc_id, cat in results:
        lines.append(f"[{cat}·{doc_id}] (相关度{sim}) {content}")

    return "\n".join(lines)


def get_weather(city: str) -> str:
    """查询贵州各城市天气"""
    info = WEATHER_DB.get(city)
    if not info:
        # 模糊匹配
        for key in WEATHER_DB:
            if city in key or key in city:
                info = WEATHER_DB[key]
                city = key
                break
    if not info:
        return f"暂不支持查询'{city}'的天气。目前支持：{', '.join(WEATHER_DB.keys())}"

    return (
        f"{city}天气：{info['condition']}，温度{info['temperature']}°C，"
        f"湿度{info['humidity']}。{info['tip']}。"
    )


def get_current_time() -> str:
    """获取当前日期时间"""
    return datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")


# 工具菜单（OpenAI Function Calling 格式）

def get_tool_definitions():
    """返回工具列表，供 Agent 传给 LLM"""
    return [
        {
            "type": "function",
            "function": {
                "name": "search_guizhou",
                "description": (
                    "在贵州知识库中搜索信息。知识库包含景点、美食、交通、天气、文化、特产 6 个分类。\n"
                    "- 尽量把用户问题拆成 1-3 个关键词再搜\n"
                    "- 如果搜索结果不够，换关键词再搜\n"
                    "- 可以指定 category 过滤：景点、美食、交通、天气、文化、特产\n"
                    "- 复杂问题请分多次搜索不同类别"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词，如'贵阳景点'、'酸汤鱼'"},
                        "category": {
                            "type": "string",
                            "enum": ["景点", "美食", "交通", "天气", "文化", "特产"],
                            "description": "可选，指定只搜某个分类",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询贵州省内各城市的实时天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名，如'贵阳'、'遵义'、'安顺'"},
                    },
                    "required": ["city"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "获取当前日期和时间",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


# 工具执行器

class ToolExecutor:
    """执行工具调用，支持并行"""

    def __init__(self, kb):
        self.kb = kb

    def execute_one(self, name: str, arguments: dict) -> str:
        """执行单个工具"""
        if name == "search_guizhou":
            return search_guizhou(self.kb, **arguments)
        elif name == "get_weather":
            return get_weather(**arguments)
        elif name == "get_current_time":
            return get_current_time()
        else:
            return f"未知工具：{name}"

    def execute_parallel(self, tool_calls) -> list:
        """
        并行执行多个工具调用，返回 [(tool_call_id, tool_name, result), ...]
        """
        # 先过滤掉不需要并行的情况——只有 1 个工具就串行
        if len(tool_calls) == 1:
            tc = tool_calls[0]
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            result = self.execute_one(tc.function.name, args)
            return [(tc.id, tc.function.name, result)]

        # 多个工具 → 线程池并行执行
        results = []

        def _run(tc):
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            return (tc.id, tc.function.name, self.execute_one(tc.function.name, args))

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_run, tc): tc for tc in tool_calls}
            for future in as_completed(futures):
                results.append(future.result())

        return results
