"""上下文管理：token 预算估算、按预算裁剪检索上下文、imports 提取（关联文件线索）。"""

from __future__ import annotations

import re

# 粗略 token 估算：中文约 1 token/字，英文约 4 字符/token，取折中（每 2 字符 ≈ 1 token）
_CHARS_PER_TOKEN = 2


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def fit_to_budget(chunks: list[dict], *, max_chars: int, header: str = "") -> str:
    """按字符预算贪心拼接检索片段，超限时截断，优先保留高分片段。

    chunks: [{"score": float, "payload": {"source": ..., "text": ..., "kind": ...}}]
    """
    parts: list[str] = []
    used = len(header)
    for ch in sorted(chunks, key=lambda c: -float(c.get("score", 0.0))):
        payload = ch.get("payload") or {}
        source = payload.get("source", "unknown")
        kind = payload.get("kind", "doc")
        text = str(payload.get("text", "")).strip()
        if not text:
            continue
        block = f"### [{kind}] {source}\n{text}"
        if used + len(block) > max_chars:
            remaining = max_chars - used - 40
            if remaining <= 0:
                break
            block = f"### [{kind}] {source}\n{text[:remaining]}…"
        parts.append(block)
        used += len(block) + 2
        if used >= max_chars:
            break
    return header + ("\n\n" if header and parts else "") + "\n\n".join(parts)


# ---------- imports 提取（关联文件上下文线索）----------

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+|import\s+([\w.]+))", re.MULTILINE)
_JS_IMPORT = re.compile(
    r"(?:import\s+[\w*\s{},]*\s+from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\))"
)
_GO_IMPORT = re.compile(r"^\s*\"([^\"]+)\"", re.MULTILINE)


def extract_imports(code: str, language: str | None = None) -> list[str]:
    """提取代码引用的模块/包名，作为相关文件上下文线索。"""
    if not code:
        return []
    lang = (language or "").lower()
    found: list[str] = []
    if lang == "python" or (lang == "" and "import " in code):
        for g1, g2 in _PY_IMPORT.findall(code):
            found.append(g1 or g2)
    elif lang in ("javascript", "typescript"):
        for g1, g2 in _JS_IMPORT.findall(code):
            found.append(g1 or g2)
    elif lang == "go":
        found.extend(m for m in _GO_IMPORT.findall(code) if m and not m.startswith(("/*", "//")))
    return _dedupe(found)


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.append(it)
    return seen


def truncate_for_query(text: str, max_chars: int = 2000) -> str:
    """生成检索 query 用的截断文本（避免把整份代码塞进 embedding）。"""
    return text[:max_chars]
