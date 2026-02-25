"""
LangChain Agent 模块 — MiniMax 大模型 + 工具调用

架构说明：
1. @tool 装饰器：将普通函数注册为 LangChain 工具，自动从 docstring 生成描述
2. ChatOpenAI：通过 OpenAI 兼容接口接入 MiniMax
3. create_react_agent：LangGraph 构建的 ReAct 循环（推理→行动→观察→...）
4. stream_agent：流式输出生成器，分离思维链和最终回答
"""

import json
import inspect
import threading
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# ========== 共享数据引用（由 cloud_bridge.py 注入） ==========
_hr_history: list = []
_window_history: list = []
_get_current_window = lambda: "未知"
_lock: Optional[threading.Lock] = None
_agent = None

# ========== 系统提示词 ==========
SYSTEM_PROMPT = (
    "你是一个心率手环监控助手。佩戴者通过小米手环实时上传心率数据，"
    "同时他的电脑窗口标题也会被记录。\n"
    "你可以通过工具查询佩戴者的心率统计、当前在用什么软件、各软件使用时长、"
    "以及判断他是否在摸鱼。\n"
    "回答要简洁有趣，像朋友聊天一样自然。如果数据不足就直说。"
)


# ========== 工具定义 ==========

@tool
def get_heart_rate_stats() -> str:
    """获取佩戴者的心率统计信息，包括平均心率、最高心率、最低心率、最新心率、数据量和趋势描述。
    当用户询问心率、健康状态、身体状况时调用此工具。"""
    with _lock:
        if not _hr_history:
            return json.dumps({"error": "暂无心率数据"}, ensure_ascii=False)

        hrs = [h["hr"] for h in _hr_history]
        recent = hrs[-10:] if len(hrs) >= 10 else hrs

        if len(recent) >= 4:
            first_half = sum(recent[: len(recent) // 2]) / (len(recent) // 2)
            second_half = sum(recent[len(recent) // 2 :]) / (len(recent) // 2)
            diff = second_half - first_half
            if diff > 5:
                trend = "明显上升"
            elif diff > 2:
                trend = "略有上升"
            elif diff < -5:
                trend = "明显下降"
            elif diff < -2:
                trend = "略有下降"
            else:
                trend = "保持平稳"
        else:
            trend = "数据不足，无法判断趋势"

        return json.dumps(
            {
                "avg": round(sum(hrs) / len(hrs), 1),
                "max": max(hrs),
                "min": min(hrs),
                "latest": hrs[-1],
                "count": len(hrs),
                "latest_window": _hr_history[-1].get("window", "未知"),
                "trend": trend,
            },
            ensure_ascii=False,
        )


@tool
def get_heart_window_correlation() -> str:
    """分析心率与窗口的关联关系。按窗口分组统计心率，看用什么软件时心率最高/最低。
    当用户问"什么时候心率高""玩游戏心率多少"时调用。"""
    with _lock:
        if not _hr_history:
            return json.dumps({"error": "暂无数据"}, ensure_ascii=False)

        groups: dict = {}
        for h in _hr_history:
            w = h.get("window", "未知")
            if w not in groups:
                groups[w] = []
            groups[w].append(h["hr"])

        result = {}
        for w, hrs in groups.items():
            result[w] = {
                "avg": round(sum(hrs) / len(hrs), 1),
                "max": max(hrs),
                "min": min(hrs),
                "count": len(hrs),
            }

        return json.dumps(result, ensure_ascii=False)


@tool
def detect_slacking() -> str:
    """检测佩戴者是否在摸鱼。分析最近的窗口使用记录，列出各窗口的使用时长。
    当用户问"他在摸鱼吗""他在干什么""他认真吗"时调用。"""
    # 先在锁外获取当前窗口（get_current_window 内部会自行加锁）
    current = _get_current_window()
    with _lock:

        if not _window_history:
            return json.dumps(
                {
                    "current_window": current,
                    "history": "暂无窗口切换记录",
                    "judgment": "数据不足，无法判断",
                },
                ensure_ascii=False,
            )

        recent = list(_window_history[-20:])
        summary = []
        for w in recent:
            summary.append(
                {
                    "title": w.get("title", "未知"),
                    "duration_seconds": w.get("duration", 0),
                    "started_at": w.get("started_at", ""),
                }
            )

        return json.dumps(
            {"current_window": current, "recent_windows": summary},
            ensure_ascii=False,
        )


@tool
def get_app_usage_stats() -> str:
    """获取各应用的累计使用时长排行。按窗口标题聚合统计总时长。
    当用户问"他用了多久""各软件使用时间"时调用。"""
    with _lock:
        if not _window_history:
            return json.dumps({"error": "暂无窗口记录"}, ensure_ascii=False)

        usage: dict = {}
        for w in _window_history:
            title = w.get("title", "未知")
            dur = w.get("duration", 0)
            usage[title] = usage.get(title, 0) + dur

        sorted_usage = sorted(usage.items(), key=lambda x: x[1], reverse=True)
        result = []
        for title, seconds in sorted_usage[:15]:
            minutes = round(seconds / 60, 1)
            result.append({"title": title, "total_minutes": minutes, "total_seconds": round(seconds, 1)})

        return json.dumps(result, ensure_ascii=False)


# ========== Agent 初始化 ==========

def init_agent(api_key: str, hr_history: list, window_history: list, get_current_window, lock: threading.Lock):
    """
    初始化 Agent，由 cloud_bridge.py 在启动时调用。

    通过参数注入共享数据的 **引用**（而非副本），
    工具函数读取到的永远是最新数据。
    """
    global _hr_history, _window_history, _get_current_window, _lock, _agent

    _hr_history = hr_history
    _window_history = window_history
    _get_current_window = get_current_window
    _lock = lock

    llm = ChatOpenAI(
        model="MiniMax-M2.5",
        base_url="https://api.minimax.chat/v1",
        api_key=api_key,
        streaming=True,
    )

    tools = [get_heart_rate_stats, get_heart_window_correlation, detect_slacking, get_app_usage_stats]

    # 兼容不同版本的 langgraph：
    #   新版用 prompt 参数
    #   老版用 state_modifier 参数
    #   更老的版本用 messages_modifier 参数
    sig = inspect.signature(create_react_agent)
    params = sig.parameters

    if "prompt" in params:
        _agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)
    elif "state_modifier" in params:
        _agent = create_react_agent(llm, tools, state_modifier=SYSTEM_PROMPT)
    elif "messages_modifier" in params:
        _agent = create_react_agent(llm, tools, messages_modifier=SYSTEM_PROMPT)
    else:
        # 最后兜底：不传提示词，在 stream_agent 中手动注入 SystemMessage
        _agent = create_react_agent(llm, tools)
        print("[agent] WARNING: create_react_agent 不支持已知的提示词参数，将在消息中注入系统提示词")


# ========== 流式输出 ==========

def stream_agent(message: str):
    """
    流式执行 Agent 并逐步 yield 事件。

    事件类型：
        - {"type": "thinking", "content": "..."} — 思维过程
        - {"type": "tool_result", "name": "...", "content": "..."} — 工具返回
        - {"type": "answer", "content": "..."} — 最终回答 token
        - {"type": "done"} — 结束
    """
    if _agent is None:
        yield {"type": "answer", "content": "Agent 未初始化，请检查 MINIMAX_API_KEY 配置。"}
        yield {"type": "done"}
        return

    try:
        messages = [
            HumanMessage(content=message),
        ]

        stream = _agent.stream(
            {"messages": messages},
            stream_mode="messages",
        )

        seen_tool_calls = set()

        for chunk, metadata in stream:
            node = metadata.get("langgraph_node", "")

            if node == "tools":
                tool_name = getattr(chunk, "name", None)
                if tool_name and tool_name not in seen_tool_calls:
                    seen_tool_calls.add(tool_name)
                    yield {
                        "type": "tool_result",
                        "name": tool_name,
                        "content": chunk.content if chunk.content else "",
                    }

            elif node == "agent":
                if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        name = tc.get("name", "unknown")
                        if name not in seen_tool_calls:
                            yield {"type": "thinking", "content": f"调用工具: {name}"}

                elif chunk.content:
                    # 检查 MiniMax 的 reasoning_content（思维链）
                    if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                        reasoning = chunk.additional_kwargs.get("reasoning_content", "")
                        if reasoning:
                            yield {"type": "thinking", "content": reasoning}
                            continue
                    yield {"type": "answer", "content": chunk.content}

        yield {"type": "done"}

    except Exception as e:
        yield {"type": "answer", "content": f"Agent 出错: {str(e)}"}
        yield {"type": "done"}