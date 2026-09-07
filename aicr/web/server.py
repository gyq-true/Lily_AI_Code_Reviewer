"""FastAPI 应用与 REST API。"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import runs
from ..collector import (
    CollectedFile,
    CollectorError,
    SkippedFile,
    collect_from_path,
    collect_git_diff,
    collect_single,
)
from ..config import get_public_settings, load_config, save_config
from ..conversation import Conversation
from ..engine import run_review
from ..providers import ProviderError, available_providers, build_provider

app = FastAPI(title="智能代码审查助手", version="2.0.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

FOCUS_KEYS = {"correctness", "security", "performance", "style", "bestPractice", "testing"}
MAX_CODE_CHARS = 200_000
BATCH_CONCURRENCY = 3


class SettingsIn(BaseModel):
    provider: str | None = None
    apiKey: str | None = None  # 旧版扁平字段，视为 deepseek 段
    apiBase: str | None = None
    model: str | None = None
    deepseek: dict[str, str] | None = None
    openai: dict[str, str] | None = None
    anthropic: dict[str, str] | None = None
    ollama: dict[str, str] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout_ms: int | None = Field(default=None, ge=5000)
    kb_enabled: bool | None = None
    kb_qdrant_url: str | None = None
    kb_qdrant_path: str | None = None
    kb_qdrant_api_key: str | None = None
    kb_collection: str | None = None
    kb_embedding_model: str | None = None
    kb_top_k: int | None = Field(default=None, gt=0)
    kb_chunk_size: int | None = Field(default=None, gt=0)
    kb_chunk_overlap: int | None = Field(default=None, ge=0)


class ReviewIn(BaseModel):
    code: str | None = None
    path: str | None = None
    git_repo: str | None = None
    git_staged: bool = False
    filename: str | None = None
    language: str | None = None
    focus: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    kb_enabled: bool | None = None
    mode: str | None = None


class KBIngestIn(BaseModel):
    path: str
    recreate: bool = False


class KBSearchIn(BaseModel):
    query: str
    top_k: int = 5


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    system: str | None = None


# 进程内会话存储：session_id -> Conversation
_CHAT_SESSIONS: dict[str, Conversation] = {}


# ---------- 静态页面 ----------

@app.get("/", include_in_schema=False)
async def index():
    from fastapi.responses import FileResponse

    return FileResponse(STATIC_DIR / "index.html")


@app.get("/settings.html", include_in_schema=False)
async def settings_page():
    from fastapi.responses import FileResponse

    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/chat.html", include_in_schema=False)
async def chat_page():
    from fastapi.responses import FileResponse

    return FileResponse(STATIC_DIR / "chat.html")


@app.get("/kb.html", include_in_schema=False)
async def kb_page():
    from fastapi.responses import FileResponse

    return FileResponse(STATIC_DIR / "kb.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------- 基础接口 ----------

@app.get("/api/health")
async def health():
    cfg = get_public_settings()
    section = cfg["providers"].get(cfg["provider"], {})
    return {
        "status": "ok",
        "provider": cfg["provider"],
        "configured": bool(section.get("has_api_key")) or cfg["provider"] == "ollama",
    }


@app.get("/api/settings")
async def get_settings():
    return get_public_settings()


@app.post("/api/settings")
async def update_settings(body: SettingsIn):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if isinstance(patch.get("apiKey"), str):
        patch["apiKey"] = patch["apiKey"].strip() or None
        if patch["apiKey"] is None:
            patch.pop("apiKey")
    if not patch:
        raise HTTPException(status_code=400, detail="没有有效的配置项")
    if patch.get("provider") and patch["provider"] not in available_providers():
        names = ", ".join(available_providers())
        raise HTTPException(status_code=400, detail=f"未知 provider，可选：{names}")
    try:
        save_config(patch)
    except OSError as err:
        raise HTTPException(status_code=500, detail=f"保存配置失败：{err}") from err
    return get_public_settings()


@app.get("/api/providers")
async def providers():
    return {"providers": available_providers()}


@app.post("/api/providers/test")
async def test_provider(provider: str | None = None):
    """发送最小请求验证当前/指定 provider 连通性。"""
    try:
        prov = build_provider(load_config(), provider)
        text = await prov.chat(
            [{"role": "user", "content": '回复一个词：ok'}], max_tokens=16
        )
        return {"ok": True, "reply": (text or "").strip()[:50]}
    except ProviderError as err:
        return JSONResponse(status_code=err.status, content={"ok": False, "error": err.message})


# ---------- 多轮对话 ----------

@app.post("/api/chat")
async def chat(body: ChatIn):
    """多轮对话接口：返回回复文本与思考内容（支持思考型模型）。"""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    try:
        conv = _CHAT_SESSIONS.get(body.session_id) if body.session_id else None
        if conv is None:
            conv = Conversation.create(body.provider, model=body.model, system=body.system)
            session_id = body.session_id or uuid.uuid4().hex
            _CHAT_SESSIONS[session_id] = conv
        else:
            session_id = body.session_id or ""
        result = await conv.ask(body.message)
    except ProviderError as err:
        raise HTTPException(status_code=err.status, detail=err.message) from err

    return {
        "session_id": session_id,
        "reply": result.text,
        "reasoning": result.reasoning,
        "finish_reason": result.finish_reason,
        "turn_count": len(conv.history()),
    }


@app.delete("/api/chat/{session_id}")
async def chat_reset(session_id: str):
    """结束并清空某个会话。"""
    if _CHAT_SESSIONS.pop(session_id, None) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


# ---------- 审查 ----------

def _validate_focus(focus: list[str]) -> list[str]:
    return [f for f in focus if f in FOCUS_KEYS]


async def _review_one(item, body: ReviewIn) -> dict:
    result = await run_review(
        code=item.code,
        filename=item.path if item.is_diff else (body.filename or Path(item.path).name),
        language=body.language,
        focus=_validate_focus(body.focus),
        provider_name=body.provider,
        model=body.model,
        is_diff=item.is_diff,
        kb_enabled=body.kb_enabled,
        mode=body.mode,
    )
    return result


@app.post("/api/review")
async def review(body: ReviewIn):
    try:
        if body.code is not None and body.code.strip():
            if len(body.code) > MAX_CODE_CHARS:
                raise CollectorError("代码过长（超过 20 万字符），请分段审查")
            item = collect_single(body.code, body.filename, body.language)
            return await _review_one(item, body)

        if body.path:
            items = collect_from_path(body.path, max_files=1)
            item = items[0]
            item.path = body.filename or item.path
            return await _review_one(item, body)

        if body.git_repo:
            items = await asyncio.to_thread(collect_git_diff, body.git_repo, staged=body.git_staged)
            results = await _run_batch(items[:5], body)
            skipped = [
                {"path": i.path, "reason": "git diff 单次审查最多 5 个文件"} for i in items[5:]
            ]
            if len(results) == 1 and not skipped:
                return results[0]
            return {"batch": True, "results": results, "skipped": skipped}

        raise CollectorError("请提供 code、path 或 git_repo 之一")
    except CollectorError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except ProviderError as err:
        raise HTTPException(status_code=err.status, detail=err.message) from err


@app.post("/api/review/batch")
async def review_batch(body: ReviewIn):
    try:
        if body.code is not None and body.code.strip():
            # 多文件上传场景：files 数组在扩展字段中传递（见 FilesIn）
            raise CollectorError("批量接口请使用 files / path / git_repo")

        skipped: list[SkippedFile] = []
        if body.path:
            items = collect_from_path(body.path, max_files=30, skipped=skipped)
        elif body.git_repo:
            items = await asyncio.to_thread(collect_git_diff, body.git_repo, staged=body.git_staged)
        else:
            raise CollectorError("请提供 path 或 git_repo")

        results = await _run_batch(items, body)
        return {
            "batch": True,
            "total": len(results),
            "avg_score": round(sum(r["score"] for r in results) / max(1, len(results))),
            "skipped": [{"path": s.path, "reason": s.reason} for s in skipped],
            "results": [
                {
                    "file": r["meta"]["filename"],
                    **r,
                }
                for r in results
            ],
        }
    except CollectorError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except ProviderError as err:
        raise HTTPException(status_code=err.status, detail=err.message) from err


class FilesIn(ReviewIn):
    files: list[dict] = Field(default_factory=list)


@app.post("/api/review/files")
async def review_files(body: FilesIn):
    """浏览器多文件上传批量审查。"""
    if not body.files:
        raise HTTPException(status_code=400, detail="files 不能为空")
    items = []
    skipped: list[dict] = []
    for f in body.files[:30]:
        name = str(f.get("name") or "file")
        content = str(f.get("content") or "")
        if not content.strip():
            skipped.append({"path": name, "reason": "内容为空"})
            continue
        if len(content) > MAX_CODE_CHARS:
            skipped.append({"path": name, "reason": f"超过大小限制（>{MAX_CODE_CHARS} 字符）"})
            continue
        items.append(CollectedFile(path=name, code=content, language=None))
    if len(body.files) > 30:
        extra = len(body.files) - 30
        skipped.append({"path": "(上传)", "reason": f"另有 {extra} 个文件超过数量上限（30）被跳过"})
    if not items:
        raise HTTPException(status_code=400, detail="没有可审查的文件内容")
    for it in items:
        from ..collector import guess_language

        it.language = body.language or guess_language(it.path)
    try:
        results = await _run_batch(items, body)
    except ProviderError as err:
        raise HTTPException(status_code=err.status, detail=err.message) from err
    return {
        "batch": True,
        "total": len(results),
        "avg_score": round(sum(r["score"] for r in results) / max(1, len(results))),
        "skipped": skipped,
        "results": [{"file": r["meta"]["filename"], **r} for r in results],
    }


async def _run_batch(items, body: ReviewIn) -> list[dict]:
    sem = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def worker(item):
        async with sem:
            try:
                return await _review_one(item, body)
            except (ProviderError, Exception) as err:  # noqa: BLE001 - 单文件失败不阻断批次
                status = getattr(err, "status", 500)
                message = getattr(err, "message", str(err))
                return {
                    "error": message,
                    "status_code": status,
                    "meta": {"filename": item.path, "provider": body.provider},
                    "score": 0,
                    "issues": [],
                    "highlights": [],
                    "recommendations": [],
                    "summary": f"该文件审查失败：{message}",
                    "issueCount": 0,
                }

    return list(await asyncio.gather(*(worker(i) for i in items)))


# ---------- 运行记录 ----------

@app.get("/api/runs")
async def list_runs(limit: int = 200):
    return runs.list_runs(min(limit, 500))


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    record = runs.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return record


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    if not runs.delete_run(run_id):
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"ok": True}


# ---------- 知识库 / RAG ----------

@app.get("/api/kb/stats")
async def kb_stats():
    from ..knowledge import build_store

    cfg = load_config()
    try:
        store = build_store(cfg)
        points = store.count()
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"向量库不可用：{err}") from err
    return {
        "enabled": cfg.kb_enabled,
        "collection": cfg.kb_collection,
        "points": points,
        "embedding_model": cfg.kb_embedding_model,
        "backend": "remote" if cfg.kb_qdrant_url else "local",
    }


@app.post("/api/kb/ingest")
async def kb_ingest(body: KBIngestIn):
    from ..knowledge import build_embedder, build_store, ingest_path

    cfg = load_config()
    try:
        store = build_store(cfg)
        embedder = build_embedder(cfg)
        stats = await asyncio.to_thread(
            ingest_path,
            body.path,
            store=store,
            embedder=embedder,
            chunk_size=cfg.kb_chunk_size,
            overlap=cfg.kb_chunk_overlap,
            recreate=body.recreate,
        )
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"摄入失败：{err}") from err
    return stats


@app.post("/api/kb/search")
async def kb_search(body: KBSearchIn):
    from ..knowledge import build_embedder, build_store
    from ..rag import retrieve_context

    cfg = load_config()
    try:
        store = build_store(cfg)
        embedder = build_embedder(cfg)
        chunks = await asyncio.to_thread(
            retrieve_context, store, embedder, body.query, body.top_k
        )
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"检索失败：{err}") from err
    return {
        "results": [
            {
                "score": ch["score"],
                "source": (ch["payload"] or {}).get("source"),
                "kind": (ch["payload"] or {}).get("kind"),
                "text": (ch["payload"] or {}).get("text"),
            }
            for ch in chunks
        ]
    }


@app.delete("/api/kb")
async def kb_clear():
    from ..knowledge import build_store

    cfg = load_config()
    store = build_store(cfg)
    store.clear()
    return {"ok": True}
