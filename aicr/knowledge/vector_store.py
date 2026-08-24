"""向量库抽象 + Qdrant 实现。

支持三种 Qdrant 运行方式：
- 远程服务：url + api_key（Docker / Qdrant Cloud）
- 本地内嵌：path（持久化到本地目录，无需 Docker）
- 内存：仅测试用（":memory:"）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    """知识库向量存储的抽象接口。"""

    @abstractmethod
    def upsert(self, points: list[dict[str, Any]]) -> None:
        """写入点。point: {"id", "vector", "payload"}"""

    @abstractmethod
    def search(self, vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """返回 [{"score": float, "payload": dict}]"""

    @abstractmethod
    def count(self) -> int:
        """当前点数。"""

    @abstractmethod
    def clear(self) -> None:
        """清空集合。"""


class QdrantStore(VectorStore):
    def __init__(
        self,
        *,
        url: str = "",
        api_key: str = "",
        path: str = "",
        collection: str = "aicr_kb",
        dim: int = 384,
    ):
        self.collection = collection
        self.dim = dim
        try:
            import qdrant_client
        except ImportError as err:
            raise RuntimeError("未安装 qdrant-client，请运行: pip install qdrant-client") from err

        if url:
            self._client = qdrant_client.QdrantClient(url=url, api_key=api_key or None)
        elif path:
            self._client = qdrant_client.QdrantClient(path=path)
        else:
            self._client = qdrant_client.QdrantClient(location=":memory:")
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        try:
            self._client.get_collection(self.collection)
        except Exception:  # noqa: BLE001 - 集合不存在则创建
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )

    def upsert(self, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        from qdrant_client.models import PointStruct

        self._client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in points
            ],
        )

    def search(self, vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        result = self._client.query_points(
            collection_name=self.collection, query=vector, limit=top_k
        )
        return [{"score": p.score, "payload": p.payload} for p in result.points]

    def count(self) -> int:
        try:
            return self._client.count(collection_name=self.collection).count
        except Exception:  # noqa: BLE001
            return 0

    def clear(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self._client.delete_collection(collection_name=self.collection)
        self._ensure_collection()


def build_store(settings) -> QdrantStore:
    """根据配置构造 Qdrant 存储（远程 > 本地内嵌 > 内存）。"""
    from ..config import DATA_DIR

    local_path = settings.kb_qdrant_path or str(DATA_DIR / "kb")
    return QdrantStore(
        url=settings.kb_qdrant_url,
        api_key=settings.kb_qdrant_api_key,
        path="" if settings.kb_qdrant_url else local_path,
        collection=settings.kb_collection,
    )
