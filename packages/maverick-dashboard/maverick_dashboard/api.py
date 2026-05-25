"""REST API for Maverick.

Mounted at /api/v1 on the dashboard. Any HTTP client can:
  - create + run a goal
  - poll goal status
  - stream live events
  - read / write facts
  - list / install skills

Auth: bearer token via the dashboard middleware (set
``MAVERICK_DASHBOARD_TOKEN``); same auth applies to /api routes.

Auto-generated OpenAPI schema is at /docs and /openapi.json.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])


class GoalIn(BaseModel):
    title: str = Field(..., max_length=200, examples=["Plan a 2-week trip to Japan"])
    description: str = Field("", examples=["Solo, mid-budget, May 5–19, foodie-focused"])
    max_dollars: float = 5.0
    max_wall_seconds: float = 3600.0
    max_depth: int = 3
    template: Optional[str] = Field(None, examples=["trip-plan"])
    params: Optional[dict[str, str]] = None


class GoalOut(BaseModel):
    id: int
    status: str
    title: str
    description: Optional[str] = None
    result: Optional[str] = None


class GoalEventOut(BaseModel):
    id: int
    agent: str
    kind: str
    content: str
    ts: float


class GoalEventsResponse(BaseModel):
    status: str
    result: Optional[str]
    next_id: int
    events: list[GoalEventOut]


class FactIn(BaseModel):
    key: str
    value: str


class SkillInstallIn(BaseModel):
    source: str = Field(..., examples=[
        "gh:texasreaper62/awesome-maverick-skills:research/web-search.md",
        "https://example.com/my-skill.md",
    ])


class SkillOut(BaseModel):
    name: str
    triggers: list[str]
    tools_needed: list[str]


def _world():
    # See app.py:_world for why we resolve DEFAULT_DB at call time.
    from maverick.world_model import DEFAULT_DB, WorldModel
    return WorldModel(DEFAULT_DB)


def _run_goal_in_thread(goal_id: int) -> None:
    try:
        from maverick.budget import Budget
        from maverick.llm import LLM
        from maverick.orchestrator import run_goal_sync
        from maverick.sandbox import build_sandbox
        from maverick.world_model import DEFAULT_DB, WorldModel
        world = WorldModel(DEFAULT_DB)
        llm = LLM()
        sandbox = build_sandbox()
        run_goal_sync(llm, world, Budget(max_dollars=2.0), goal_id, sandbox=sandbox)
    except Exception:
        log.exception("REST API background goal run failed (goal_id=%s)", goal_id)


def _to_goal_out(g) -> GoalOut:
    return GoalOut(
        id=g.id, status=g.status, title=g.title,
        description=g.description, result=g.result,
    )


@router.post("/goals", response_model=GoalOut, status_code=201)
async def create_goal(payload: GoalIn, bg: BackgroundTasks) -> GoalOut:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY not set. Run `maverick init` first.",
        )

    title = payload.title
    description = payload.description

    if payload.template:
        from maverick.templates import load_template
        try:
            tpl = load_template(payload.template)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        try:
            title, description = tpl.render(**(payload.params or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    w = _world()
    goal_id = w.create_goal(title[:200], description)
    bg.add_task(_run_goal_in_thread, goal_id)
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=500, detail="goal vanished after create")
    return _to_goal_out(g)


@router.get("/goals", response_model=list[GoalOut])
async def list_goals(
    status: Optional[str] = None,
    limit: int = 50,
) -> list[GoalOut]:
    w = _world()
    goals = w.list_goals(status=status)
    return [_to_goal_out(g) for g in goals[-limit:]]


@router.get("/goals/{goal_id}", response_model=GoalOut)
async def get_goal(goal_id: int) -> GoalOut:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    return _to_goal_out(g)


@router.get("/goals/{goal_id}/events", response_model=GoalEventsResponse)
async def goal_events(
    goal_id: int, since: int = 0, limit: int = 200,
) -> GoalEventsResponse:
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    events = w.goal_events(goal_id, since_id=since, limit=limit)
    return GoalEventsResponse(
        status=g.status,
        result=g.result,
        next_id=events[-1].id if events else since,
        events=[
            GoalEventOut(id=e.id, agent=e.agent, kind=e.kind,
                         content=e.content, ts=e.ts)
            for e in events
        ],
    )


@router.post("/goals/{goal_id}/answer", status_code=204)
async def answer_question(
    goal_id: int,
    question_id: int,
    answer: str,
) -> None:
    w = _world()
    qs = w.open_questions(goal_id=goal_id)
    if not any(q.id == question_id for q in qs):
        raise HTTPException(status_code=404, detail="no such open question for this goal")
    w.answer(question_id, answer)


@router.get("/facts", response_model=dict[str, str])
async def list_facts() -> dict[str, str]:
    return _world().get_facts()


@router.post("/facts", status_code=204)
async def set_fact(payload: FactIn) -> None:
    _world().upsert_fact(payload.key, payload.value)


@router.get("/skills", response_model=list[SkillOut])
async def list_installed_skills() -> list[SkillOut]:
    from maverick.skills import load_skills
    return [
        SkillOut(name=s.name, triggers=s.triggers, tools_needed=s.tools_needed)
        for s in load_skills()
    ]


@router.post("/skills", response_model=SkillOut, status_code=201)
async def install_skill_endpoint(payload: SkillInstallIn) -> SkillOut:
    from maverick.skills import install_skill
    try:
        s = install_skill(payload.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SkillOut(name=s.name, triggers=s.triggers, tools_needed=s.tools_needed)


@router.delete("/skills/{name}", status_code=204)
async def remove_skill_endpoint(name: str) -> None:
    from maverick.skills import remove_skill
    if not remove_skill(name):
        raise HTTPException(status_code=404, detail="no such skill")


@router.get("/spend")
async def get_spend() -> dict:
    w = _world()
    total = w.total_spend()
    episodes = w.list_episodes(limit=30)
    return {
        "total": total,
        "episodes": [
            {
                "id": e.id, "goal_id": e.goal_id, "started_at": e.started_at,
                "ended_at": e.ended_at, "outcome": e.outcome,
                "cost_dollars": e.cost_dollars,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "tool_calls": e.tool_calls,
            }
            for e in episodes
        ],
    }
