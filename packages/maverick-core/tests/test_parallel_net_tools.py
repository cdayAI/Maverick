"""Thread-offloaded concurrency for sync parallel-safe tools.

The agent loop gathers a turn's parallel_safe tool calls concurrently, but
sync tool functions (network/file reads) would run back-to-back on the
event loop unless offloaded to a thread. ToolRegistry.run offloads sync
fns via asyncio.to_thread so they truly overlap. Network read tools
(http_fetch/arxiv/wikipedia/semantic_scholar/hackernews) are marked
parallel_safe so they join that path.
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from maverick.agent import Agent
from maverick.blackboard import Blackboard
from maverick.budget import Budget
from maverick.llm import LLMResponse, ToolCall
from maverick.sandbox import LocalBackend
from maverick.swarm import SwarmContext
from maverick.tools import Tool, base_registry
from maverick.world_model import WorldModel


@pytest.fixture
def ctx(tmp_path: Path, fake_llm):
    world = WorldModel(tmp_path / "world.db")
    goal_id = world.create_goal("test goal", "")
    return SwarmContext(
        llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
        blackboard=Blackboard(), sandbox=LocalBackend(workdir=tmp_path),
        goal_id=goal_id, max_depth=1, use_skills=False,
    )


def test_network_read_tools_are_parallel_safe(ctx):
    reg = base_registry(ctx.world, ctx.sandbox)
    for name in ("http_fetch", "arxiv", "wikipedia",
                 "semantic_scholar", "hackernews"):
        assert reg.get(name).parallel_safe is True, name


class _BlockingSyncTracker:
    """Hands out SYNC tools that block (time.sleep) and record the peak
    number of distinct threads running concurrently."""

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.threads: set[int] = set()
        self._lock = threading.Lock()

    def tool(self, name: str) -> Tool:
        def fn(args: dict) -> str:
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.threads.add(threading.get_ident())
            time.sleep(0.1)
            with self._lock:
                self.active -= 1
            return f"ok:{name}"

        return Tool(name=name, description="x",
                    input_schema={"type": "object", "properties": {}},
                    fn=fn, parallel_safe=True)


@pytest.mark.asyncio
async def test_sync_parallel_safe_tools_overlap_via_threads(ctx, fake_llm):
    tracker = _BlockingSyncTracker()
    fake_llm.scripted = [
        LLMResponse(
            text="reading", thinking=None, stop_reason="tool_use",
            tool_calls=[ToolCall(id="a", name="r1", input={}),
                        ToolCall(id="b", name="r2", input={})],
        ),
        LLMResponse(text="FINAL: done", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
    ]
    agent = Agent(ctx=ctx, role="researcher", brief="read two urls")
    agent.tools.register(tracker.tool("r1"))
    agent.tools.register(tracker.tool("r2"))
    result = await agent.run()
    assert result.final == "done"
    # Both blocking sync tools ran at the same time, on two threads.
    assert tracker.max_active == 2
    assert len(tracker.threads) == 2


@pytest.mark.asyncio
async def test_offload_can_be_disabled(ctx, fake_llm, monkeypatch):
    monkeypatch.setenv("MAVERICK_TOOL_THREAD_OFFLOAD", "0")
    tracker = _BlockingSyncTracker()
    fake_llm.scripted = [
        LLMResponse(
            text="reading", thinking=None, stop_reason="tool_use",
            tool_calls=[ToolCall(id="a", name="r1", input={}),
                        ToolCall(id="b", name="r2", input={})],
        ),
        LLMResponse(text="FINAL: done", thinking=None,
                    stop_reason="end_turn", tool_calls=[]),
    ]
    agent = Agent(ctx=ctx, role="researcher", brief="read two urls")
    agent.tools.register(tracker.tool("r1"))
    agent.tools.register(tracker.tool("r2"))
    await agent.run()
    # No offload -> sync fns run inline on the loop -> no overlap.
    assert tracker.max_active == 1


@pytest.mark.asyncio
async def test_async_tools_still_work(ctx):
    """Coroutine-function tools are awaited on the loop, not offloaded."""
    reg = base_registry(ctx.world, ctx.sandbox)
    calls = {"n": 0}

    async def afn(args):
        calls["n"] += 1
        await asyncio.sleep(0)
        return "async-ok"

    reg.register(Tool(name="atool", description="x",
                      input_schema={"type": "object", "properties": {}},
                      fn=afn, parallel_safe=True))
    out = await reg.run("atool", {})
    assert out == "async-ok"
    assert calls["n"] == 1
