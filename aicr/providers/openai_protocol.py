"""OpenAI Chat Completions 兼容协议（DeepSeek / OpenAI / Ollama 均走此协议）。"""

from __future__ import annotations

from typing import Any

import httpx

from .base import BaseProvider, ChatResult, ProviderError


class OpenAICompatProvider(BaseProvider):
    async def chat_full(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ChatResult:
        self._require_key()
        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with self._client() as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as err:
            raise ProviderError(
                f"请求 {self.name} 超时（{self.timeout_ms}ms），可在设置中调大超时",
                504,
                "TIMEOUT",
            ) from err
        except httpx.HTTPError as err:
            raise ProviderError(f"无法连接到 {self.name}：{err}", 502, "NETWORK") from err

        if resp.status_code != 200:
            detail = _extract_error_detail(resp)
            self._raise_http_error(resp.status_code, detail, self.name)

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        content = message.get("content")
        # 思考型模型（DeepSeek R1 / o1 等）把推理放在 reasoning_content
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        finish_reason = choice.get("finish_reason")

        text = str(content).strip() if content is not None else ""
        reasoning = str(reasoning or "")

        if not text and not reasoning:
            raise ProviderError(f"{self.name} 返回内容为空", 502, "EMPTY_RESPONSE")

        # DeepSeek R1 / OpenAI o1 不建议在后续请求回传 reasoning_content（模型会重新生成），
        # 故 assistant 消息仅保留 content；思考文本只通过 ChatResult.reasoning 暴露给上层。
        assistant: dict[str, Any] = {"role": "assistant", "content": text}

        return ChatResult(
            text=text,
            reasoning=reasoning,
            assistant_message=assistant,
            finish_reason=finish_reason,
            raw=data,
        )


def _extract_error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return str(data.get("error", {}).get("message") or data)[:500]
    except ValueError:
        return resp.text[:500]
