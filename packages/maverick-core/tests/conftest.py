"""Shared test fixtures for maverick-core.

Provides:
  - ``fake_llm``: a scripted ``FakeLLM`` instance that replaces ``maverick.llm.LLM``
    in tests. Push ``LLMResponse`` objects to ``scripted`` and the agent loop
    pops them in order. Recorded calls available on ``.calls`` for assertions.
  - ``make_llm_response``: helper to build LLMResponse fixtures quickly.

Using this pattern is the only way to test the recursive agent loop and the
OpenAI translator without burning API credits in CI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from maverick.llm import LLMResponse, ToolCall  # noqa: F401 - re-exported for tests


@dataclass
class FakeLLM:
    """Drop-in replacement for ``maverick.llm.LLM`` driven by a script."""

    scripted: list[LLMResponse] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    model: str = "fake:test"

    def _record(self, **kwargs) -> None:
        self.calls.append(kwargs)

    def _next(self) -> LLMResponse:
        if not self.scripted:
            return LLMResponse(
                text="FINAL: (script exhausted)",
                thinking=None,
                tool_calls=[],
                stop_reason="end_turn",
            )
        return self.scripted.pop(0)

    async def complete_async(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget=None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        self._record(
            system=system, messages=messages, tools=tools,
            max_tokens=max_tokens, model=model,
        )
        return self._next()

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget=None,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        model: Optional[str] = None,
        on_delta=None,
    ) -> LLMResponse:
        self._record(
            system=system, messages=messages, tools=tools,
            max_tokens=max_tokens, model=model,
        )
        return self._next()


def make_response(
    text: str = "",
    tool_calls: Optional[list[ToolCall]] = None,
    thinking: Optional[str] = None,
    stop_reason: str = "end_turn",
) -> LLMResponse:
    return LLMResponse(
        text=text,
        thinking=thinking,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def make_llm_response():
    return make_response
