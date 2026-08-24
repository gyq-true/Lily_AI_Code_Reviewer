"""测试全局夹具：把配置/数据目录隔离到临时路径，避免污染真实环境。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="aicr-tests-"))
os.environ["CRV_CONFIG_FILE"] = str(_TMP / "config.json")
os.environ["CRV_DATA_DIR"] = str(_TMP / "data")
os.environ["CRV_ENV_FILE"] = str(_TMP / ".env-nonexistent")
# 清掉可能干扰的 key 环境变量
for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_BASE"):
    os.environ.pop(name, None)


@pytest.fixture()
def isolated_dirs(tmp_path, monkeypatch):
    """每个用例独立的 config/data 目录。"""
    cfg = tmp_path / "config.json"
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("aicr.config.CONFIG_FILE", cfg)
    monkeypatch.setattr("aicr.runs.RUNS_DIR", data / "runs")
    return {"config": cfg, "data": data}
