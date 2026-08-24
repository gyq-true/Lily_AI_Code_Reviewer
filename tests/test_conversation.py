"""多轮对话与思考型模型支持：历史保留、签名回传、max_tokens 自动续写。"""

from __future__ import annotations

import httpx
import pytest

from aicr.conversation import CONTINUE_PROMPT, Conversation
from aicr.providers import ProviderError
from aicr.providers.anthropic_protocol import AnthropicProvider
from aicr.providers.base import ChatResult
from aicr.providers.openai_protocol import OpenAICompatProvider

SECTION = {"base_url": "https://mock.example/v1", "model": "test-model", "api_key": "sk-test"}


def make_kwargs(transport):
    return dict(temperature=0.3, max_tokens=1024, timeout_ms=30000, transport=transport)


class ScriptedProvider:
    """按顺序吐出预设 ChatResult 的假 provider，记录每次收到的消息历史。"""

    name = "scripted"
    default_model = "test-model"

    def __init__(self, results: list[ChatResult]):
        self.results = list(results)
        self.calls: list[list[dict]] = []

    async def chat_full(self, messages, *, model=None, temperature=None, max_tokens=None, json_mode=False):
        self.calls.append([dict(m) for m in messages])
        return self.results.pop(0)


def _anthropic_assistant(blocks):
    return {"role": "assistant", "content": blocks}


# ---------- 自动续写 ----------

@pytest.mark.asyncio
async def test_auto_continue_on_truncation():
    first = ChatResult(
        text="部分",
        reasoning="思考中",
        assistant_message={"role": "assistant", "content": "部分"},
        finish_reason="length",
    )
    second = ChatResult(
        text="续写",
        reasoning="",
        assistant_message={"role": "assistant", "content": "续写"},
        finish_reason="stop",
    )
    prov = ScriptedProvider([first, second])
    conv = Conversation(prov)
    result = await conv.ask("hi")

    assert result.text == "部分续写"
    assert len(prov.calls) == 2
    # 续写请求以 user "continue" 结尾（否则 OpenAI/Anthropic 会因非 user 结尾而中断）
    assert prov.calls[1][-1]["role"] == "user"
    assert prov.calls[1][-1]["content"] == CONTINUE_PROMPT
    # 历史保持单轮干净：不残留 continue 提示
    assert [m["role"] for m in conv.messages] == ["user", "assistant"]
    assert conv.messages[-1]["content"] == "部分续写"


@pytest.mark.asyncio
async def test_anthropic_continue_keeps_thinking_before_text():
    first = ChatResult(
        text="a",
        reasoning="think1",
        assistant_message=_anthropic_assistant(
            [{"type": "thinking", "thinking": "think1", "signature": "sig1"}, {"type": "text", "text": "a"}]
        ),
        finish_reason="max_tokens",
    )
    second = ChatResult(
        text="b",
        reasoning="think2",
        assistant_message=_anthropic_assistant(
            [{"type": "thinking", "thinking": "think2", "signature": "sig2"}, {"type": "text", "text": "b"}]
        ),
        finish_reason="end_turn",
    )
    prov = ScriptedProvider([first, second])
    conv = Conversation(prov)
    result = await conv.ask("q")

    assert result.text == "ab"
    blocks = conv.messages[-1]["content"]
    # 合并后：thinking 块（含签名）仍位于 text 之前
    assert blocks[0]["type"] == "thinking"
    assert blocks[0]["signature"] == "sig1"
    types = [b["type"] for b in blocks]
    assert types.index("thinking") < types.index("text")


# ---------- 多轮历史与思考块签名回传 ----------

@pytest.mark.asyncio
async def test_thinking_signature_preserved_across_turns():
    first = ChatResult(
        text="a",
        reasoning="think1",
        assistant_message=_anthropic_assistant(
            [{"type": "thinking", "thinking": "think1", "signature": "sig1"}, {"type": "text", "text": "a"}]
        ),
        finish_reason="end_turn",
    )
    second = ChatResult(
        text="b",
        reasoning="think2",
        assistant_message=_anthropic_assistant(
            [{"type": "thinking", "thinking": "think2", "signature": "sig2"}, {"type": "text", "text": "b"}]
        ),
        finish_reason="end_turn",
    )
    prov = ScriptedProvider([first, second])
    conv = Conversation(prov)
    await conv.ask("q1")
    await conv.ask("q2")

    second_turn = prov.calls[1]
    assistant_msgs = [m for m in second_turn if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    # 上一轮的 thinking 块 + 签名原样回传
    assert assistant_msgs[0]["content"][0]["type"] == "thinking"
    assert assistant_msgs[0]["content"][0]["signature"] == "sig1"


# ---------- Provider 层：思考内容解析 ----------

@pytest.mark.asyncio
async def test_openai_reasoning_kept_out_of_assistant_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "answer", "reasoning_content": "hidden reasoning"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    provider = OpenAICompatProvider(SECTION, **make_kwargs(httpx.MockTransport(handler)))
    result = await provider.chat_full([{"role": "user", "content": "hi"}])

    assert result.text == "answer"
    assert result.reasoning == "hidden reasoning"
    # reasoning_content 不应出现在待回传的 assistant 消息中（DeepSeek R1 / o1 不建议回传）
    assert "reasoning_content" not in result.assistant_message


@pytest.mark.asyncio
async def test_openai_truncated_thinking_raises_actionable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "", "reasoning_content": "推理中……"},
                        "finish_reason": "length",
                    }
                ]
            },
        )

    provider = OpenAICompatProvider(SECTION, **make_kwargs(httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        await provider.chat([{"role": "user", "content": "hi"}])
    assert "max_tokens" in str(exc.value)


@pytest.mark.asyncio
async def test_anthropic_thinking_blocks_preserved():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "thinking", "thinking": "hmm", "signature": "sig-x"},
                    {"type": "text", "text": "reply"},
                ],
                "stop_reason": "end_turn",
            },
        )

    provider = AnthropicProvider(
        {**SECTION, "base_url": "https://mock.example"},
        **make_kwargs(httpx.MockTransport(handler)),
    )
    result = await provider.chat_full([{"role": "user", "content": "hi"}])

    assert result.text == "reply"
    assert result.reasoning == "hmm"
    assert result.assistant_message["content"][0]["signature"] == "sig-x"
