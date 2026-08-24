"""Provider 层测试：请求构造、响应解析、错误处理（全部走 MockTransport，无真实网络）。"""

from __future__ import annotations

import json

import httpx
import pytest

from aicr.providers import ProviderError, build_provider
from aicr.providers.anthropic_protocol import AnthropicProvider
from aicr.providers.openai_protocol import OpenAICompatProvider

SECTION = {"base_url": "https://mock.example/v1", "model": "test-model", "api_key": "sk-test"}


def make_kwargs(transport):
    return dict(temperature=0.3, max_tokens=1024, timeout_ms=30000, transport=transport)


@pytest.mark.asyncio
async def test_openai_protocol_request_and_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello review"}}]},
        )

    provider = OpenAICompatProvider(SECTION, **make_kwargs(httpx.MockTransport(handler)))
    text = await provider.chat([{"role": "user", "content": "hi"}], json_mode=True)

    assert text == "hello review"
    assert captured["url"] == "https://mock.example/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_openai_protocol_http_error_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    provider = OpenAICompatProvider(SECTION, **make_kwargs(httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        await provider.chat([{"role": "user", "content": "hi"}])
    assert exc.value.status == 401
    assert "API Key" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_protocol_requires_key():
    section = {**SECTION, "api_key": ""}
    provider = OpenAICompatProvider(section, **make_kwargs(httpx.MockTransport(None)))
    with pytest.raises(ProviderError) as exc:
        await provider.chat([{"role": "user", "content": "hi"}])
    assert exc.value.code == "NO_API_KEY"


@pytest.mark.asyncio
async def test_anthropic_protocol_maps_system_and_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "anthropic reply"}]}
        )

    provider = AnthropicProvider(
        {**SECTION, "base_url": "https://mock.example"},
        **make_kwargs(httpx.MockTransport(handler)),
    )
    text = await provider.chat(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user prompt"},
        ]
    )
    assert text == "anthropic reply"
    assert captured["url"] == "https://mock.example/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    # system 被提升到顶层字段，messages 只含对话消息
    assert captured["body"]["system"] == "system prompt"
    assert [m["role"] for m in captured["body"]["messages"]] == ["user"]


def test_registry_builds_provider(isolated_dirs):
    from aicr.config import load_config

    s = load_config()
    p = build_provider(s, "deepseek")
    assert isinstance(p, OpenAICompatProvider)
    with pytest.raises(ProviderError):
        build_provider(s, "no-such-provider")


def test_ollama_needs_no_key(isolated_dirs):
    from aicr.config import load_config

    s = load_config()
    p = build_provider(s, "ollama")
    assert p.needs_key is False or not p.api_key  # ollama 无 key 也可调用


def test_available_providers_contains_four():
    from aicr.providers import available_providers

    assert set(available_providers()) == {"deepseek", "openai", "anthropic", "ollama"}
