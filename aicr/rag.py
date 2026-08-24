"""RAG 检索：把审查目标代码转为查询，从知识库召回相关上下文并格式化为提示词片段。"""

from __future__ import annotations

from typing import Any

from .context import estimate_tokens, truncate_for_query


def build_query(filename: str | None, code: str, focus: list[str]) -> str:
    """构造检索查询：文件名 + 关注点 + 代码片段（截断）。"""
    focus_text = " ".join(focus) or ""
    head = f"{filename or ''} {focus_text}".strip()
    body = truncate_for_query(code or "")
    return f"{head}\n{body}".strip() or "代码审查"


def retrieve_context(store, embedder, query: str, top_k: int) -> list[dict[str, Any]]:
    """检索 top_k 相关片段。store/embedder 为 None 时返回空。"""
    if store is None or embedder is None or not query:
        return []
    vector = embedder.embed([query])[0]
    return store.search(vector, top_k=top_k)


def format_context(chunks: list[dict[str, Any]], *, max_chars: int = 4000) -> str:
    """把检索结果格式化为可注入提示词的项目上下文块。"""
    if not chunks:
        return ""
    from .context import fit_to_budget

    header = "以下是来自本项目知识库的检索结果（供审查时对照的项目规范/架构/相关代码）："
    return fit_to_budget(chunks, max_chars=max_chars, header=header)


def context_stats(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """返回检索上下文的元信息，便于落盘与展示。"""
    return {
        "count": len(chunks),
        "tokens": estimate_tokens(format_context(chunks, max_chars=4000)),
        "sources": [
            (ch.get("payload") or {}).get("source", "unknown") for ch in chunks
        ],
    }
