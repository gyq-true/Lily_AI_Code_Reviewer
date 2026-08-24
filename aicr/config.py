"""配置管理：优先级链为 请求参数 > .env > 环境变量 > config.json > 内置默认值。

环境变量命名遵循 PICO 风格：CRV_ 前缀，并回退到无前缀的通用名称。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(os.environ.get("CRV_CONFIG_FILE", APP_DIR / "config.json"))
DATA_DIR = Path(os.environ.get("CRV_DATA_DIR", APP_DIR / "data"))
ENV_FILE = Path(os.environ.get("CRV_ENV_FILE", APP_DIR / ".env"))

DEFAULT_PROVIDER = "deepseek"

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "label": "DeepSeek（V3/R1，推荐）",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "label": "OpenAI 兼容服务",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-3-5-haiku-20241022",
        "label": "Anthropic 兼容服务",
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5-coder:7b",
        "label": "Ollama 本地模型（免 Key）",
    },
}

# 每个 provider 的环境变量名（CRV_ 前缀 → 通用回退名）
PROVIDER_ENV_KEYS: dict[str, dict[str, tuple[str, str]]] = {
    "deepseek": {
        "api_key": ("CRV_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        "base_url": ("CRV_DEEPSEEK_API_BASE", "DEEPSEEK_API_BASE"),
        "model": ("CRV_DEEPSEEK_MODEL", "DEEPSEEK_MODEL"),
    },
    "openai": {
        "api_key": ("CRV_OPENAI_API_KEY", "OPENAI_API_KEY"),
        "base_url": ("CRV_OPENAI_API_BASE", "OPENAI_API_BASE"),
        "model": ("CRV_OPENAI_MODEL", "OPENAI_MODEL"),
    },
    "anthropic": {
        "api_key": ("CRV_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        "base_url": ("CRV_ANTHROPIC_API_BASE", "ANTHROPIC_API_BASE"),
        "model": ("CRV_ANTHROPIC_MODEL", "ANTHROPIC_MODEL"),
    },
    # ollama 不需要 key
    "ollama": {
        "base_url": ("CRV_OLLAMA_HOST", "OLLAMA_HOST"),
        "model": ("CRV_OLLAMA_MODEL", "OLLAMA_MODEL"),
    },
}

GENERAL_ENV_KEYS: dict[str, tuple[str, str]] = {
    "provider": ("CRV_PROVIDER",),
    "temperature": ("CRV_TEMPERATURE",),
    "max_tokens": ("CRV_MAX_TOKENS",),
    "timeout_ms": ("CRV_TIMEOUT_MS",),
    "review_mode": ("CRV_REVIEW_MODE",),
}

KB_ENV_KEYS: dict[str, tuple[str, str]] = {
    "enabled": ("CRV_KB_ENABLED",),
    "qdrant_url": ("CRV_KB_QDRANT_URL",),
    "qdrant_path": ("CRV_KB_QDRANT_PATH",),
    "qdrant_api_key": ("CRV_KB_QDRANT_API_KEY",),
    "collection": ("CRV_KB_COLLECTION",),
    "embedding_model": ("CRV_KB_EMBEDDING_MODEL",),
    "top_k": ("CRV_KB_TOP_K",),
    "chunk_size": ("CRV_KB_CHUNK_SIZE",),
    "chunk_overlap": ("CRV_KB_CHUNK_OVERLAP",),
}

KB_SCALAR_KEYS = (
    "kb_enabled",
    "kb_qdrant_url",
    "kb_qdrant_path",
    "kb_qdrant_api_key",
    "kb_collection",
    "kb_embedding_model",
    "kb_top_k",
    "kb_chunk_size",
    "kb_chunk_overlap",
)


@dataclass
class Settings:
    provider: str = DEFAULT_PROVIDER
    providers: dict[str, dict[str, str]] = field(default_factory=dict)
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout_ms: int = 120000
    review_mode: str = "single"

    kb_enabled: bool = False
    kb_qdrant_url: str = ""
    kb_qdrant_path: str = ""
    kb_qdrant_api_key: str = ""
    kb_collection: str = "aicr_kb"
    kb_embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    kb_top_k: int = 5
    kb_chunk_size: int = 800
    kb_chunk_overlap: int = 100

    def for_provider(self, name: str | None = None) -> dict[str, str]:
        return self.providers[name or self.provider]


def _env_first(*names: str) -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return ""


def load_config() -> Settings:
    """按优先级链解析配置。.env 已在进程启动时加载并覆盖同名环境变量。"""
    if ENV_FILE.is_file():
        load_dotenv(ENV_FILE)

    file_cfg = _read_config_file()

    settings = Settings()
    settings.provider = (
        _env_first(*GENERAL_ENV_KEYS["provider"])
        or file_cfg.get("provider")
        or DEFAULT_PROVIDER
    ).lower()
    if settings.provider not in PROVIDER_DEFAULTS:
        settings.provider = DEFAULT_PROVIDER

    for pname, defaults in PROVIDER_DEFAULTS.items():
        section: dict[str, str] = {"label": defaults["label"]}
        env_keys = PROVIDER_ENV_KEYS[pname]
        # 文件中的旧字段兼容：apiKey/apiBase/model 视为 deepseek 段
        legacy = {}
        if pname == "deepseek":
            legacy = {
                "api_key": file_cfg.get("apiKey", ""),
                "base_url": file_cfg.get("apiBase", ""),
                "model": file_cfg.get("model", ""),
            }
        file_section = file_cfg.get(pname, {})
        if isinstance(file_section, str):
            try:
                file_section = json.loads(file_section)
            except json.JSONDecodeError:
                file_section = {}
        for field_name in ("api_key", "base_url", "model"):
            names = env_keys.get(field_name, ())
            value = _env_first(*names) if names else ""
            if not value:
                value = (file_section or {}).get(field_name) or legacy.get(field_name) or ""
            section[field_name] = str(value or "")
        if not section["base_url"]:
            section["base_url"] = defaults["base_url"]
        if not section["model"]:
            section["model"] = defaults["model"]
        settings.providers[pname] = section

    def _num(env_names: tuple[str, ...], file_keys: tuple[str, ...], default: Any, cast):
        raw = _env_first(*env_names)
        if not raw:
            for k in file_keys:
                if file_cfg.get(k) is not None:
                    raw = file_cfg[k]
                    break
        try:
            return cast(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    settings.temperature = _num(GENERAL_ENV_KEYS["temperature"], ("temperature",), 0.3, float)
    settings.max_tokens = _num(
        GENERAL_ENV_KEYS["max_tokens"], ("max_tokens", "maxTokens"), 4096, int
    )
    settings.timeout_ms = _num(
        GENERAL_ENV_KEYS["timeout_ms"], ("timeout_ms", "timeoutMs"), 120000, int
    )
    mode = (
        _env_first(*GENERAL_ENV_KEYS["review_mode"])
        or file_cfg.get("review_mode")
        or "single"
    ).lower()
    settings.review_mode = mode if mode in ("single", "multi") else "single"

    def _s(env_names: tuple[str, ...], file_key: str, default: str) -> str:
        v = _env_first(*env_names)
        if not v:
            v = file_cfg.get(file_key, "")
        return str(v or default)

    def _b(env_names: tuple[str, ...], file_key: str, default: bool = False) -> bool:
        v = _env_first(*env_names)
        if v == "":
            v = file_cfg.get(file_key, default)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    settings.kb_enabled = _b(KB_ENV_KEYS["enabled"], "kb_enabled", False)
    settings.kb_qdrant_url = _s(KB_ENV_KEYS["qdrant_url"], "kb_qdrant_url", "")
    settings.kb_qdrant_path = _s(KB_ENV_KEYS["qdrant_path"], "kb_qdrant_path", "")
    settings.kb_qdrant_api_key = _s(KB_ENV_KEYS["qdrant_api_key"], "kb_qdrant_api_key", "")
    settings.kb_collection = _s(KB_ENV_KEYS["collection"], "kb_collection", "aicr_kb")
    settings.kb_embedding_model = _s(
        KB_ENV_KEYS["embedding_model"], "kb_embedding_model", "paraphrase-multilingual-MiniLM-L12-v2"
    )
    settings.kb_top_k = _num(KB_ENV_KEYS["top_k"], ("kb_top_k",), 5, int)
    settings.kb_chunk_size = _num(KB_ENV_KEYS["chunk_size"], ("kb_chunk_size",), 800, int)
    settings.kb_chunk_overlap = _num(
        KB_ENV_KEYS["chunk_overlap"], ("kb_chunk_overlap",), 100, int
    )
    return settings


def _read_config_file() -> dict[str, Any]:
    try:
        if CONFIG_FILE.is_file():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError) as err:
        print(f"[config] 读取 {CONFIG_FILE} 失败: {err}")
    return {}


def save_config(patch: dict[str, Any]) -> None:
    """Web 设置页保存（写入 config.json，位于优先级链的低层）。

    支持两种写法：
    - 分 provider 段：{"deepseek": {"api_key": "...", "base_url": "..."}, ...}
    - 旧版扁平字段：{"apiKey": "...", "apiBase": "...", "model": "..."}（视为 deepseek 段）
    """
    current = _read_config_file()
    merged: dict[str, Any] = {**current}
    provider = str(patch.get("provider") or current.get("provider") or DEFAULT_PROVIDER)

    for name in PROVIDER_DEFAULTS:
        section = patch.get(name)
        if isinstance(section, dict) and section:
            base = merged.get(name) if isinstance(merged.get(name), dict) else {}
            clean = {k: v for k, v in section.items() if isinstance(v, str) and v.strip()}
            merged[name] = {**base, **clean}

    # 旧版扁平字段 → 归入当前 provider 段（仅 deepseek 场景）
    flat_map = {"apiKey": "api_key", "apiBase": "base_url", "model": "model"}
    for flat_key, section_key in flat_map.items():
        value = patch.get(flat_key)
        if provider == "deepseek" and isinstance(value, str) and value.strip():
            ds = merged.get("deepseek") if isinstance(merged.get("deepseek"), dict) else {}
            ds[section_key] = value.strip()
            merged["deepseek"] = ds

    for key in ("provider", "temperature", "max_tokens", "timeout_ms", "review_mode", *KB_SCALAR_KEYS):
        if key in patch and patch[key] is not None:
            merged[key] = patch[key]

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def get_public_settings() -> dict[str, Any]:
    s = load_config()
    return {
        "provider": s.provider,
        "providers": {
            name: {
                "label": sec["label"],
                "base_url": sec["base_url"],
                "model": sec["model"],
                "needs_key": name != "ollama",
                "has_api_key": bool(sec.get("api_key")),
                "api_key_masked": mask_secret(sec.get("api_key", "")),
            }
            for name, sec in s.providers.items()
        },
        "temperature": s.temperature,
        "max_tokens": s.max_tokens,
        "timeout_ms": s.timeout_ms,
        "review_mode": s.review_mode,
        "kb": {
            "enabled": s.kb_enabled,
            "qdrant_url": s.kb_qdrant_url,
            "qdrant_path": s.kb_qdrant_path,
            "has_qdrant_api_key": bool(s.kb_qdrant_api_key),
            "qdrant_api_key_masked": mask_secret(s.kb_qdrant_api_key),
            "collection": s.kb_collection,
            "embedding_model": s.kb_embedding_model,
            "top_k": s.kb_top_k,
            "chunk_size": s.kb_chunk_size,
            "chunk_overlap": s.kb_chunk_overlap,
        },
    }
