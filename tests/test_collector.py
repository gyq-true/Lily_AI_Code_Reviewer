"""收集器测试：目录扫描、过滤规则、diff 拆分。"""

from __future__ import annotations

import subprocess

import pytest

from aicr.collector import (
    CollectorError,
    collect_from_path,
    collect_git_diff,
    guess_language,
    split_diff_by_file,
)


def test_guess_language():
    assert guess_language("a.py") == "Python"
    assert guess_language("b.TS") == "TypeScript"
    assert guess_language("noext") is None


def test_collect_single_file(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("print('hi')", encoding="utf-8")
    items = collect_from_path(f)
    assert len(items) == 1
    assert items[0].language == "Python"


def test_collect_directory_with_filters(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.js").write_text("let x=1;\n", encoding="utf-8")
    # 应跳过的内容
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "c.js").write_text("junk\n", encoding="utf-8")
    (tmp_path / "big.py").write_text("x" * 200_000, encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02binary")

    only_py = collect_from_path(tmp_path, extensions=["py"], max_files=10, max_file_bytes=1000)
    paths = [i.path for i in only_py]
    assert any(p.endswith("a.py") for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any("big.py" in p for p in paths)  # 超过大小上限
    assert not any("bin.dat" in p for p in paths)

    all_files = collect_from_path(tmp_path, max_files=30, max_file_bytes=150_000)
    assert len(all_files) >= 2


def test_collect_missing_path_raises(tmp_path):
    with pytest.raises(CollectorError):
        collect_from_path(tmp_path / "not-exist")


def test_collect_directory_reports_skipped(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "big.py").write_text("x" * 200_000, encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02binary")

    skipped = []
    items = collect_from_path(tmp_path, max_files=10, max_file_bytes=1000, skipped=skipped)
    assert len(items) == 1
    from pathlib import Path as _P
    reasons = {_P(s.path).name: s.reason for s in skipped}
    assert "big.py" in reasons and "大小" in reasons["big.py"]
    assert "bin.dat" in reasons and "二进制" in reasons["bin.dat"]


def test_collect_directory_reports_count_overflow(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text(f"x{i} = 1\n", encoding="utf-8")
    skipped = []
    items = collect_from_path(tmp_path, max_files=2, skipped=skipped)
    assert len(items) == 2
    assert any("数量上限" in s.reason for s in skipped)


SAMPLE_DIFF = """diff --git a/app/main.py b/app/main.py
index 1111111..2222222 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,3 +1,4 @@
 import os
+import sys
 def main():
     pass
diff --git a/docs/readme.md b/docs/renamed.md
similarity index 100%
rename from docs/readme.md
rename to docs/renamed.md
"""


def test_split_diff_by_file():
    items = split_diff_by_file(SAMPLE_DIFF)
    assert len(items) == 1
    item = items[0]
    assert item.path == "app/main.py"
    assert item.is_diff is True
    assert item.language == "Python"
    assert "+import sys" in item.code


def test_split_diff_empty_additions_raises():
    delete_only = """diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-old line 1
-old line 2
"""
    with pytest.raises(CollectorError):
        split_diff_by_file(delete_only)


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git 不可用",
)
def test_collect_git_diff_real_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env_git = ["git", "-C", str(repo)]
    subprocess.run([*env_git, "init", "-q"], capture_output=True, check=True)
    subprocess.run([*env_git, "config", "user.email", "t@t"], capture_output=True, check=True)
    subprocess.run([*env_git, "config", "user.name", "t"], capture_output=True, check=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([*env_git, "add", "."], capture_output=True, check=True)
    subprocess.run([*env_git, "commit", "-qm", "init"], capture_output=True, check=True)

    # 无变更时报错
    with pytest.raises(CollectorError):
        collect_git_diff(repo)

    # 修改已跟踪文件 → 未暂存 diff
    (repo / "a.py").write_text("x = 100\n", encoding="utf-8")
    items = collect_git_diff(repo)
    assert [i.path for i in items] == ["a.py"]

    # 已暂存模式：暂存 a.py，再新建未跟踪 b.py，staged 只看 a.py
    subprocess.run([*env_git, "add", "a.py"], capture_output=True, check=True)
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    staged = collect_git_diff(repo, staged=True)
    assert [i.path for i in staged] == ["a.py"]
