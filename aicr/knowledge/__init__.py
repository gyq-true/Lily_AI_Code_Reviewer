"""知识库层：embedding + 向量库 + 摄入 的统一入口。"""

from __future__ import annotations

from .embeddings import Embedder, build_embedder
from .ingest import ingest_path
from .vector_store import QdrantStore, VectorStore, build_store

__all__ = [
    "Embedder",
    "VectorStore",
    "QdrantStore",
    "build_embedder",
    "build_store",
    "ingest_path",
]
