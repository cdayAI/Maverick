"""Maverick CLI."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

from .budget import Budget
from .llm import DEFAULT_MODEL, LLM
from .orchestrator import run_goal_sync
from .sandbox import build_sandbox
from .skills import (
    SKILLS_DIR,
    install_skill,
    load_skills,
    remove_skill,
)
from .world_model import DEFAULT_DB, WorldModel


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
            "Install it with:  pipx install maverick-installer",
            err=True,
        )
        sys.exit(2)
    sys.exit(run_wizard())


@main.command()
def doctor() -> None:
    """Diagnose your Maverick installation."""
    from .health import diagnose
    diagnose()


@main.command()
@click.argument("action", type=click.Choice(["show", "path", "edit"]), default="show")
def config(action: str) -> None:
    """Show, locate, or edit ~/.maverick/config.toml."""
    from .config import config_path
    p = config_path()
    if action == "path":
        click.echo(str(p))
        return
    if action == "edit":
        editor = os.environ.get("EDITOR", "nano")
        os.execvp(editor, [editor, str(p)])
        return
    if not p.exists():
        click.echo(f"No config at {p}. Run:  maverick init", err=True)
        sys.exit(1)
    click.echo(p.read_text())


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
def dashboard(host: str, port: int) -> None:
    """Start the local web dashboard (read-only goals/skills/facts viewer)."""
    try:
        from maverick_dashboard.app import app as fastapi_app
    except ImportError:
        click.echo("Install: pip install maverick-dashboard", err=True)
        sys.exit(2)
    import uvicorn
    click.echo(f"Maverick dashboard: http://{host}:{port}")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@main.command()
def mcp() -> None:
    """Start the MCP server on stdio (for Claude Code / Cursor / etc.)."""
    try:
        from maverick_mcp.server import main as mcp_main
    except ImportError:
        click.echo("Install: pip install maverick-mcp", err=True)
        sys.exit(2)
    mcp_main()


@main.command()
@click.argument("title", required=False)
@click.option("--description", default="", help="Longer description.")
@click.option("--template", "template_name", default=None,
              help="Goal template name (see benchmarks/example-templates/).")
@click.option("--param", "-p", "params", multiple=True,
              help="key=value param for the template. Repeatable.")
@click.option("--max-dollars", default=None, type=float)
@click.option("--max-wall-seconds", default=None, type=float)
@click.option("--max-depth", default=3, type=int)
@click.option("--workdir", default=None)
@click.option("--sandbox", "sandbox_backend", default=None,
              type=click.Choice(["local", "docker", "ssh"]))
@click.pass_context
def start(
    ctx, title, description, template_name, params,
    max_dollars, max_wall_seconds, max_depth, workdir, sandbox_backend,
) -> None:
    """Start a new goal and run the swarm.

    Pass either TITLE directly, or --template <name> with --param key=value pairs.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("ERROR: ANTHROPIC_API_KEY not set. Run: maverick doctor", err=True)
        sys.exit(2)

    if template_name:
        from .templates import load_template
        try:
            tpl = load_template(template_name)
        except FileNotFoundError as e:
            click.echo(f"ERROR: {e}", err=True)
            sys.exit(2)
        # Parse key=value param pairs.
        param_dict = {}
        for raw in params:
            if "=" not in raw:
                click.echo(f"ERROR: --param must be key=value, got {raw!r}", err=True)
                sys.exit(2)
            k, v = raw.split("=", 1)
            param_dict[k.strip()] = v.strip()
        try:
            title, description = tpl.render(**param_dict)
        except ValueError as e:
            click.echo(f"ERROR: {e}", err=True)
            sys.exit(2)
        max_dollars = max_dollars or tpl.budget_dollars
        max_wall_seconds = max_wall_seconds or tpl.budget_wall_seconds
        click.echo(f"[template {tpl.name}] {title}")
    elif not title:
        click.echo("ERROR: pass TITLE or --template <name>", err=True)
        sys.exit(2)

    world = WorldModel(ctx.obj["db"])
    goal_id = world.create_goal(title, description)
    click.echo(f"goal #{goal_id} created: {title}")

    llm = LLM(model=ctx.obj["model"])
    budget = Budget(
        max_dollars=max_dollars or 5.0,
        max_wall_seconds=max_wall_seconds or 3600.0,
    )
    sandbox = build_sandbox(workdir=workdir, backend=sandbox_backend)
    result = run_goal_sync(llm, world, budget, goal_id, sandbox=sandbox, max_depth=max_depth)
    click.echo("")
    click.echo(result)


