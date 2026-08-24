"""FastAPI 集成测试（TestClient + 注入 FakeProvider，无真实网络）。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aicr.web.server import app


class FakeProvider:
    name = "fake"
    default_model = "fake-model"

    def __init__(self, payload: str | Exception):
        self.payload = payload

    async def chat(self, messages, **kwargs):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


GOOD = {
    "summary": "ok",
    "score": 90,
    "highlights": [],
    "issues": [{"severity": "minor", "title": "t", "line": 1, "description": "d", "suggestion": "s", "code": None}],
    "recommendations": [],
}


@pytest.fixture()
def client(monkeypatch, isolated_dirs):
    def fake_run_review(**kwargs):
        return _sync_run(kwargs)

    async def _sync_run(kwargs):
        return {
            **GOOD,
            "issueCount": len(GOOD["issues"]),
            "meta": {
                "id": "test-run-id",
                "created_at": "2026-01-01T00:00:00",
                "filename": kwargs.get("filename"),
                "language": kwargs.get("language"),
                "provider": "fake",
                "model": "fake-model",
                "focus": kwargs.get("focus") or [],
                "line_count": len(kwargs["code"].splitlines()),
                "elapsed_ms": 5,
            },
        }

    monkeypatch.setattr("aicr.web.server.run_review", fake_run_review)
    return TestClient(app)


def test_health(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["provider"] == "deepseek"


def test_settings_roundtrip_masked(client, isolated_dirs):
    # 保存 key（分 provider 段）
    resp = client.post("/api/settings", json={"deepseek": {"api_key": "sk-web-secret-9999"}})
    assert resp.status_code == 200
    pub = resp.json()
    masked = pub["providers"]["deepseek"]["api_key_masked"]
    assert "secret" not in masked and "****" in masked

    # 再读取确认脱敏
    got = client.get("/api/settings").json()
    assert got["providers"]["deepseek"]["has_api_key"] is True


def test_settings_invalid_provider_rejected(client):
    resp = client.post("/api/settings", json={"provider": "nope"})
    assert resp.status_code == 400


def test_review_single_with_injected_fake(client):
    resp = client.post(
        "/api/review",
        json={"code": "print('hi')\n", "filename": "a.py", "focus": ["correctness"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 90
    assert data["meta"]["provider"] == "fake"
    assert data["issueCount"] == 1


def test_review_empty_code_rejected(client):
    resp = client.post("/api/review", json={"code": "   "})
    assert resp.status_code == 400


def test_review_batch_files(client):
    files = [
        {"name": "a.py", "content": "x = 1\n"},
        {"name": "b.js", "content": "let y=2;\n"},
        {"name": "empty.py", "content": "  "},  # 应被跳过
    ]
    resp = client.post("/api/review/files", json={"files": files})
    assert resp.status_code == 200
    data = resp.json()
    assert data["batch"] is True
    assert data["total"] == 2
    assert {r["file"] for r in data["results"]} == {"a.py", "b.js"}


def test_review_provider_error_maps_status(client, monkeypatch):
    from aicr.providers import ProviderError

    async def failing(**kwargs):
        raise ProviderError("Key 无效", status=401)

    monkeypatch.setattr("aicr.web.server.run_review", failing)
    resp = client.post("/api/review", json={"code": "x"})
    assert resp.status_code == 401
    assert "Key 无效" in resp.json()["detail"]


def test_runs_crud(client, isolated_dirs):
    from aicr import runs

    run = runs.RunTrace("20260101-000000-aaaa")
    run.init_meta(filename="x.py", score=80, issue_count=1, status="running")
    run.save_report(GOOD)
    run.finish_meta(status="completed", score=80, issue_count=1)

    listed = client.get("/api/runs").json()
    assert any(m["id"] == "20260101-000000-aaaa" for m in listed)

    detail = client.get("/api/runs/20260101-000000-aaaa").json()
    assert detail["report"]["score"] == 90 or detail["report"]["score"] == GOOD["score"]
    assert any(e["event"] == "run_started" for e in detail["trace"])

    assert client.delete("/api/runs/20260101-000000-aaaa").json() == {"ok": True}
    assert client.get("/api/runs/20260101-000000-aaaa").status_code == 404
    assert client.delete("/api/runs/no-such").status_code == 404


def test_legacy_history_migration(isolated_dirs):
    from aicr import runs

    history_file = isolated_dirs["data"] / "history.json"
    legacy = [
        {
            "id": "legacy-uuid-1",
            "createdAt": "2026-08-13T10:00:00",
            "filename": "old.js",
            "language": "JavaScript",
            "model": "deepseek-chat",
            "focus": ["security"],
            "score": 77,
            "issueCount": 3,
            "summary": "旧记录",
            "highlights": [],
            "issues": [],
            "recommendations": [],
        }
    ]
    history_file.write_text(json.dumps(legacy), encoding="utf-8")
    migrated = runs.import_legacy_history(history_file)
    assert migrated == 1

    meta = runs.get_run("legacy-uuid-1")
    assert meta["meta"]["status"] == "completed"
    assert meta["meta"]["filename"] == "old.js"
    assert meta["report"]["summary"] == "旧记录"
    # 幂等
    assert runs.import_legacy_history(history_file) == 0


def test_static_pages_served(client):
    assert client.get("/").status_code == 200
    html = client.get("/").text
    assert "智能代码审查助手" in html
    css = client.get("/static/css/style.css")
    assert css.status_code == 200


def test_chat_endpoint_multiturn(client, monkeypatch):
    from aicr.conversation import Conversation
    from aicr.providers.base import ChatResult

    calls: list[str] = []
    state = {"n": 0}

    class FakeConv:
        async def ask(self, message, **kwargs):
            calls.append(message)
            state["n"] += 1
            return ChatResult(
                text=f"reply-{state['n']}", reasoning="think", finish_reason="stop"
            )

        def history(self):
            return []

    def fake_create(provider_name=None, model=None, system=None):
        return FakeConv()

    monkeypatch.setattr(Conversation, "create", staticmethod(fake_create))
    monkeypatch.setattr("aicr.web.server._CHAT_SESSIONS", {})

    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "reply-1"
    assert data["reasoning"] == "think"
    assert data["finish_reason"] == "stop"
    session_id = data["session_id"]

    resp2 = client.post("/api/chat", json={"message": "again", "session_id": session_id})
    assert resp2.status_code == 200
    assert resp2.json()["reply"] == "reply-2"
    assert calls == ["hello", "again"]

    # 空消息被拒绝
    assert client.post("/api/chat", json={"message": "   "}).status_code == 400


def _patch_kb(monkeypatch):
    from helpers import FakeEmbedder, FakeVectorStore

    monkeypatch.setattr("aicr.knowledge.build_store", lambda settings: FakeVectorStore())
    monkeypatch.setattr("aicr.knowledge.build_embedder", lambda settings: FakeEmbedder())


def test_kb_stats_endpoint(client, monkeypatch):
    _patch_kb(monkeypatch)
    r = client.get("/api/kb/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["points"] == 0
    assert data["backend"] == "local"


def test_kb_ingest_and_search(client, monkeypatch, tmp_path):
    from helpers import FakeEmbedder, FakeVectorStore

    store = FakeVectorStore()
    monkeypatch.setattr("aicr.knowledge.build_store", lambda settings: store)
    monkeypatch.setattr("aicr.knowledge.build_embedder", lambda settings: FakeEmbedder())

    (tmp_path / "README.md").write_text("# 规范\n\n必须使用 service 层。", encoding="utf-8")

    r = client.post("/api/kb/ingest", json={"path": str(tmp_path), "recreate": False})
    assert r.status_code == 200
    stats = r.json()
    assert stats["files"] == 1 and stats["points"] >= 1
    assert store.count() == stats["points"]

    r2 = client.post("/api/kb/search", json={"query": "service 层", "top_k": 3})
    assert r2.status_code == 200
    results = r2.json()["results"]
    assert results and "service 层" in results[0]["text"]


def test_kb_clear(client, monkeypatch):
    from helpers import FakeVectorStore

    store = FakeVectorStore()
    store.upsert([{"id": "a", "vector": [0.1] * 8, "payload": {}}])
    monkeypatch.setattr("aicr.knowledge.build_store", lambda settings: store)
    assert client.delete("/api/kb").json() == {"ok": True}
    assert store.count() == 0


def test_kb_ingest_missing_path(client, monkeypatch):
    _patch_kb(monkeypatch)
    r = client.post("/api/kb/ingest", json={"path": "Z:/no/such/dir"})
    assert r.status_code == 404
