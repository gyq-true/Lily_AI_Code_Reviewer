"""合成器：把多个专项 agent 的结果确定性合并为统一报告（复用既有 report schema）。"""

from __future__ import annotations

from typing import Any

from .specialists import SPECIALIST_BY_NAME


def _norm_title(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


def _clamp_score(score: Any) -> int:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return 0
    return max(0, min(100, int(score)))


def dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 (规范化标题, 行号) 去重，保留首次出现。"""
    seen: set[tuple[str, Any]] = set()
    out: list[dict[str, Any]] = []
    for it in issues:
        if not isinstance(it, dict):
            continue
        key = (_norm_title(str(it.get("title", ""))), it.get("line"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _dedupe_strs(items: list[str]) -> list[str]:
    seen: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.append(it)
    return seen


def merge_reports(agent_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """合并各 agent 报告：总览提供 summary/score/highlights/recommendations，
    各专项提供 issues（打上 category 标签），并做去重。"""
    overview: dict[str, Any] = {}
    all_issues: list[dict[str, Any]] = []
    highlights: list[str] = []
    recommendations: list[str] = []
    scores: list[int] = []

    for ar in agent_reports:
        name = ar.get("agent", "")
        spec = SPECIALIST_BY_NAME.get(name)
        label = spec.label if spec else name
        report = ar.get("report") or {}
        if not isinstance(report, dict):
            continue

        if name == "overview":
            overview = report
        for it in report.get("issues") or []:
            if isinstance(it, dict):
                all_issues.append({**it, "category": label})
        highlights.extend(h for h in (report.get("highlights") or []) if isinstance(h, str))
        recommendations.extend(
            r for r in (report.get("recommendations") or []) if isinstance(r, str)
        )
        s = report.get("score")
        if isinstance(s, (int, float)) and not isinstance(s, bool):
            scores.append(int(s))

    issues = dedupe_issues(all_issues)
    score = _clamp_score(overview.get("score")) if overview else (
        round(sum(scores) / len(scores)) if scores else 0
    )
    summary = str(overview.get("summary") or "（多专家已完成审查，但总览未返回摘要）")

    return {
        "summary": summary,
        "score": score,
        "highlights": _dedupe_strs(highlights),
        "issues": issues,
        "recommendations": _dedupe_strs(recommendations),
        "issueCount": len(issues),
        "agents": [ar.get("agent") for ar in agent_reports],
    }
