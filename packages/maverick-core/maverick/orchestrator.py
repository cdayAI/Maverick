"""Run a top-level goal through the swarm.

v0.1.2: episodes now record cost/tokens/tool_calls at end so the
dashboard can render spend history.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .agent import Agent
from .blackboard import Blackboard
from .budget import Budget, BudgetExceeded
from .llm import LLM
from .sandbox import LocalBackend
from .skills import distill
from .swarm import SwarmContext
from .world_model import WorldModel

log = logging.getLogger(__name__)


def _build_shield() -> Optional[Any]:
    try:
        from maverick_shield import Shield
        return Shield.from_config()
    except ImportError:
        log.warning("maverick-shield not installed; tool-call scans disabled")
        return None
    except Exception as e:  # pragma: no cover
        log.error("Shield construction failed (fail-open): %s", e)
        return None


def _end_episode_with_spend(
    world: WorldModel,
    episode_id: int,
    summary: str,
    outcome: str,
    budget: Budget,
) -> None:
    """Helper to record final spend numbers in the episode row."""
    try:
        world.end_episode(
            episode_id, summary, outcome,
            cost_dollars=budget.dollars,
            input_tokens=budget.input_tokens,
            output_tokens=budget.output_tokens,
            tool_calls=budget.tool_calls,
        )
    except TypeError:
        # Older WorldModel without the spend kwargs -- fall back.
        world.end_episode(episode_id, summary, outcome)


async def run_goal(
    llm: LLM,
    world: WorldModel,
    budget: Budget,
    goal_id: int,
    sandbox: Optional[Any] = None,
    max_depth: int = 3,
) -> str:
    goal = world.get_goal(goal_id)
    if not goal:
        return f"no such goal: {goal_id}"

    world.set_goal_status(goal_id, "active")
    episode_id = world.start_episode(goal_id)
    blackboard = Blackboard()
    sandbox = sandbox or LocalBackend()
    shield = _build_shield()

    ctx = SwarmContext(
        llm=llm, world=world, budget=budget, blackboard=blackboard,
        sandbox=sandbox, goal_id=goal_id, max_depth=max_depth, shield=shield,
    )

    facts = world.get_facts()
    facts_block = "\n".join(f"  {k}: {v}" for k, v in facts.items()) or "  (none)"
    brief = (
        f"Top-level goal: {goal.title}\n"
        f"Description: {goal.description or '(none)'}\n\n"
        f"Known facts about the user:\n{facts_block}\n\n"
        "Decompose into sub-tasks, spawn workers (parallel where possible), "
        "synthesize their findings, verify, and respond with FINAL:."
    )

    root = Agent(ctx=ctx, role="orchestrator", brief=brief, depth=0)

    try:
        result = await root.run()
    except BudgetExceeded as e:
        _end_episode_with_spend(world, episode_id, f"budget: {e}", "failure", budget)
        world.set_goal_status(goal_id, "blocked", result=f"budget exceeded: {e}")
        return f"BUDGET EXCEEDED: {budget.summary()}"

    if result.blocked_on_user:
        _end_episode_with_spend(
            world, episode_id, "blocked awaiting user", "interrupted", budget,
        )
        world.set_goal_status(goal_id, "blocked")
        qs = world.open_questions(goal_id)
        return (
            f"PAUSED: waiting on user. {len(qs)} open question(s).\n"
            + "\n".join(f"  #{q.id}: {q.question}" for q in qs)
        )

    if result.error:
        _end_episode_with_spend(world, episode_id, result.error, "failure", budget)
        world.set_goal_status(goal_id, "blocked", result=result.error)
        return f"FAILED: {result.error}\n[{budget.summary()}]"

    summary = result.final or "(no answer)"
    _end_episode_with_spend(world, episode_id, summary, "success", budget)
    world.set_goal_status(goal_id, "done", result=summary)

    try:
        skill = distill(goal.title, summary, blackboard, llm, budget=budget)
        skill_note = f"\n\n[distilled skill: {skill.name}]" if skill else ""
    except BudgetExceeded:
        skill_note = "\n\n[skill distill skipped: budget]"
    except Exception as e:
        skill_note = f"\n\n[skill distill error: {e}]"

    return f"DONE.\n\n{summary}{skill_note}\n\n[{budget.summary()}]"


def run_goal_sync(*args, **kwargs) -> str:
    return asyncio.run(run_goal(*args, **kwargs))
