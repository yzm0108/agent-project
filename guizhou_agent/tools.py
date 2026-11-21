"""
tools.py — 工具定义与并行执行
"""
import json
import os
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from dotenv import load_dotenv

import requests

load_dotenv()
logger = logging.getLogger("guizhou_agent")
_GAODE_KEY = os.getenv("GAODE_API_KEY", "")

WEATHER_FALLBACK = {
    "贵阳":     {"temperature": 23, "condition": "多云转晴", "humidity": "65%", "tip": "适合外出"},
    "遵义":     {"temperature": 26, "condition": "晴天",     "humidity": "55%", "tip": "注意防晒"},
    "安顺":     {"temperature": 22, "condition": "阴天",     "humidity": "70%", "tip": "可能下雨，建议带伞"},
    "黔东南":   {"temperature": 24, "condition": "阵雨",     "humidity": "80%", "tip": "记得带伞"},
    "黔南":     {"temperature": 25, "condition": "多云",     "humidity": "60%", "tip": "适合出游"},
    "毕节":     {"temperature": 20, "condition": "小雨",     "humidity": "75%", "tip": "温度偏低，带外套"},
    "铜仁":     {"temperature": 27, "condition": "晴天",     "humidity": "58%", "tip": "天气不错"},
    "六盘水":   {"temperature": 19, "condition": "阴转多云", "humidity": "68%", "tip": "中国凉都，常年凉爽"},
}

CACHE_TTL_SECONDS = 30 * 60
_weather_cache: dict[str, tuple[float, dict]] = {}
_stats: list[dict] = []


def _fetch_from_api(city: str, timeout: float = 5.0) -> dict | None:
    """从高德天气 API 获取实时天气，失败返回 None"""
    try:
        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {"city": city, "key": _GAODE_KEY, "extensions": "base"}
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1" or not data.get("lives"):
            return None

        live = data["lives"][0]
        return {
            "temperature": int(live.get("temperature", 0)),
            "condition":   live.get("weather", "未知"),
            "humidity":    str(live.get("humidity", "N/A")) + "%",
            "tip":         "",
        }
    except Exception:
        return None


def _generate_tip(condition: str, temperature: int) -> str:
    t = temperature
    if "雨" in condition:
        if "大" in condition or "暴" in condition:
            return "大雨天气，尽量避免外出"
        return "记得带伞"
    if "雪" in condition:
        return "注意防滑保暖"
    if "雷" in condition:
        return "可能有雷阵雨，注意安全"
    if "雾" in condition or "霾" in condition:
        return "能见度低，出行注意安全"
    if t > 32:
        return "高温天气，注意防暑降温"
    if t < 10:
        return "温度偏低，记得带外套"
    if ("晴" in condition or "多云" in condition) and 20 <= t <= 30:
        return "适合出游"
    if "阴" in condition or "云" in condition:
        return "适合外出"
    if "凉" in condition:
        return "中国凉都，常年凉爽"
    return ""


def _get_from_cache(city: str) -> dict | None:
    entry = _weather_cache.get(city)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > CACHE_TTL_SECONDS:
        del _weather_cache[city]
        return None
    return data


def _put_to_cache(city: str, data: dict) -> None:
    _weather_cache[city] = (time.time(), data)


def _log_call(city: str, source: str, elapsed_ms: float, success: bool) -> None:
    _stats.append({
        "timestamp": datetime.now().isoformat(),
        "city": city,
        "source": source,
        "elapsed_ms": round(elapsed_ms, 1),
        "success": success,
    })
    while len(_stats) > 500:
        _stats.pop(0)


def _resolve_city(city: str) -> str | None:
    if city in WEATHER_FALLBACK:
        return city
    for key in WEATHER_FALLBACK:
        if city in key or key in city:
            return key
    return None


def get_weather(city: str) -> str:
    t0 = time.perf_counter()
    resolved = _resolve_city(city)
    if resolved is None:
        elapsed = (time.perf_counter() - t0) * 1000
        _log_call(city, "none", elapsed, False)
        return f"暂不支持查询'{city}'的天气。目前支持：{', '.join(WEATHER_FALLBACK.keys())}"

    info: dict | None = None
    source: str = ""

    info = _fetch_from_api(resolved)
    if info is not None:
        source = "api"
        info["tip"] = _generate_tip(info["condition"], info["temperature"])
        _put_to_cache(resolved, info)
    else:
        info = _get_from_cache(resolved)
        if info is not None:
            source = "cache"
        else:
            info = dict(WEATHER_FALLBACK[resolved])
            source = "fallback"

    elapsed = (time.perf_counter() - t0) * 1000
    _log_call(resolved, source, elapsed, True)

    freshness = ""
    if source == "cache":
        freshness = "（缓存数据，30分钟内更新）"
    elif source == "fallback":
        freshness = "（⚠️ 非实时数据，未能获取最新天气）"

    return (
        f"{resolved}天气：{info['condition']}，温度{info['temperature']}°C，"
        f"湿度{info['humidity']}。{info['tip']}。{freshness}"
    )


