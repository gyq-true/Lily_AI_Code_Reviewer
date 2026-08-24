"""Provider 注册表：按名称构建后端实例（PICO 式 provider 工厂）。"""

from __future__ import annotations

from ..config import Settings
from .anthropic_protocol import AnthropicProvider
from .base import BaseProvider, ChatResult, ProviderError, is_truncated
from .openai_protocol import OpenAICompatProvider

_REGISTRY: dict[str, type[BaseProvider]] = {
    "deepseek": OpenAICompatProvider,
    "openai": OpenAICompatProvider,
    "ollama": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
}


def available_providers() -> list[str]:
    return list(_REGISTRY)


def build_provider(settings: Settings, name: str | None = None) -> BaseProvider:
    provider_name = (name or settings.provider).lower()
    cls = _REGISTRY.get(provider_name)
    if cls is None:
        raise ProviderError(
            f"未知 provider: {provider_name}，可选：{', '.join(_REGISTRY)}", 400, "BAD_PROVIDER"
        )
    section = settings.providers.get(provider_name)
    if not section:
        raise ProviderError(f"provider '{provider_name}' 缺少配置段", 500, "NO_SECTION")
    instance = cls(
        section,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout_ms=settings.timeout_ms,
    )
    # 修正实例级 name（此前 OpenAI 兼容 provider 的 name 恒为 "base"），
    # 并让 ollama 免 Key（本地模型无需鉴权）。
    instance.name = provider_name
    if provider_name == "ollama":
        instance.needs_key = False
    return instance


__all__ = [
    "BaseProvider",
    "ChatResult",
    "ProviderError",
    "build_provider",
    "available_providers",
    "is_truncated",
]
