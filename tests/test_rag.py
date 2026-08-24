"""RAG 检索与上下文组装测试。"""

from __future__ import annotations

from helpers import FakeEmbedder, FakeVectorStore

from aicr.rag import build_query, context_stats, format_context, retrieve_context


def test_build_query_contains_filename_and_focus():
    q = build_query("server.py", "def main():\n    pass", ["security"])
    assert "server.py" in q
    assert "security" in q


def test_retrieve_context_empty_when_no_store():
    assert retrieve_context(None, FakeEmbedder(), "query", 5) == []
    assert retrieve_context(FakeVectorStore(), None, "query", 5) == []


def test_retrieve_context_returns_top_k():
    store = FakeVectorStore()
    embedder = FakeEmbedder()
    payloads = [
        {"source": f"doc{i}.md", "kind": "doc", "text": f"text{i}", "chunk_index": 0}
        for i in range(10)
    ]
    vectors = embedder.embed([p["text"] for p in payloads])
    store.upsert(
        [{"id": str(i), "vector": vectors[i], "payload": payloads[i]} for i in range(10)]
    )
    query = "text0"
    chunks = retrieve_context(store, embedder, query, top_k=3)
    assert len(chunks) == 3
    assert chunks[0]["payload"]["source"] == "doc0.md"


def test_format_context_and_stats():
    chunks = [
        {"score": 0.8, "payload": {"source": "a.md", "kind": "doc", "text": "规范内容 A"}},
        {"score": 0.6, "payload": {"source": "b.py", "kind": "code", "text": "代码片段 B"}},
    ]
    text = format_context(chunks)
    assert "a.md" in text and "b.py" in text
    stats = context_stats(chunks)
    assert stats["count"] == 2
    assert stats["sources"] == ["a.md", "b.py"]


def test_format_context_empty():
    assert format_context([]) == ""
