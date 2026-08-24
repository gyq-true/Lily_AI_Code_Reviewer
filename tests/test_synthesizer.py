"""合成器测试：多 agent 报告合并与去重。"""

from __future__ import annotations

from aicr.agents.synthesizer import dedupe_issues, merge_reports


def test_merge_reports_combines_and_tags():
    reports = [
        {
            "agent": "overview",
            "report": {
                "summary": "总体不错",
                "score": 85,
                "highlights": ["结构清晰"],
                "recommendations": ["补测试"],
                "issues": [],
            },
        },
        {"agent": "security", "report": {"issues": [{"title": "SQL 注入", "severity": "critical"}]}},
        {"agent": "style", "report": {"issues": [{"title": "命名不规范", "severity": "minor"}]}},
    ]
    r = merge_reports(reports)
    assert r["summary"] == "总体不错"
    assert r["score"] == 85
    assert r["issueCount"] == 2
    cats = {i["category"] for i in r["issues"]}
    assert cats == {"安全", "风格与可读性"}


def test_merge_no_overview_avg_score():
    reports = [
        {"agent": "security", "report": {"issues": [{"title": "x"}], "score": 70}},
        {"agent": "style", "report": {"issues": [{"title": "y"}], "score": 90}},
    ]
    r = merge_reports(reports)
    assert r["score"] == 80
    assert r["issueCount"] == 2


def test_merge_dedupes_identical_issue_across_agents():
    reports = [
        {"agent": "security", "report": {"issues": [{"title": "重复问题", "line": 1}]}},
        {"agent": "style", "report": {"issues": [{"title": "重复问题", "line": 1}]}},
    ]
    r = merge_reports(reports)
    assert r["issueCount"] == 1


def test_dedupe_issues_normalizes_title():
    issues = [
        {"title": "SQL 注入", "line": 1},
        {"title": "sql注入", "line": 1},  # 规范化后相同
        {"title": "另一问题", "line": 2},
    ]
    assert len(dedupe_issues(issues)) == 2


def test_merge_handles_malformed_report():
    reports = [
        {"agent": "overview", "report": "not a dict"},
        {"agent": "security", "report": {"issues": [{"title": "ok"}]}},
    ]
    r = merge_reports(reports)
    assert r["issueCount"] == 1
    assert r["score"] == 0
