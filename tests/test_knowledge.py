"""知识库层测试：分块、来源收集、摄入、Qdrant 内嵌（可选）。"""

from __future__ import annotations

import pytest
from helpers import FakeEmbedder, FakeVectorStore

from aicr.knowledge.ingest import chunk_text, classify, collect_sources, ingest_path


def test_chunk_text_splits_by_size():
    text = "\n\n".join(f"段落 {i} " + "x" * 300 for i in range(6))
    chunks = chunk_text(text, chunk_size=800, overlap=0)
    assert len(chunks) > 1
    assert all(len(c) <= 900 for c in chunks)


def test_chunk_text_empty():
    assert chunk_text("", chunk_size=800) == []


def test_chunk_text_rejects_bad_size():
    with pytest.raises(ValueError):
        chunk_text("x", chunk_size=0)


def test_classify(tmp_path):
    assert classify(tmp_path / "README.md") == "doc"
    assert classify(tmp_path / "app.py") == "code"
    assert classify(tmp_path / "notes.xyz") is None


def test_collect_sources_directory(tmp_path):
    (tmp_path / "README.md").write_text("# 项目说明\n\n内容", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("junk", encoding="utf-8")

    docs = collect_sources(tmp_path)
    kinds = {d.path.split("\\")[-1]: d.kind for d in docs}
    assert kinds["README.md"] == "doc"
    assert kinds["a.py"] == "code"
    assert not any("node_modules" in d.path for d in docs)


def test_collect_sources_single_file(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text("# 规范", encoding="utf-8")
    docs = collect_sources(f)
    assert len(docs) == 1 and docs[0].kind == "doc"


def test_ingest_path(tmp_path):
    (tmp_path / "README.md").write_text("# 规范\n\n必须使用 service 层。", encoding="utf-8")
    (tmp_path / "a.py").write_text("import os\n\nx = 1", encoding="utf-8")

    store = FakeVectorStore()
    stats = ingest_path(
        tmp_path, store=store, embedder=FakeEmbedder(), chunk_size=500, overlap=0
    )
    assert stats["files"] == 2
    assert stats["chunks"] == stats["points"] == store.count()
    assert store.count() > 0

    # 幂等：重复摄入相同内容不增加（相同 chunk id 覆盖）
    store_after_first = store.count()
    ingest_path(
        tmp_path, store=store, embedder=FakeEmbedder(), chunk_size=500, overlap=0
    )
    assert store.count() == store_after_first

    # recreate 会清空重建
    ingest_path(
        tmp_path, store=store, embedder=FakeEmbedder(), chunk_size=500, overlap=0, recreate=True
    )
    assert store.count() == stats["points"]


def _qdrant_available() -> bool:
    try:
        import qdrant_client  # noqa: F401
        from qdrant_client import QdrantClient

        QdrantClient(location=":memory:")
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _qdrant_available(), reason="qdrant-client 本地模式不可用")
def test_qdrant_store_local_memory():
    from aicr.knowledge.vector_store import QdrantStore

    store = QdrantStore(collection="test_kb", dim=8)
    vec = [0.1] * 8
    point_id = "12345678-1234-1234-1234-1234567890ab"
    store.upsert([{"id": point_id, "vector": vec, "payload": {"source": "a.md", "text": "hi"}}])
    assert store.count() == 1
    hits = store.search(vec, top_k=3)
    assert hits and hits[0]["payload"]["source"] == "a.md"
    store.clear()
    assert store.count() == 0
