"""测试用轻量 fake：确定性 embedding + 内存向量库，避免真实 Qdrant / sentence-transformers 依赖。"""

from __future__ import annotations

import hashlib
from typing import Any


class FakeEmbedder:
    dim = 8
    name = "fake"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16)
            v = [((h >> (i * 8)) & 0xFF) / 255.0 for i in range(self.dim)]
            out.append(v)
        return out


class FakeVectorStore:
    def __init__(self):
        self._points: dict[str, dict[str, Any]] = {}

    def upsert(self, points: list[dict[str, Any]]) -> None:
        for p in points:
            self._points[p["id"]] = p

    def search(self, vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        scored = []
        for p in self._points.values():
            dot = sum(a * b for a, b in zip(vector, p["vector"], strict=True))
            scored.append({"score": dot, "payload": p["payload"]})
        scored.sort(key=lambda x: -x["score"])
        return scored[:top_k]

    def count(self) -> int:
        return len(self._points)

    def clear(self) -> None:
        self._points = {}
