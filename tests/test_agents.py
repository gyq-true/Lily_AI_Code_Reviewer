"""LangGraph 多 Agent 编排集成测试（FakeProvider，无真实网络）。"""

from __future__ import annotations

import json
import re

import pytest

from aicr.agents import run_multi_agent_review


class MultiFakeProvider:
    name = "fake"
    default_model = "fake-model"
    needs_key = False

    def __init__(self):
        self.labels: list[str] = []
        self.user_prompts: list[str] = []

    async def chat(self, messages, **kwargs):
        system = messages[0]["content"]
        match = re.search(r"「(.+?)」", system)
        label = match.group(1) if match else "unknown"
        self.labels.append(label)
        self.user_prompts.append(messages[1]["content"] if len(messages) > 1 else "")
        if label.startswith("总览"):
            return json.dumps(
                {
                    "summary": "总体良好",
                    "score": 82,
                    "highlights": ["结构清晰"],
                    "recommendations": ["补测试"],
                    "issues": [],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "summary": "",
                "score": 0,
                "issues": [
                    {
                        "severity": "major",
                        "title": f"{label}问题",
                        "line": 1,
                        "description": "d",
                        "suggestion": "s",
                        "code": None,
                    }
                ],
                "recommendations": [],
            },
            ensure_ascii=False,
        )


@pytest.mark.asyncio
async def test_multi_agent_full_run():
    prov = MultiFakeProvider()
    result = await run_multi_agent_review(
        code="x = 1", filename="a.py", focus=[], provider=prov, max_concurrency=6
    )
    assert result["summary"] == "总体良好"
    assert result["score"] == 82
    assert result["issueCount"] == 5  # 5 个专项各 1 条
    assert set(result["agents"]) == {
        "overview",
        "architecture",
        "security",
        "performance",
        "style",
        "testing",
    }
    cats = {i["category"] for i in result["issues"]}
    assert len(cats) == 5
    assert len(prov.labels) == 6
    # 代码必须真正传递到每个 agent 的用户提示词
    assert all("x = 1" in up for up in prov.user_prompts)


@pytest.mark.asyncio
async def test_multi_agent_focus_filter():
    prov = MultiFakeProvider()
    await run_multi_agent_review(
        code="x = 1", focus=["security", "style"], provider=prov, max_concurrency=6
    )
    labels = set(prov.labels)
    assert "总览与正确性" in labels
    assert "安全" in labels
    assert "风格与可读性" in labels
    assert "性能" not in labels
    assert "架构与最佳实践" not in labels
