"""知识库摄入：来源收集 → 分块 → 去重 → 向量化 → 入库。"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..collector import EXT_LANG, SKIP_DIRS, _read_text

DOC_EXTS = {"md", "rst", "txt"}
DOC_FILENAMES = {"readme.md", "contributing.md", "architecture.md", "coding_standards.md"}


@dataclass
class SourceDoc:
    path: str
    text: str
    kind: str  # "doc" | "code"
    language: str | None = None


def chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """按空行段落合并成大小受限的块，带少量重叠以保留上下文。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正数")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 2 > chunk_size:
            chunks.append(buf)
            # 重叠：保留上一块尾部作为上下文
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = (tail + "\n\n" + para) if tail else para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def classify(path: Path) -> str | None:
    """返回 'doc' / 'code'，不可入库则返回 None。"""
    name = path.name.lower()
    ext = path.suffix.lstrip(".").lower()
    if ext in DOC_EXTS or name in DOC_FILENAMES:
        return "doc"
    if ext in EXT_LANG:
        return "code"
    return None


def collect_sources(root: str | Path, *, max_files: int = 200, max_bytes: int = 200_000) -> list[SourceDoc]:
    """扫描目录，收集文档与代码来源。"""
    root_p = Path(root)
    if not root_p.exists():
        raise FileNotFoundError(f"路径不存在：{root_p}")
    if root_p.is_file():
        kind = classify(root_p)
        if kind is None:
            return []
        text = _read_text(root_p, max_bytes)
        if text is None:
            return []
        lang = EXT_LANG.get(root_p.suffix.lstrip(".").lower())
        return [SourceDoc(path=str(root_p), text=text, kind=kind, language=lang)]

    docs: list[SourceDoc] = []
    for p in sorted(root_p.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        kind = classify(p)
        if kind is None:
            continue
        if p.stat().st_size > max_bytes:
            continue
        text = _read_text(p, max_bytes)
        if text is None:
            continue
        lang = EXT_LANG.get(p.suffix.lstrip(".").lower())
        docs.append(SourceDoc(path=str(p), text=text, kind=kind, language=lang))
        if len(docs) >= max_files:
            break
    return docs


def _chunk_id(path: str, index: int) -> str:
    digest = hashlib.sha1(f"{path}::{index}".encode()).hexdigest()
    return str(uuid.UUID(digest[:32]))


def ingest_path(
    root: str | Path,
    *,
    store: Any,
    embedder: Any,
    chunk_size: int = 800,
    overlap: int = 100,
    max_files: int = 200,
    recreate: bool = False,
) -> dict[str, Any]:
    """摄入目录到向量库，返回统计信息。"""
    sources = collect_sources(root, max_files=max_files)
    if recreate:
        store.clear()

    seen: set[str] = set()
    chunks: list[dict[str, Any]] = []
    for doc in sources:
        for i, text in enumerate(chunk_text(doc.text, chunk_size=chunk_size, overlap=overlap)):
            cid = _chunk_id(doc.path, i)
            if cid in seen:
                continue
            seen.add(cid)
            chunks.append(
                {
                    "id": cid,
                    "text": text,
                    "payload": {
                        "source": doc.path,
                        "kind": doc.kind,
                        "language": doc.language or "",
                        "chunk_index": i,
                        "text": text,
                    },
                }
            )

    vectors = embedder.embed([c["text"] for c in chunks])
    points = [
        {"id": c["id"], "vector": vec, "payload": c["payload"]}
        for c, vec in zip(chunks, vectors, strict=True)
    ]
    store.upsert(points)
    return {
        "files": len(sources),
        "chunks": len(chunks),
        "points": len(points),
    }
