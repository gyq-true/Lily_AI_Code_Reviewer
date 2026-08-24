"""Anthropic Messages 协议（/v1/messages，x-api-key 鉴权）。"""

from __future__ import annotations

import httpx

from .base import BaseProvider, ChatResult, ProviderError

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(BaseProvider):
    name = "anthropic"

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
        url = f"{self.base_url}/v1/messages"

        system_text = "\n\n".join(
            m["content"]
            for m in messages
            if m["role"] == "system" and isinstance(m.get("content"), str)
        )
        # 历史 assistant 消息（含 thinking 块 + signature）原样透传，用于多轮续写
        chat_messages = [m for m in messages if m["role"] != "system"]

        body: dict = {
            "model": model or self.default_model,
            "messages": chat_messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if system_text:
            body["system"] = system_text
        # Anthropic 无 response_format，JSON 输出依赖提示词约束
        _ = json_mode

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

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
            try:
                detail = str(resp.json().get("error", {}).get("message", ""))[:500]
            except ValueError:
                detail = resp.text[:500]
            self._raise_http_error(resp.status_code, detail, self.name)

        data = resp.json()
        blocks = data.get("content") or []

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        for block in blocks:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text", "")))
            elif btype == "thinking":
                reasoning_parts.append(str(block.get("thinking", "")))

        text = "".join(text_parts).strip()
        reasoning = "".join(reasoning_parts).strip()
        finish_reason = data.get("stop_reason")

        if not text and not reasoning:
            raise ProviderError(f"{self.name} 返回内容为空", 502, "EMPTY_RESPONSE")

        # 完整保留原始 content 块（含 thinking 块的 signature），供下一轮原样回传
        assistant = {"role": "assistant", "content": list(blocks)}

        return ChatResult(
            text=text,
            reasoning=reasoning,
            assistant_message=assistant,
            finish_reason=finish_reason,
            raw=data,
        )