def get_weather_stats() -> str:
    if not _stats:
        return "暂无天气调用记录。"

    total = len(_stats)
    success = sum(1 for s in _stats if s["success"])
    sources = {"api": 0, "cache": 0, "fallback": 0}
    for s in _stats:
        src = s.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    avg_ms = sum(s["elapsed_ms"] for s in _stats) / total if total else 0

    return (
        f"天气服务统计（共 {total} 次调用）：\n"
        f"- 成功率：{success}/{total}（{success/total*100:.1f}%）\n"
        f"- 数据来源：API {sources['api']} 次 | 缓存 {sources['cache']} 次 | 兜底 {sources['fallback']} 次\n"
        f"- 平均耗时：{avg_ms:.0f}ms\n"
        f"- 兜底率（API 不可用时兜住了）：{sources['fallback']/total*100:.1f}%"
    )


RELEVANCE_THRESHOLD = 0.2   # 相关度低于此值的条目不返回
DEFAULT_TOP_K = 5           # 粗取 5 条再过滤，保证过滤后仍有足够信息


def search_guizhou(kb, query: str, category: str = None,
                   top_k: int = DEFAULT_TOP_K, min_score: float = RELEVANCE_THRESHOLD) -> list[dict] | None:
    """在贵州知识库中搜索信息，返回结构化结果 list[dict]（id/content/score/category）。

    展示/提示文本由上层生成，本函数只负责检索与过滤：
    - 检索失败返回 None（不抛异常）
    - 无命中返回 []（含：全低于阈值、指定分类搜不到且全库也搜不到）
    - 指定分类搜不到时自动放宽到全库，防 Agent 猜错分类漏召回
    """
    def _search(cat):
        try:
            return kb.search(query, top_k=top_k, category=cat)
        except Exception:
            return None

    results = _search(category)
    if results is None:
        return None

    hits = [r for r in results if r["score"] >= min_score]

    # 指定分类搜不到 → 放宽到全库，防 Agent 猜错分类漏召回
    if not hits and category:
        results = _search(None)
        if results is not None:
            hits = [r for r in results if r["score"] >= min_score]

    return hits


def get_current_time() -> str:
    """获取当前日期时间"""
    return datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")


DEFAULT_CATEGORIES = ["景点", "美食", "交通", "天气", "文化", "特产"]


def get_tool_definitions(categories: list | None = None):
    """返回工具列表，供 Agent 传给 LLM。categories 传入当前知识库分类（含自定义）。"""
    if not categories:
        categories = DEFAULT_CATEGORIES
    cats_text = "、".join(categories)

    return [
        {
            "type": "function",
            "function": {
                "name": "search_guizhou",
                "description": (
                    f"在贵州知识库中搜索信息。知识库包含 {len(categories)} 个分类：{cats_text}。\n"
                    "- 尽量把用户问题拆成 1-3 个关键词再搜\n"
                    "- 如果搜索结果不够，换关键词再搜\n"
                    "- category 可选：确定内容属于某个分类时才指定；不确定时不要指定，直接搜整个知识库\n"
                    "- 复杂问题请分多次搜索不同类别"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词，如'贵阳景点'、'酸汤鱼'"},
                        "category": {
                            "type": "string",
                            "enum": list(categories),
                            "description": "可选，指定只搜某个分类；不确定内容归属时不要指定，直接搜整个知识库",
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
                "description": "查询贵州城市实时天气。仅支持 8 个城市：贵阳、遵义、安顺、黔东南、黔南、毕节、铜仁、六盘水。不在列表中的城市无法查询，不要承诺。自动从气象 API 获取最新数据，API 不可用时降级到本地缓存。",
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


def _parse_tool_args(raw: str | None) -> dict:
    """解析 LLM 返回的工具参数；非法 JSON / 非 dict 统一返回空 dict。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


class ToolExecutor:

    def __init__(self, kb):
        self.kb = kb

    def execute_one(self, name: str, arguments: dict) -> list[dict] | str | None:
        """执行单个工具。

        返回约定：
        - search_guizhou: list[dict]（检索结果）或 None（检索失败）
        - get_weather / get_current_time: str
        - 未知工具 / 参数错误 / 执行异常: str（交给 LLM 兜底，不打断主循环）
        """
        if not isinstance(arguments, dict):
            return f"工具 {name} 参数格式错误：{arguments!r}"
        try:
            if name == "search_guizhou":
                return search_guizhou(self.kb, **arguments)
            elif name == "get_weather":
                return get_weather(**arguments)
            elif name == "get_current_time":
                return get_current_time()
            else:
                return f"未知工具：{name}"
        except Exception as e:
            return f"工具 {name} 执行失败：{type(e).__name__}: {e}"

    def execute_parallel(self, tool_calls) -> list:
        if len(tool_calls) == 1:
            tc = tool_calls[0]
            args = _parse_tool_args(tc.function.arguments)
            result = self.execute_one(tc.function.name, args)
            return [(tc.id, tc.function.name, result)]

        results = []

        def _run(tc):
            args = _parse_tool_args(tc.function.arguments)
            return (tc.id, tc.function.name, self.execute_one(tc.function.name, args))

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_run, tc): tc for tc in tool_calls}
            for future in as_completed(futures):
                results.append(future.result())

        return results
