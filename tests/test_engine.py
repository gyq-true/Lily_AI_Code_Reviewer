"""审查引擎测试：JSON 提取、结果校验、编排与工件落盘。"""

from __future__ import annotations

import json

import pytest

from aicr import runs
from aicr.engine import run_review, validate_result
from aicr.prompts import build_system_prompt, build_user_prompt, extract_json
from aicr.providers import ProviderError


class FakeProvider:
    name = "fake"
    default_model = "fake-model"
    needs_key = False

    def __init__(self, payload: str | Exception = ""):
        self.payload = payload
        self.calls: list[dict] = []

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None, json_mode=False):
        self.calls.append({"messages": messages, "model": model, "json_mode": json_mode})
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


GOOD_REPORT = {
    "summary": "总体不错",
    "score": 88,
    "highlights": ["结构清晰"],
    "issues": [
        {"severity": "major", "title": "空指针", "line": 12, "description": "d", "suggestion": "s", "code": "x=1"},
        {"severity": "unknown-level", "title": "风格", "line": "bad", "description": "", "suggestion": "", "code": None},
    ],
    "recommendations": ["加测试"],
}


# ---------- extract_json ----------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = '好的，结果如下：\n```json\n{"score": 90}\n```\n以上。'
    assert extract_json(text) == {"score": 90}


def test_extract_json_with_surrounding_text():
    assert extract_json('前置说明 {"ok": true} 后置说明') == {"ok": True}


def test_extract_json_garbage_returns_none():
    assert extract_json("完全不是 JSON") is None
    assert extract_json(None) is None


# ---------- validate_result ----------

def test_validate_result_clamps_and_cleans():
    raw = {
        "summary": "s",
        "score": 150,
        "issues": GOOD_REPORT["issues"],
        "highlights": ["ok", 123],
        "recommendations": [42],
    }
    result = validate_result(raw)
    assert result["score"] == 100  # 钳制到 100
    assert len(result["issues"]) == 2
    assert result["issues"][0]["severity"] == "major"
    assert result["issues"][1]["severity"] == "minor"  # 非法级别回退
    assert result["issues"][1]["line"] is None
    assert result["highlights"] == ["ok"]
    assert result["recommendations"] == []
    assert result["issueCount"] == 2


def test_validate_result_rejects_non_dict():
    with pytest.raises(ProviderError):
        validate_result("not a dict")


# ---------- 提示词 ----------

def test_system_prompt_contains_focus_and_diff_note():
    prompt = build_system_prompt("Python", ["security", "style"], is_diff=True)
    assert "安全性" in prompt and "代码风格" in prompt
    assert "git diff" in prompt


def test_user_prompt_wraps_code():
    p = build_user_prompt("print(1)", "a.py", "Python")
    assert "a.py" in p and "print(1)" in p


# ---------- run_review 编排 ----------

@pytest.mark.asyncio
async def test_run_review_success_without_artifacts(isolated_dirs):
    fake = FakeProvider(json.dumps(GOOD_REPORT))
    result = await run_review(
        code="print(1)\n",
        filename="demo.py",
        focus=["correctness"],
        provider=fake,
        save_artifacts=False,
    )
    assert result["score"] == 88
    assert result["meta"]["provider"] == "fake"
    assert fake.calls[0]["json_mode"] is True
    assert "demo.py" in fake.calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_run_review_saves_artifacts(isolated_dirs):
    fake = FakeProvider(json.dumps(GOOD_REPORT))
    result = await run_review(code="print(1)", filename="demo.py", provider=fake)

    run_dir = isolated_dirs["data"] / "runs" / result["meta"]["id"]
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    trace_lines = (run_dir / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()

    assert meta["status"] == "completed"
    assert meta["score"] == 88
    assert report["issueCount"] == 2
    events = [json.loads(ln) for ln in trace_lines]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "run_started"
    assert "provider_request" in kinds and "report_saved" in kinds
    # 工件中不得出现 API Key 明文（FakeProvider 无 key，验证 trace 不含敏感字段名）
    assert not any("api_key" in ln for ln in trace_lines)


@pytest.mark.asyncio
async def test_run_review_provider_error_marks_run_failed(isolated_dirs):
    fake = FakeProvider(ProviderError("余额不足", status=402))
    with pytest.raises(ProviderError):
        await run_review(code="x=1", provider=fake)

    run_list = runs.list_runs()
    assert run_list and run_list[0]["status"] == "error"
    assert "余额不足" in run_list[0]["error"]


@pytest.mark.asyncio
async def test_run_review_injects_kb_context(isolated_dirs):
    from helpers import FakeEmbedder, FakeVectorStore

    store = FakeVectorStore()
    embedder = FakeEmbedder()
    store.upsert(
        [
            {
                "id": "x1",
                "vector": embedder.embed(["必须使用 service 层"])[0],
                "payload": {"source": "ARCH.md", "kind": "doc", "text": "必须使用 service 层"},
            }
        ]
    )

    fake = FakeProvider(json.dumps(GOOD_REPORT))
    result = await run_review(
        code="class C:\n    pass",
        filename="a.py",
        provider=fake,
        kb_enabled=True,
        kb_store=store,
        kb_embedder=embedder,
    )

    system = fake.calls[0]["messages"][0]["content"]
    assert "ARCH.md" in system
    assert "service 层" in system
    assert result["meta"]["kb_enabled"] is True


@pytest.mark.asyncio
async def test_run_review_kb_disabled_skips_retrieval(isolated_dirs):
    fake = FakeProvider(json.dumps(GOOD_REPORT))
    result = await run_review(code="x = 1", filename="a.py", provider=fake, kb_enabled=False)
    system = fake.calls[0]["messages"][0]["content"]
    assert "知识库检索" not in system
    assert result["meta"]["kb_enabled"] is False


@pytest.mark.asyncio
async def test_run_review_multi_mode(isolated_dirs):
    fake = FakeProvider(json.dumps(GOOD_REPORT))
    result = await run_review(code="x = 1", filename="a.py", provider=fake, mode="multi")
    assert result["meta"]["review_mode"] == "multi"
    assert len(result["agents"]) == 6
    # 6 个 agent 返回相同 GOOD_REPORT，去重后问题数仍为 2
    assert result["issueCount"] == 2
    # 每个 issue 都带 category 标签
    assert all(i.get("category") for i in result["issues"])
