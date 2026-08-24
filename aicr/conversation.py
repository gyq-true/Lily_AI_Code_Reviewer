"""多轮对话管理器：维护历史、保留思考块与签名、处理 max_tokens 自动续写。

思考型模型（Claude thinking / DeepSeek R1 等）在多轮场景下有两个关键点：
1. 上一轮的思考内容（thinking 块 / reasoning_content）必须连同签名原样回传，
   否则会出现 issue #1575 描述的 "Expected thinking..." 400 或思考中断。
2. 当 max_tokens 在思考阶段耗尽时（finish_reason = length / max_tokens），
   不能把半截回答当作完整结果，而应带上下文续写。
"""

from __future__ import annotations

from typing import Any

from .config import load_config
from .providers import BaseProvider, build_provider
from .providers.base import ChatResult, is_truncated

# 续写提示：模型因 max_tokens 截断时，用一条用户消息提示其继续（issue #1575 的 synthetic continue 思路）
CONTINUE_PROMPT = "continue"


class Conversation:
    """持有 provider 原生消息历史的对话会话。"""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        model: str | None = None,
        system: str | None = None,
        max_continue_turns: int = 4,
    ):
        self.provider = provider
        self.model = model or provider.default_model
        self.system = system
        self.max_continue_turns = max_continue_turns
        self.messages: list[dict[str, Any]] = []
        if self.system is not None:
            self.messages.append({"role": "system", "content": self.system})

    @classmethod
    def create(
        cls,
        provider_name: str | None = None,
        model: str | None = None,
        system: str | None = None,
    ) -> Conversation:
        settings = load_config()
        provider = build_provider(settings, provider_name)
        return cls(provider, model=model, system=system)

    async def ask(self, user_text: str, *, json_mode: bool = False) -> ChatResult:
        """追加用户消息并返回本轮完整回答（含思考内容）。

        若模型因 max_tokens 耗尽而中断，会自动带上下文续写至完整或达到上限。
        """
        self.messages.append({"role": "user", "content": user_text})

        result = await self._call(json_mode=json_mode)
        self._append_assistant(result)

        text_acc = result.text
        reasoning_acc = result.reasoning

        turns = 0
        while is_truncated(result.finish_reason) and turns < self.max_continue_turns:
            # 追加续写提示触发模型继续（消息需以 user 结尾，否则 API 会报错/中断）
            self.messages.append({"role": "user", "content": CONTINUE_PROMPT})
            cont = await self._call(json_mode=json_mode)
            self.messages.pop()  # 移除临时续写提示，保持单轮干净
            self._merge_last_assistant(cont)
            text_acc += cont.text
            reasoning_acc += cont.reasoning
            result = ChatResult(
                text=text_acc,
                reasoning=reasoning_acc,
                assistant_message=self.messages[-1],
                finish_reason=cont.finish_reason,
                raw=cont.raw,
            )
            turns += 1

        return result

    async def _call(self, *, json_mode: bool = False) -> ChatResult:
        return await self.provider.chat_full(self.messages, model=self.model, json_mode=json_mode)

    def _append_assistant(self, result: ChatResult) -> None:
        if result.assistant_message:
            self.messages.append(result.assistant_message)

    def _merge_last_assistant(self, cont: ChatResult) -> None:
        """把续写结果合并进最后一条 assistant 消息，保留签名/思考块。

        - Anthropic：content 为块数组，保留原始 thinking 块（含签名），仅追加续写的 text 块，
          保证 thinking 块始终位于 text 之前（否则下一轮回传会被 API 拒绝）。
        - OpenAI 兼容：content 为字符串，直接拼接正文。
        """
        last = self.messages[-1]
        content = last.get("content")
        if isinstance(content, list):
            extra = [
                b
                for b in (cont.assistant_message or {}).get("content", [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            last["content"] = [*content, *extra]
        else:
            last["content"] = (last.get("content") or "") + (cont.text or "")

    def history(self) -> list[dict[str, Any]]:
        """返回当前消息历史（不含 system），供前端/调试展示。"""
        return [m for m in self.messages if m.get("role") != "system"]


def new_conversation(
    provider_name: str | None = None,
    model: str | None = None,
    system: str | None = None,
) -> Conversation:
    """便捷工厂：加载配置并创建会话。"""
    return Conversation.create(provider_name, model=model, system=system)
