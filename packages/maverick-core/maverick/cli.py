"""Maverick CLI."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

from .budget import Budget
from .llm import LLM, DEFAULT_MODEL
from .orchestrator import run_goal_sync
from .sandbox import build_sandbox
from .skills import (
    SKILLS_DIR,
    install_skill,
    load_skills,
    remove_skill,
)
from .world_model import WorldModel, DEFAULT_DB


@click.group()
@click.option("--db", default=str(DEFAULT_DB), help="World model database path.")
@click.option("--model", default=DEFAULT_MODEL, help="LLM model id (per-role overrides apply).")
@click.pass_context
def main(ctx: click.Context, db: str, model: str) -> None:
    """Maverick: multi-agent swarm for long-horizon work."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = Path(db)
    ctx.obj["model"] = model


@main.command()
def init() -> None:
    """Run the interactive setup wizard."""
    try:
        from maverick_installer.wizard import run as run_wizard
    except ImportError:
        click.echo(
            "The installer wizard isn't installed.\n"
            "Install it with:  pipx install maverick-installer\n"
            "Or:               pip install maverick[installer]",
            err=True,
        )
        sys.exit(2)
    sys.exit(run_wizard())


@main.command()
@click.argument("title")
@click.option("--description", default="", help="Longer description of the goal.")
@click.option("--max-dollars", default=5.0, type=float)
@click.option("--max-wall-seconds", default=3600.0, type=float)
@click.option("--max-depth", default=3, type=int, help="Maximum swarm spawn depth.")
@click.option("--workdir", default=None, help="Sandbox working directory (defaults to config).")
@click.option("--sandbox", "sandbox_backend", default=None,
              type=click.Choice(["local", "docker"]),
              help="Sandbox backend override.")
@click.pass_context
def start(
    ctx,
    title: str,
    description: str,
    max_dollars: float,
    max_wall_seconds: float,
    max_depth: int,
    workdir,
    sandbox_backend,
) -> None:
    """Start a new goal and run the swarm."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("ERROR: ANTHROPIC_API_KEY not set.", err=True)
        sys.exit(2)

    world = WorldModel(ctx.obj["db"])
    goal_id = world.create_goal(title, description)
    click.echo(f"goal #{goal_id} created: {title}")

    llm = LLM(model=ctx.obj["model"])
    budget = Budget(max_dollars=max_dollars, max_wall_seconds=max_wall_seconds)
    sandbox = build_sandbox(workdir=workdir, backend=sandbox_backend)

    result = run_goal_sync(llm, world, budget, goal_id, sandbox=sandbox, max_depth=max_depth)
    click.echo("")
    click.echo(result)


@main.command()
@click.option("--max-depth", default=3, type=int, help="Maximum swarm spawn depth per request.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def serve(max_depth: int, verbose: bool) -> None:
    """Start the channel server (Telegram, Discord, Signal, etc.)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        from .server import build_from_config
    except ImportError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)

    try:
        server = build_from_config()
    except RuntimeError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)

    server.max_depth = max_depth
    click.echo("Maverick serve running. Ctrl-C to stop.")
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        click.echo("\nshutting down...")
        asyncio.run(server.stop())


@main.command()
@click.pass_context
def status(ctx) -> None:
    """Show recent goals and open questions."""
    world = WorldModel(ctx.obj["db"])
    goals = world.list_goals()
    if not goals:
        click.echo("no goals yet. start one with `maverick start \"...\"`")
        return
    for g in goals[-10:]:
        click.echo(f"  #{g.id} [{g.status}] {g.title}")
    qs = world.open_questions()
    if qs:
        click.echo("")
        click.echo("open questions:")
        for q in qs:
            click.echo(f"  #{q.id} (goal {q.goal_id}): {q.question}")


@main.command()
@click.argument("question_id", type=int)
@click.argument("answer", nargs=-1, required=True)
@click.pass_context
def answer(ctx, question_id: int, answer: tuple[str, ...]) -> None:
    """Answer a pending question."""
    world = WorldModel(ctx.obj["db"])
    world.answer(question_id, " ".join(answer))
    click.echo(f"answered #{question_id}")


@main.command()
@click.option("--goal-id", type=int, default=None)
@click.option("--max-depth", default=3, type=int)
@click.pass_context
def resume(ctx, goal_id, max_depth: int) -> None:
    """Resume a blocked goal."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("ERROR: ANTHROPIC_API_KEY not set.", err=True)
        sys.exit(2)

    world = WorldModel(ctx.obj["db"])
    if goal_id is None:
        g = world.active_goal()
        if not g:
            click.echo("no active or blocked goal to resume.")
            return
        goal_id = g.id

    open_qs = world.open_questions(goal_id)
    if open_qs:
        click.echo(f"cannot resume goal #{goal_id}: {len(open_qs)} open question(s).")
        for q in open_qs:
            click.echo(f"  #{q.id}: {q.question}")
        return

    llm = LLM(model=ctx.obj["model"])
    budget = Budget()
    result = run_goal_sync(llm, world, budget, goal_id, max_depth=max_depth)
    click.echo(result)


@main.command()
@click.argument("key")
@click.argument("value", nargs=-1, required=True)
@click.pass_context
def fact(ctx, key: str, value: tuple[str, ...]) -> None:
    """Set a fact in the world model."""
    world = WorldModel(ctx.obj["db"])
    world.upsert_fact(key, " ".join(value))
    click.echo(f"set {key}")


@main.command()
@click.pass_context
def facts(ctx) -> None:
    """List known facts."""
    world = WorldModel(ctx.obj["db"])
    for k, v in world.get_facts().items():
        click.echo(f"  {k}: {v}")


@main.command()
def skills() -> None:
    """List skills the swarm has distilled or installed."""
    items = load_skills()
    if not items:
        click.echo(f"no skills yet. they accrue in {SKILLS_DIR} after successful runs,")
        click.echo("or install one with:  maverick skill install <source>")
        return
    for s in items:
        click.echo(f"  {s.name}")
        for t in s.triggers[:3]:
            click.echo(f"    trigger: {t}")


@main.group()
def skill() -> None:
    """Manage skills (install, remove, info)."""


@skill.command("install")
@click.argument("source")
def skill_install(source: str) -> None:
    """Install a SKILL.md from a URL, gh:org/repo[:path], or local file.

    Examples:

      maverick skill install gh:texasreaper62/awesome-maverick-skills
      maverick skill install gh:texasreaper62/skills:research/web-search.md
      maverick skill install https://example.com/my-skill.md
      maverick skill install ./local-skill.md
    """
    try:
        s = install_skill(source)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"installed: {s.name} -> {s.path}")
    for t in s.triggers[:3]:
        click.echo(f"  trigger: {t}")


@skill.command("remove")
@click.argument("name")
def skill_remove(name: str) -> None:
    """Remove an installed skill by name."""
    if remove_skill(name):
        click.echo(f"removed: {name}")
    else:
        click.echo(f"no skill named {name!r}", err=True)
        sys.exit(2)


@skill.command("info")
@click.argument("name")
def skill_info(name: str) -> None:
    """Print a skill's body and triggers."""
    for s in load_skills():
        if s.name == name:
            click.echo(s.path)
            click.echo("")
            for t in s.triggers:
                click.echo(f"trigger: {t}")
            click.echo("")
            click.echo(s.body)
            return
    click.echo(f"no skill named {name!r}", err=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
