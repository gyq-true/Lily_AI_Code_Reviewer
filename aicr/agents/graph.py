"""LangGraph 多 Agent 编排：orchestrator → 并行专项 agent（Send map-reduce）→ synthesizer。"""

from __future__ import annotations

import asyncio
import operator
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from ..prompts import build_user_prompt, extract_json
from .specialists import SPECIALIST_BY_NAME, build_system, select_agents
from .synthesizer import merge_reports


class ReviewState(TypedDict, total=False):
    code: str
    filename: str
    language: str
    focus: list[str]
    kb_context: str
    is_diff: bool
    tasks: list[str]
    agent: str
    agent_reports: Annotated[list[dict[str, Any]], operator.add]
    final_report: dict[str, Any]


def _build_graph(provider, model: str | None, max_concurrency: int):
    sem = asyncio.Semaphore(max_concurrency)

    async def orchestrator(state: ReviewState) -> dict:
        return {"tasks": select_agents(state.get("focus") or [])}

    def dispatch(state: ReviewState) -> list[Send]:
        # LangGraph 的 Send 分支只接收 Send 载荷，需显式携带共享字段
        shared = {
            "code": state.get("code", ""),
            "filename": state.get("filename", ""),
            "language": state.get("language", ""),
            "kb_context": state.get("kb_context", ""),
            "is_diff": state.get("is_diff", False),
        }
        return [Send("agent", {**shared, "agent": name}) for name in state.get("tasks", [])]

    async def agent(state: ReviewState) -> dict:
        name = state["agent"]
        spec = SPECIALIST_BY_NAME[name]
        async with sem:
            system = build_system(
                spec,
                state.get("language", ""),
                state.get("kb_context", ""),
                state.get("is_diff", False),
            )
            user = build_user_prompt(
                state.get("code", ""), state.get("filename"), state.get("language")
            )
            text = await provider.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                model=model,
                json_mode=True,
            )
        report = extract_json(text) or {}
        return {"agent_reports": [{"agent": name, "report": report}]}

    def synthesizer(state: ReviewState) -> dict:
        return {"final_report": merge_reports(state.get("agent_reports", []))}

    graph = StateGraph(ReviewState)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("agent", agent)
    graph.add_node("synthesizer", synthesizer)
    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges("orchestrator", dispatch, ["agent"])
    graph.add_edge("agent", "synthesizer")
    graph.add_edge("synthesizer", END)
    return graph.compile()


async def run_multi_agent_review(
    *,
    code: str,
    filename: str | None = None,
    language: str | None = None,
    focus: list[str] | None = None,
    provider,
    model: str | None = None,
    kb_context: str = "",
    is_diff: bool = False,
    max_concurrency: int = 3,
) -> dict[str, Any]:
    """执行多 Agent 协作审查，返回统一报告（复用既有 report schema，issues 带 category 标签）。"""
    graph = _build_graph(provider, model, max_concurrency)
    initial: ReviewState = {
        "code": code,
        "filename": filename or "",
        "language": language or "",
        "focus": focus or [],
        "kb_context": kb_context,
        "is_diff": is_diff,
    }
    result = await graph.ainvoke(initial)
    return result["final_report"]
