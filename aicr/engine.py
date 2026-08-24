"""审查引擎：编排 provider 调用、结果校验、工件落盘。"""

from __future__ import annotations

import time
from typing import Any

from . import runs
from .config import load_config
from .prompts import VALID_SEVERITIES, build_system_prompt, build_user_prompt, extract_json
from .providers import BaseProvider, ProviderError, build_provider


class EngineError(ProviderError):
    pass


def validate_result(raw: Any) -> dict[str, Any]:
    """清洗模型输出：字段兜底 + 评分钳制 + 严重级别白名单。"""
    if not isinstance(raw, dict):
        raise EngineError("模型返回的审查结果不是有效 JSON", 502, "BAD_RESULT")

    issues: list[dict[str, Any]] = []
    for item in raw.get("issues") or []:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity")
        issues.append(
            {
                "severity": severity if severity in VALID_SEVERITIES else "minor",
                "title": str(item.get("title") or "未命名问题"),
                "line": item.get("line") if isinstance(item.get("line"), int) else None,
                "description": str(item.get("description") or ""),
                "suggestion": str(item.get("suggestion") or ""),
                "code": item.get("code") if isinstance(item.get("code"), str) else None,
                "category": str(item.get("category") or ""),
            }
        )

    raw_score = raw.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        score = 0
    else:
        score = max(0, min(100, int(raw_score)))

    return {
        "summary": str(raw.get("summary") or "（模型未返回摘要）"),
        "score": max(0, min(100, score)),
        "highlights": [h for h in (raw.get("highlights") or []) if isinstance(h, str)],
        "issues": issues,
        "recommendations": [r for r in (raw.get("recommendations") or []) if isinstance(r, str)],
        "issueCount": len(issues),
        "agents": [a for a in (raw.get("agents") or []) if isinstance(a, str)],
    }


async def run_review(
    *,
    code: str,
    filename: str | None = None,
    language: str | None = None,
    focus: list[str] | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    is_diff: bool = False,
    save_artifacts: bool = True,
    provider: BaseProvider | None = None,
    kb_enabled: bool | None = None,
    kb_store=None,
    kb_embedder=None,
    mode: str | None = None,
) -> dict[str, Any]:
    """执行一次审查并落盘运行工件。provider/kb_store/kb_embedder 参数用于测试注入。"""
    from .collector import guess_language

    settings = load_config()
    prov = provider or build_provider(settings, provider_name)
    resolved_model = model or prov.default_model
    focus_list = [f for f in (focus or [])]
    language = language or guess_language(filename)
    use_kb = settings.kb_enabled if kb_enabled is None else kb_enabled
    use_multi = (mode or settings.review_mode) == "multi"

    run = runs.RunTrace(runs.new_run_id()) if save_artifacts else None
    started = time.time()
    if run:
        run.init_meta(
            filename=filename,
            language=language,
            provider=prov.name,
            model=resolved_model,
            focus=focus_list,
            line_count=len(code.splitlines()),
            code_bytes=len(code.encode("utf-8")),
            kb_enabled=use_kb,
            review_mode="multi" if use_multi else "single",
        )

    kb_context = ""
    if use_kb:
        try:
            from .knowledge import build_embedder, build_store
            from .rag import build_query, format_context, retrieve_context

            store = kb_store or build_store(settings)
            embedder = kb_embedder or build_embedder(settings)
            query = build_query(filename, code, focus_list)
            chunks = retrieve_context(store, embedder, query, settings.kb_top_k)
            kb_context = format_context(chunks, max_chars=settings.kb_chunk_size * 5)
            if run:
                run.event("kb_retrieved", count=len(chunks), query_chars=len(query))
        except Exception as err:  # noqa: BLE001 - 知识库异常不阻断审查
            if run:
                run.event("kb_skipped", reason=str(err)[:200])

    messages = [
        {
            "role": "system",
            "content": build_system_prompt(language or "", focus_list, is_diff, kb_context),
        },
        {"role": "user", "content": build_user_prompt(code, filename, language)},
    ]

    try:
        if run:
            run.event(
                "provider_request",
                provider=prov.name,
                model=resolved_model,
                json_mode=True,
                mode="multi" if use_multi else "single",
            )
        if use_multi:
            from .agents import run_multi_agent_review

            raw = await run_multi_agent_review(
                code=code,
                filename=filename,
                language=language,
                focus=focus_list,
                provider=prov,
                model=model,
                kb_context=kb_context,
                is_diff=is_diff,
            )
            if run:
                run.event("agents_completed", agents=raw.get("agents", []))
            result = validate_result(raw)
        else:
            text = await prov.chat(messages, model=model, json_mode=True)
            if run:
                run.event("provider_response", chars=len(text))
            result = validate_result(extract_json(text))
        if run:
            run.event("result_validated", issues=result["issueCount"], score=result["score"])
    except ProviderError as err:
        if run:
            elapsed = int((time.time() - started) * 1000)
            run.finish_meta(status="error", error=str(err), elapsed_ms=elapsed)
            runs.prune_runs()
        raise
    except Exception as err:
        if run:
            elapsed = int((time.time() - started) * 1000)
            run.finish_meta(status="error", error=f"内部错误：{err}", elapsed_ms=elapsed)
        raise EngineError(f"内部错误：{err}", 500, "INTERNAL") from err

    elapsed_ms = int((time.time() - started) * 1000)
    meta_summary = {
        "elapsed_ms": elapsed_ms,
        "score": result["score"],
        "issue_count": result["issueCount"],
        "summary": result["summary"],
    }
    if run:
        run.save_report(result)
        run.finish_meta(status="completed", **meta_summary)
        runs.prune_runs()

    return {
        **result,
        "meta": {
            "id": run.id if run else None,
            "created_at": run._meta["created_at"] if run and run._meta else None,  # noqa: SLF001
            "filename": filename,
            "language": language,
            "provider": prov.name,
            "model": resolved_model,
            "focus": focus_list,
            "line_count": len(code.splitlines()),
            "elapsed_ms": elapsed_ms,
            "kb_enabled": use_kb,
            "review_mode": "multi" if use_multi else "single",
        },
    }
