"""多 Agent 审查层：基于 LangGraph 的编排 + 专项专家 + 合成器。"""

from __future__ import annotations

from .graph import run_multi_agent_review
from .specialists import SPECIALIST_BY_NAME, SPECIALISTS, select_agents
from .synthesizer import dedupe_issues, merge_reports

__all__ = [
    "SPECIALISTS",
    "SPECIALIST_BY_NAME",
    "select_agents",
    "merge_reports",
    "dedupe_issues",
    "run_multi_agent_review",
]
