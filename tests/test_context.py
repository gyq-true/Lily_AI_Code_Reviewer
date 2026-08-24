"""上下文管理测试：token 估算、预算裁剪、imports 提取。"""

from __future__ import annotations

from aicr.context import estimate_tokens, extract_imports, fit_to_budget, truncate_for_query


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") >= 1
    # 每 2 字符约 1 token
    assert estimate_tokens("a" * 100) == 50


def test_fit_to_budget_respects_limit():
    chunks = [
        {"score": 0.9, "payload": {"source": "a.md", "kind": "doc", "text": "x" * 100}},
        {"score": 0.5, "payload": {"source": "b.py", "kind": "code", "text": "y" * 100}},
    ]
    result = fit_to_budget(chunks, max_chars=120, header="头")
    assert len(result) <= 120
    assert "a.md" in result


def test_fit_to_budget_sorts_by_score_desc():
    chunks = [
        {"score": 0.1, "payload": {"source": "low", "kind": "doc", "text": "LOW"}},
        {"score": 0.9, "payload": {"source": "high", "kind": "doc", "text": "HIGH"}},
    ]
    result = fit_to_budget(chunks, max_chars=200)
    assert result.index("high") < result.index("low")


def test_extract_imports_python():
    code = "import os\nfrom pathlib import Path\nimport sys, re\n"
    imports = extract_imports(code, "Python")
    assert "os" in imports
    assert "pathlib" in imports


def test_extract_imports_javascript():
    code = "import React from 'react';\nconst fs = require('fs');\n"
    imports = extract_imports(code, "JavaScript")
    assert "react" in imports
    assert "fs" in imports


def test_extract_imports_dedup():
    code = "import os\nimport os\n"
    assert extract_imports(code, "Python") == ["os"]


def test_truncate_for_query():
    assert len(truncate_for_query("a" * 5000)) == 2000
