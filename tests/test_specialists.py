"""专项 agent 定义测试。"""

from __future__ import annotations

from aicr.agents.specialists import (
    SPECIALIST_BY_NAME,
    SPECIALISTS,
    build_system,
    select_agents,
)


def test_specialists_count_and_names():
    assert [s.name for s in SPECIALISTS] == [
        "overview",
        "architecture",
        "security",
        "performance",
        "style",
        "testing",
    ]


def test_select_agents_empty_runs_all():
    assert select_agents([]) == [s.name for s in SPECIALISTS]


def test_select_agents_filters_focus():
    names = select_agents(["security", "style"])
    assert names[0] == "overview"
    assert "security" in names and "style" in names
    assert "performance" not in names


def test_select_agents_unknown_focus_ignored():
    assert select_agents(["nope"]) == ["overview"]


def test_build_system_contains_role_mission_and_kb():
    spec = SPECIALIST_BY_NAME["security"]
    sys = build_system(spec, "Python", "规范上下文XYZ", False)
    assert "安全" in sys
    assert "规范上下文XYZ" in sys
    assert "JSON" in sys


def test_build_system_diff_note():
    sys = build_system(SPECIALIST_BY_NAME["style"], "Python", "", True)
    assert "git diff" in sys
