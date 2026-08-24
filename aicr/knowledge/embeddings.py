"""Embedding 抽象与本地 sentence-transformers 实现。

sentence-transformers 是可选依赖（`pip install -e ".[rag]"`），
此处惰性导入，未安装时仅在真正调用 embed 时才报错。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    """把文本列表转为归一化向量。"""

    name: str = "base"

    @property
    def dim(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与 texts 等长的向量列表。"""


class LocalSentenceTransformerEmbedder(Embedder):
    name = "sentence-transformers"

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as err:
                raise RuntimeError(
                    "未安装 sentence-transformers，请运行: pip install -e \".[rag]\""
                ) from err
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dim(self) -> int:
        return self._load().get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]


def build_embedder(settings) -> Embedder:
    return LocalSentenceTransformerEmbedder(settings.kb_embedding_model)
