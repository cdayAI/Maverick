"""FastAPI dashboard for Maverick.

Local, read-only browser UI over the world model + skills directory.
Serves templates from ``maverick_dashboard/templates/`` using Jinja2.

Run directly::

    maverick-dashboard --host 127.0.0.1 --port 8765

Or via the core CLI once installed::

    maverick dashboard

Binds to localhost by default so nothing is exposed off-host. Pass
``--host 0.0.0.0`` only if you have a reverse proxy + auth in front.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="Maverick Dashboard", docs_url=None, redoc_url=None)


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
        {
            "counts": counts,
            "goals": list(reversed(goals[-20:])),
            "facts": facts,
            "skills": skills[:10],
        },
    )


@app.get("/goals", response_class=HTMLResponse)
async def goals_page(request: Request) -> HTMLResponse:
    w = _world()
    goals = list(reversed(w.list_goals()))
    return templates.TemplateResponse(request, "goals.html", {"goals": goals})


@app.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request) -> HTMLResponse:
    skills = _load_skills()
    return templates.TemplateResponse(request, "skills.html", {"skills": skills})


@app.get("/facts", response_class=HTMLResponse)
async def facts_page(request: Request) -> HTMLResponse:
    facts = _world().get_facts()
    return templates.TemplateResponse(request, "facts.html", {"facts": facts})


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