@main.command()
@click.option("--max-depth", default=3, type=int)
@click.option("--max-dollars", default=2.0, type=float,
              help="Cap per message (chat is per-turn).")
@click.option("--workdir", default=None)
@click.pass_context
def chat(ctx, max_depth: int, max_dollars: float, workdir) -> None:
    """Start an interactive chat REPL.

    Each line you type becomes a goal. Maverick replies with the swarm's
    final answer. Type 'exit' / 'quit' or Ctrl-D to leave.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("ERROR: ANTHROPIC_API_KEY not set. Run: maverick doctor", err=True)
        sys.exit(2)

    world = WorldModel(ctx.obj["db"])
    llm = LLM(model=ctx.obj["model"])
    sandbox = build_sandbox(workdir=workdir)

    click.echo(click.style("Maverick chat. Type 'exit' to leave.", fg="cyan"))
    while True:
        try:
            line = click.prompt("", prompt_suffix="> ", default="", show_default=False)
        except (EOFError, click.exceptions.Abort):
            click.echo("")
            return
        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit", "/exit", "/quit"):
            return
        title = line[:80]
        goal_id = world.create_goal(title, line)
        click.echo(click.style(f"  ... goal #{goal_id}", fg="bright_black"))
        budget = Budget(max_dollars=max_dollars)
        try:
            result = run_goal_sync(llm, world, budget, goal_id,
                                   sandbox=sandbox, max_depth=max_depth)
        except Exception as e:
            click.echo(click.style(f"  ✗ {e}", fg="red"))
            continue
        click.echo(result)
        click.echo("")


@main.group()
def template() -> None:
    """Manage goal templates."""


@template.command("list")
def template_list() -> None:
    """List bundled + user-installed templates."""
    from .templates import list_templates
    names = list_templates()
    if not names:
        click.echo("no templates found.")
        return
    for n in names:
        click.echo(f"  {n}")


@template.command("show")
@click.argument("name")
def template_show(name: str) -> None:
    """Print a template's title, body, and params."""
    from .templates import load_template
    try:
        t = load_template(name)
    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"template: {t.name}")
    click.echo(f"path: {t.path}")
    click.echo(f"title: {t.title}")
    click.echo(f"budget: ${t.budget_dollars} / {t.budget_wall_seconds}s")
    click.echo(f"params: {', '.join(t.params) or '(none)'}")
    click.echo("")
    click.echo(t.body)


@main.command()
@click.option("--max-depth", default=3, type=int)
@click.option("--verbose", "-v", is_flag=True)
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
@click.option("--limit", default=20, type=int)
@click.pass_context
def logs(ctx, limit: int) -> None:
    """Show recent goal + episode history from the world model."""
    world = WorldModel(ctx.obj["db"])
    goals = world.list_goals()
    if not goals:
        click.echo("no goals yet.")
        return
    for g in goals[-limit:]:
        click.echo(f"#{g.id} [{g.status}] {g.title}")
        if g.result:
            preview = (g.result or "")[:200].replace("\n", " ")
            click.echo(f"  -> {preview}{'...' if len(g.result) > 200 else ''}")


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
        click.echo(f"no skills yet. they accrue in {SKILLS_DIR} after successful runs.")
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
    """Install a SKILL.md from a URL, gh:org/repo[:path], or local file."""
    try:
        s = install_skill(source)
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    click.echo(f"installed: {s.name} -> {s.path}")


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
