"""OpenAI provider client.

Implements the same complete()/complete_async() interface as
AnthropicClient, by translating Anthropic-format messages and tools
into OpenAI's chat format and converting the response back.

Used directly for OpenAI; subclassed by OpenRouter and Ollama, which
are OpenAI-compatible at different base_urls.

Format translation:
  - Anthropic system block      -> first OpenAI ``system`` message
  - Anthropic user text         -> OpenAI ``user`` message
  - Anthropic assistant content -> OpenAI ``assistant`` with text +
                                   ``tool_calls`` list
  - Anthropic tool_use block    -> OpenAI tool_calls function entry
  - Anthropic tool_result block -> OpenAI ``role: tool`` message
  - Thinking blocks are dropped (OpenAI has no equivalent for now;
    o1 thinking is internal to the model).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from ..budget import Budget
from ..llm import LLMResponse, ToolCall

log = logging.getLogger(__name__)


class OpenAIClient:
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        try:
            from openai import OpenAI, AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK not installed. Run: pip install 'maverick[openai]'"
            ) from e
        key = api_key or os.environ.get("OPENAI_API_KEY")
        self._sync = OpenAI(api_key=key, base_url=base_url)
        self._async = AsyncOpenAI(api_key=key, base_url=base_url)

    @staticmethod
    def _to_openai_messages(system: str, anthropic_messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for msg in anthropic_messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user":
                if isinstance(content, str):
                    out.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    text_parts: list[str] = []
                    for block in content:
                        if not isinstance(block, dict):
                            text_parts.append(str(block))
                            continue
                        bt = block.get("type")
                        if bt == "tool_result":
                            out.append({
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": str(block.get("content", "")),
                            })
                        elif bt == "text":
                            text_parts.append(block.get("text", ""))
                        else:
                            text_parts.append(str(block))
                    if text_parts:
                        out.append({"role": "user", "content": "\n".join(text_parts)})
            elif role == "assistant":
                if isinstance(content, str):
                    out.append({"role": "assistant", "content": content})
                elif isinstance(content, list):
                    text_parts: list[str] = []
                    tool_calls: list[dict] = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        bt = block.get("type")
                        if bt == "text":
                            text_parts.append(block.get("text", ""))
                        elif bt == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })
                        # ignore thinking blocks
                    msg_out: dict[str, Any] = {"role": "assistant"}
                    msg_out["content"] = "\n".join(text_parts) if text_parts else None
                    if tool_calls:
                        msg_out["tool_calls"] = tool_calls
                    out.append(msg_out)
        return out

    @staticmethod
    def _to_openai_tools(anthropic_tools: Optional[list[dict]]) -> Optional[list[dict]]:
        if not anthropic_tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object"}),
                },
            }
            for t in anthropic_tools
        ]

    @staticmethod
    def _from_response(resp: Any, budget: Optional[Budget]) -> LLMResponse:
        choice = resp.choices[0]
        text = choice.message.content or ""
        tool_calls: list[ToolCall] = []
        if getattr(choice.message, "tool_calls", None):
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id, name=tc.function.name, input=args,
                ))
        if budget is not None and getattr(resp, "usage", None):
            usage = resp.usage
            budget.record_tokens(
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
        return LLMResponse(
            text=text,
            thinking=None,
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason or "stop",
            raw=resp,
        )

    def _build_kwargs(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]],
        max_tokens: int,
        model: Optional[str],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model or self.DEFAULT_MODEL,
            "messages": self._to_openai_messages(system, messages),
            "max_tokens": max_tokens,
        }
        oai_tools = self._to_openai_tools(tools)
        if oai_tools:
            kwargs["tools"] = oai_tools
        return kwargs

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,  # noqa: ARG002 - unused, OpenAI has no eq
        model: Optional[str] = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(system, messages, tools, max_tokens, model)
        resp = self._sync.chat.completions.create(**kwargs)
        return self._from_response(resp, budget)

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[Budget] = None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,  # noqa: ARG002
        model: Optional[str] = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(system, messages, tools, max_tokens, model)
        resp = await self._async.chat.completions.create(**kwargs)
        return self._from_response(resp, budget)
