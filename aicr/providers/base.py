"""Provider 抽象基类。所有后端实现相同的 chat 接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx


class ProviderError(Exception):
    def __init__(self, message: str, status: int = 500, code: str = "PROVIDER_ERROR"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


@dataclass
class ChatResult:
    """一次对话的完整结果：文本 + 思考内容 + 可回传的 assistant 消息（用于多轮续写）。"""

    text: str
    reasoning: str = ""
    assistant_message: dict[str, Any] | None = None
    finish_reason: str | None = None
    raw: Any = None


# 触发"需要续写"的 finish_reason（OpenAI 用 length，Anthropic 用 max_tokens）
_TRUNCATED_REASONS = {"length", "max_tokens"}


def is_truncated(finish_reason: str | None) -> bool:
    """判断模型是否因 token 耗尽而中断（此时需要续写，而非当作完整回答）。"""
    return (finish_reason or "").lower() in _TRUNCATED_REASONS


class BaseProvider(ABC):
    """LLM 后端抽象。settings 段包含 base_url / model / api_key。"""

    name: str = "base"
    needs_key: bool = True

    def __init__(
        self,
        section: dict[str, str],
        *,
        temperature: float,
        max_tokens: int,
        timeout_ms: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = (section.get("base_url") or "").rstrip("/")
        self.default_model = section.get("model", "")
        self.api_key = section.get("api_key", "")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_ms = timeout_ms
        self._transport = transport

    def _require_key(self) -> None:
        if self.needs_key and not self.api_key:
            raise ProviderError(
                f"Provider '{self.name}' 尚未配置 API Key，请到设置页填写或在 .env 中配置",
                401,
                "NO_API_KEY",
            )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """发送对话并返回纯文本（向后兼容的单轮接口）。"""
        result = await self.chat_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        if not result.text:
            if result.reasoning:
                raise ProviderError(
                    f"{self.name} 在思考阶段耗尽 max_tokens（finish_reason={result.finish_reason}），"
                    "未产出正文。请调大 max_tokens，或改用多轮对话接口续写。",
                    502,
                    "EMPTY_RESPONSE",
                )
            raise ProviderError(f"{self.name} 返回内容为空", 502, "EMPTY_RESPONSE")
        return result.text

    @abstractmethod
    async def chat_full(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ChatResult:
        """发送对话并返回完整结果（含思考内容与可回传 assistant 消息）。"""

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_ms / 1000, transport=self._transport)

    @staticmethod
    def _raise_http_error(status: int, detail: str, name: str) -> None:
        hints = {
            401: "（API Key 无效或未授权，请到设置页检查）",
            402: "（账户余额不足）",
            404: "（接口地址或模型名不存在，请检查 base_url / model 配置）",
            429: "（请求过于频繁或超出配额，请稍后重试）",
        }
        hint = hints.get(status, "")
        raise ProviderError(f"{name} API 错误 [{status}]：{detail}{hint}", status, "API_ERROR")
