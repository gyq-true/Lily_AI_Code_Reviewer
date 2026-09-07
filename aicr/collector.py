"""代码收集器：单文件、目录扫描、git diff 解析、多文件批量。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

EXT_LANG = {
    "js": "JavaScript", "jsx": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript",
    "ts": "TypeScript", "tsx": "TypeScript",
    "py": "Python", "java": "Java", "go": "Go", "rs": "Rust",
    "c": "C", "h": "C", "cpp": "C++", "hpp": "C++", "cc": "C++", "cs": "C#",
    "php": "PHP", "rb": "Ruby", "swift": "Swift", "kt": "Kotlin",
    "html": "HTML", "css": "CSS", "scss": "SCSS", "vue": "Vue",
    "sql": "SQL", "sh": "Shell", "bash": "Shell", "ps1": "PowerShell",
    "json": "JSON", "md": "Markdown", "yml": "YAML", "yaml": "YAML", "xml": "XML",
    "lua": "Lua", "pl": "Perl", "r": "R", "scala": "Scala", "dart": "Dart", "toml": "TOML",
}

SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".idea", ".vscode", ".pytest_cache", ".ruff_cache",
    "vendor", "target", ".next", ".nuxt", "coverage",
}


class CollectorError(ValueError):
    pass


@dataclass
class CollectedFile:
    path: str
    code: str
    language: str | None = None
    is_diff: bool = False
    meta: dict = field(default_factory=dict)


@dataclass
class SkippedFile:
    path: str
    reason: str


def guess_language(filename: str | None) -> str | None:
    if not filename:
        return None
    ext = Path(filename).suffix.lstrip(".").lower()
    return EXT_LANG.get(ext)


def collect_single(code: str, filename: str | None, language: str | None = None) -> CollectedFile:
    return CollectedFile(
        path=filename or "粘贴的代码",
        code=code,
        language=language or guess_language(filename),
    )


def collect_from_path(
    path: str | Path,
    *,
    extensions: list[str] | None = None,
    max_files: int = 30,
    max_file_bytes: int = 100_000,
    skipped: list[SkippedFile] | None = None,
) -> list[CollectedFile]:
    """扫描目录下可审查的文本文件；path 为单个文件时直接返回。

    跳过/超限的文件会写入 skipped（若传入），供上层向用户反馈。
    """
    root = Path(path)
    if not root.exists():
        raise CollectorError(f"路径不存在：{root}")

    if root.is_file():
        code = _read_text(root, max_file_bytes)
        if code is None:
            raise CollectorError(f"文件无法按文本读取或超过大小限制：{root}")
        return [CollectedFile(path=str(root), code=code, language=guess_language(root.name))]

    exts = {e.lower().lstrip(".") for e in (extensions or [])}
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if exts and p.suffix.lstrip(".").lower() not in exts:
            continue
        files.append(p)
        if len(files) >= max_files * 3:  # 预筛后仍需过滤大小，多收一些候选
            break

    results: list[CollectedFile] = []
    over_count = 0
    for f in files:
        if len(results) >= max_files:
            over_count += 1
            continue
        if f.stat().st_size > max_file_bytes:
            _add_skip(skipped, str(f), f"超过大小限制（>{max_file_bytes} 字节）")
            continue
        code = _read_text(f, max_file_bytes)
        if code is None:
            _add_skip(skipped, str(f), "二进制文件或无法按文本解码")
            continue
        results.append(CollectedFile(path=str(f), code=code, language=guess_language(f.name)))

    if over_count > 0:
        _add_skip(skipped, "(目录)", f"另有 {over_count} 个文件超过数量上限（{max_files}）被跳过")
    if not results:
        raise CollectorError(f"目录中未找到可审查的代码文件：{root}")
    return results


def _add_skip(skipped: list[SkippedFile] | None, path: str, reason: str) -> None:
    if skipped is not None:
        skipped.append(SkippedFile(path=path, reason=reason))


def _read_text(p: Path, max_bytes: int) -> str | None:
    try:
        if p.stat().st_size > max_bytes:
            return None
        raw = p.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:  # 二进制文件粗判
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            return None


# ---------- git diff ----------

def collect_git_diff(repo_path: str | Path, *, staged: bool = False) -> list[CollectedFile]:
    """收集仓库的未暂存/已暂存 diff，按文件拆分。"""
    repo = Path(repo_path)
    if not repo.is_dir():
        raise CollectorError(f"仓库路径不存在：{repo}")
    args = ["git", "-C", str(repo), "diff", "--no-color"]
    if staged:
        args.append("--cached")
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise CollectorError(f"执行 git 失败：{err}") from err
    if proc.returncode != 0:
        raise CollectorError(f"git diff 失败：{(proc.stderr or '').strip()[:300]}")
    diff_text = proc.stdout.strip()
    if not diff_text:
        raise CollectorError("没有检测到变更（git diff 为空）")
    return split_diff_by_file(diff_text)


def split_diff_by_file(diff_text: str) -> list[CollectedFile]:
    """把 unified diff 按文件拆分为多个待审片段。"""
    sections: list[tuple[str, list[str]]] = []
    current_file: str | None = None
    lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current_file:
                sections.append((current_file, lines))
            current_file = _parse_diff_path(line)
            lines = [line]
        elif current_file is not None:
            lines.append(line)
    if current_file:
        sections.append((current_file, lines))

    results: list[CollectedFile] = []
    for fname, body in sections:
        text = "\n".join(body).strip()
        # 跳过纯删除/重命名等没有新增行的变更
        has_added = any(
            line.startswith("+") and not line.startswith("+++") for line in body
        )
        if not has_added:
            continue
        results.append(
            CollectedFile(
                path=fname,
                code=text,
                language=guess_language(fname),
                is_diff=True,
                meta={"hint": "以下为该文件的 git diff 片段"},
            )
        )
    if not results:
        raise CollectorError("diff 中没有包含新增变更的文件")
    return results


def _parse_diff_path(diff_line: str) -> str:
    """从 'diff --git a/x.py b/x.py' 提取文件路径（处理含空格的简单场景）。"""
    rest = diff_line[len("diff --git "):]
    halves = rest.split(" b/")
    candidate = halves[-1] if len(halves) == 2 else rest
    return candidate.strip('"').removeprefix("b/")
