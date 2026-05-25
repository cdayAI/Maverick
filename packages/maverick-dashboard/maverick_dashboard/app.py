"""FastAPI dashboard for Maverick.

v0.1.3 additions:
  - /chat with background-task goal runs + live event polling
  - /api/goal/{id}/events streams blackboard entries via long-poll
  - Optional bearer-token auth for VPS deployments via
    MAVERICK_DASHBOARD_TOKEN env var
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="Maverick Dashboard", docs_url=None, redoc_url=None)


@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    """Optional bearer-token gate for VPS / non-localhost deployments.

    If ``MAVERICK_DASHBOARD_TOKEN`` is set, every request must carry
    ``Authorization: Bearer <token>`` OR ``?token=<token>`` query
    parameter (so phone browsers can be bookmarked once with the
    token in the URL).

    /healthz is always reachable so reverse proxies can probe it.
    """
    expected = os.environ.get("MAVERICK_DASHBOARD_TOKEN")
    if not expected or request.url.path == "/healthz":
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    token_qs = request.query_params.get("token", "")
    if auth == f"Bearer {expected}" or token_qs == expected:
        return await call_next(request)
    return JSONResponse({"detail": "unauthorized"}, status_code=401)


def _world():
    from maverick.world_model import WorldModel
    return WorldModel()


def _load_skills():
    from maverick.skills import load_skills
    return load_skills()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    w = _world()
    goals = w.list_goals()
    facts = w.get_facts()
    skills = _load_skills()
    counts = {
        "total":  len(goals),
        "active": sum(1 for g in goals if g.status == "active"),
        "done":   sum(1 for g in goals if g.status == "done"),
        "blocked": sum(1 for g in goals if g.status == "blocked"),
    }
    return templates.TemplateResponse(
        request, "index.html",
        {"counts": counts, "goals": list(reversed(goals[-20:])),
         "facts": facts, "skills": skills[:10]},
    )


@app.get("/goals", response_class=HTMLResponse)
async def goals_page(request: Request) -> HTMLResponse:
    goals = list(reversed(_world().list_goals()))
    return templates.TemplateResponse(request, "goals.html", {"goals": goals})


@app.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "skills.html", {"skills": _load_skills()})


@app.get("/facts", response_class=HTMLResponse)
async def facts_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "facts.html", {"facts": _world().get_facts()})


@app.get("/spend", response_class=HTMLResponse)
async def spend_page(request: Request) -> HTMLResponse:
    w = _world()
    return templates.TemplateResponse(
        request, "spend.html",
        {"episodes": w.list_episodes(limit=50), "total": w.total_spend()},
    )


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    recent = list(reversed(_world().list_goals()[-10:]))
    return templates.TemplateResponse(request, "chat.html", {"recent": recent})


def _run_goal_in_thread(goal_id: int) -> None:
    try:
        from maverick.budget import Budget
        from maverick.llm import LLM
        from maverick.orchestrator import run_goal_sync
        from maverick.sandbox import build_sandbox
        from maverick.world_model import WorldModel
        world = WorldModel()
        llm = LLM()
        sandbox = build_sandbox()
        run_goal_sync(llm, world, Budget(max_dollars=2.0), goal_id, sandbox=sandbox)
    except Exception:
        log.exception("dashboard background goal run failed (goal_id=%s)", goal_id)


@app.post("/chat/send")
async def chat_send(
    request: Request,
    bg: BackgroundTasks,
    title: str = Form(...),
) -> RedirectResponse:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY not set. Run `maverick init` first.",
        )
    w = _world()
    goal_id = w.create_goal(title.strip()[:200], title.strip())
    bg.add_task(_run_goal_in_thread, goal_id)
    return RedirectResponse(f"/chat/goal/{goal_id}", status_code=303)


@app.get("/chat/goal/{goal_id}", response_class=HTMLResponse)
async def chat_goal(request: Request, goal_id: int) -> HTMLResponse:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    return templates.TemplateResponse(request, "chat_goal.html", {"goal": g})


@app.get("/api/goal/{goal_id}")
async def api_goal(goal_id: int) -> dict:
    g = _world().get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    return {"id": g.id, "status": g.status, "title": g.title, "result": g.result or ""}


@app.get("/api/goal/{goal_id}/events")
async def api_goal_events(goal_id: int, since: int = 0, limit: int = 200) -> dict:
    """Live stream of blackboard entries for a goal.

    Long-poll style: pass `since=<last_id>` to get only new entries.
    Returned ``next_id`` is the highest id seen; pass it back as
    `since` on the next request.
    """
    w = _world()
    g = w.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail="no such goal")
    events = w.goal_events(goal_id, since_id=since, limit=limit)
    return {
        "status": g.status,
        "result": g.result or "",
        "next_id": events[-1].id if events else since,
        "events": [
            {"id": e.id, "agent": e.agent, "kind": e.kind,
             "content": e.content, "ts": e.ts}
            for e in events
        ],
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Maverick dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
