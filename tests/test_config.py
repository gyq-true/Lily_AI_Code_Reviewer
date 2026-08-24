"""dotenv 解析与配置优先级测试。"""

from __future__ import annotations

import json

from aicr.config import load_config, mask_secret, save_config
from aicr.dotenv import parse_env_text


def test_parse_env_basic():
    text = """
# 注释
CRV_PROVIDER=deepseek
export CRV_TEMPERATURE=0.7
QUOTED="hello world"
SINGLE='single val'
EMPTY=
INLINE=value # comment
BAD LINE WITHOUT EQUALS
"""
    parsed = parse_env_text(text)
    assert parsed["CRV_PROVIDER"] == "deepseek"
    assert parsed["CRV_TEMPERATURE"] == "0.7"
    assert parsed["QUOTED"] == "hello world"
    assert parsed["SINGLE"] == "single val"
    assert parsed["EMPTY"] == ""
    assert parsed["INLINE"] == "value"
    assert "BAD" not in json.dumps(parsed)


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret("short") == "****"
    masked = mask_secret("sk-1234567890abcdef")
    assert masked.startswith("sk-1") and masked.endswith("cdef")
    assert "67890" not in masked


def test_default_provider_is_deepseek(isolated_dirs):
    s = load_config()
    assert s.provider == "deepseek"
    assert s.providers["deepseek"]["base_url"] == "https://api.deepseek.com/v1"
    assert s.providers["deepseek"]["model"] == "deepseek-chat"


def test_legacy_flat_config_file(isolated_dirs, monkeypatch):
    """旧版 Node 项目 config.json（扁平 apiKey/model）应能被读取。"""
    cfg = isolated_dirs["config"]
    cfg.write_text(
        json.dumps(
            {
                "apiKey": "sk-legacy-key-123456",
                "model": "deepseek-reasoner",
                "apiBase": "https://api.deepseek.com/v1",
                "maxTokens": 2048,
                "timeoutMs": 60000,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = load_config()
    ds = s.for_provider("deepseek")
    assert ds["api_key"] == "sk-legacy-key-123456"
    assert ds["model"] == "deepseek-reasoner"
    assert s.max_tokens == 2048
    assert s.timeout_ms == 60000


def test_env_overrides_config_file(isolated_dirs, monkeypatch):
    """环境变量优先级高于 config.json。"""
    isolated_dirs["config"].write_text(json.dumps({"apiKey": "sk-from-file"}), encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    s = load_config()
    assert s.for_provider("deepseek")["api_key"] == "sk-from-env"


def test_save_config_sections_and_roundtrip(isolated_dirs):
    save_config({"provider": "openai", "openai": {"api_key": "sk-oai", "model": "gpt-4o-mini"}})
    save_config({"temperature": 0.8})
    s = load_config()
    assert s.provider == "openai"
    assert s.for_provider("openai")["api_key"] == "sk-oai"
    assert s.temperature == 0.8
    # deepseek 段不受影响
    assert s.for_provider("deepseek")["api_key"] == ""


def test_public_settings_masks_keys(isolated_dirs, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-abcdef123456")
    from aicr.config import get_public_settings

    data = get_public_settings()
    assert data["providers"]["deepseek"]["has_api_key"] is True
    assert "secret" not in data["providers"]["deepseek"]["api_key_masked"]
