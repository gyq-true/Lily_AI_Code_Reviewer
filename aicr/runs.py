"""运行工件持久化（PICO 式）：每次审查在 data/runs/<run_id>/ 下落盘

- meta.json    运行元信息与结果摘要
- trace.jsonl  逐条事件追踪（请求开始/模型调用/校验/完成或失败）
- report.json  最终结构化审查报告
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

from .config import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"
MAX_RUNS = 500


def new_run_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


class RunTrace:
    """单次运行的工件读写器。"""

    def __init__(self, run_id: str):
        self.id = run_id
        self.dir = RUNS_DIR / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.dir / "meta.json"
        self.trace_path = self.dir / "trace.jsonl"
        self.report_path = self.dir / "report.json"
        self._meta: dict[str, Any] | None = None
        self._seq = 0

    # ---------- trace 事件 ----------
    def event(self, kind: str, **fields: Any) -> None:
        self._seq += 1
        record = {"ts": time.time(), "seq": self._seq, "event": kind, **fields}
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---------- meta ----------
    def init_meta(self, **fields: Any) -> dict[str, Any]:
        self._meta = {
            "id": self.id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "running",
            **fields,
        }
        self._flush_meta()
        self.event("run_started", **fields)
        return self._meta

    def finish_meta(self, *, status: str, error: str | None = None, **summary: Any) -> dict[str, Any]:
        assert self._meta is not None, "init_meta() must be called first"
        self._meta["status"] = status
        self._meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if error:
            self._meta["error"] = error[:500]
        self._meta.update(summary)
        self._flush_meta()
        self.event("run_finished", status=status, error=error)
        return self._meta

    def _flush_meta(self) -> None:
        assert self._meta is not None
        self.meta_path.write_text(
            json.dumps(self._meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save_report(self, report: dict[str, Any]) -> None:
        self.report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.event("report_saved")


# ---------- 查询 ----------

def list_runs(limit: int = 200) -> list[dict[str, Any]]:
    if not RUNS_DIR.is_dir():
        return []
    items: list[tuple[str, dict[str, Any]]] = []
    for d in RUNS_DIR.iterdir():
        meta_file = d / "meta.json"
        if not d.is_dir() or not meta_file.is_file():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            items.append((d.name, meta))
        except (OSError, json.JSONDecodeError):
            continue
    items.sort(key=lambda kv: kv[0], reverse=True)
    return [meta for _, meta in items[:limit]]


def get_run(run_id: str) -> dict[str, Any] | None:
    d = RUNS_DIR / run_id
    if not d.is_dir():
        return None
    result: dict[str, Any] = {"id": run_id}
    for name in ("meta", "report"):
        p = d / f"{name}.json"
        if p.is_file():
            try:
                result[name] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result[name] = None
    trace_file = d / "trace.jsonl"
    if trace_file.is_file():
        events = []
        try:
            for line in trace_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        result["trace"] = events
    return result


def delete_run(run_id: str) -> bool:
    d = RUNS_DIR / run_id
    if not d.is_dir():
        return False
    import shutil

    shutil.rmtree(d, ignore_errors=True)
    return True


def prune_runs() -> int:
    """超过 MAX_RUNS 时清理最旧的已完成运行。"""
    if not RUNS_DIR.is_dir():
        return 0
    dirs = sorted((d for d in RUNS_DIR.iterdir() if d.is_dir()), key=lambda p: p.name)
    excess = len(dirs) - MAX_RUNS
    removed = 0
    for d in dirs[: max(0, excess)]:
        import shutil

        shutil.rmtree(d, ignore_errors=True)
        removed += 1
    return removed


def import_legacy_history(history_file: Path) -> int:
    """把旧版 Node.js 的 data/history.json 迁移为 runs 工件。"""
    if not history_file.is_file():
        return 0
    try:
        entries = json.loads(history_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(entries, list):
        return 0

    migrated = 0
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        run = RunTrace(str(entry["id"]))
        if run.meta_path.exists():
            continue
        created = str(entry.get("createdAt", ""))[:19]
        meta = {
            "id": run.id,
            "created_at": created,
            "finished_at": created,
            "status": "completed",
            "filename": entry.get("filename"),
            "language": entry.get("language"),
            "provider": "deepseek",
            "model": entry.get("model"),
            "focus": entry.get("focus", []),
            "line_count": entry.get("lineCount"),
            "elapsed_ms": entry.get("elapsedMs"),
            "score": entry.get("score", 0),
            "issue_count": entry.get("issueCount", 0),
            "summary": entry.get("summary", ""),
        }
        run._meta = meta  # noqa: SLF001 - 迁移场景直接写入
        run._flush_meta()
        report_keys = ("summary", "score", "highlights", "issues", "recommendations")
        run.save_report({k: entry[k] for k in report_keys if k in entry})
        migrated += 1
    return migrated
