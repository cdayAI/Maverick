"""MCP server for Maverick.

Minimal JSON-RPC 2.0 over stdio implementation matching the
MCP 2024-11-05 spec. Exposes Maverick's CLI verbs as tools so any
MCP client (Claude Code, Claude Desktop, Cursor, ...) can drive the
swarm.

Methods implemented:
  - initialize
  - tools/list
  - tools/call
  - notifications/initialized (no-op)
  - ping

Transport: stdio line-delimited JSON. Clients spawn this process and
communicate via stdin/stdout.
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any, Optional

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] mcp: %(message)s",
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "maverick"
SERVER_VERSION = "0.1.0"


TOOLS: list[dict[str, Any]] = [
    {
        "name": "maverick_start",
        "description": (
            "Start a new goal in Maverick's recursive multi-agent swarm. "
            "Returns the final answer after the swarm completes. Long-running."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the goal."},
                "description": {"type": "string", "description": "Longer goal description."},
                "max_dollars": {"type": "number", "default": 5.0},
                "max_wall_seconds": {"type": "number", "default": 3600},
                "max_depth": {"type": "integer", "default": 3},
            },
            "required": ["title"],
        },
    },
    {
        "name": "maverick_status",
        "description": "List recent goals and any open questions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "maverick_resume",
        "description": "Resume a paused goal by id (or the most recent active/blocked goal).",
        "inputSchema": {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}},
        },
    },
    {
        "name": "maverick_answer",
        "description": "Answer a queued question (from `ask_user`) so a paused goal can resume.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question_id": {"type": "integer"},
                "answer": {"type": "string"},
            },
            "required": ["question_id", "answer"],
        },
    },
    {
        "name": "maverick_skill_install",
        "description": "Install a SKILL.md from a URL, gh:org/repo[:path], or local file.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": {"type": "string"}},
            "required": ["source"],
        },
    },
    {
        "name": "maverick_skills_list",
        "description": "List installed / distilled skills with their triggers.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "maverick_fact_set",
        "description": "Store a fact in the persistent world model (key/value).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "maverick_facts_get",
        "description": "Get all known facts from the world model.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class MCPServer:
    def __init__(self):
        self._initialized = False

    def handle_initialize(self, params: dict) -> dict:
        self._initialized = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def handle_tools_list(self, params: dict) -> dict:
        return {"tools": TOOLS}

    def handle_tools_call(self, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        try:
            result = self._dispatch_tool(name, arguments)
        except Exception as e:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
            }
        return {
            "isError": False,
            "content": [{"type": "text", "text": result}],
        }

    def _dispatch_tool(self, name: Optional[str], args: dict) -> str:
        if name == "maverick_start":
            return self._tool_start(args)
        if name == "maverick_status":
            return self._tool_status()
        if name == "maverick_resume":
            return self._tool_resume(args)
        if name == "maverick_answer":
            return self._tool_answer(args)
        if name == "maverick_skill_install":
            return self._tool_skill_install(args)
        if name == "maverick_skills_list":
            return self._tool_skills_list()
        if name == "maverick_fact_set":
            return self._tool_fact_set(args)
        if name == "maverick_facts_get":
            return self._tool_facts_get()
        raise ValueError(f"unknown tool {name!r}")

    def _tool_start(self, args: dict) -> str:
        from maverick.budget import Budget
        from maverick.llm import LLM
        from maverick.orchestrator import run_goal_sync
        from maverick.sandbox import build_sandbox
        from maverick.world_model import WorldModel

        title = args["title"]
        description = args.get("description", "")
        budget = Budget(
            max_dollars=float(args.get("max_dollars", 5.0)),
            max_wall_seconds=float(args.get("max_wall_seconds", 3600)),
        )
        world = WorldModel()
        goal_id = world.create_goal(title, description)
        llm = LLM()
        sandbox = build_sandbox()
        return run_goal_sync(
            llm, world, budget, goal_id, sandbox=sandbox,
            max_depth=int(args.get("max_depth", 3)),
        )

    def _tool_status(self) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        goals = w.list_goals()
        if not goals:
            return "no goals yet"
        lines = [f"#{g.id} [{g.status}] {g.title}" for g in goals[-10:]]
        for q in w.open_questions():
            lines.append(f"  open question #{q.id} (goal {q.goal_id}): {q.question}")
        return "\n".join(lines)

    def _tool_resume(self, args: dict) -> str:
        from maverick.budget import Budget
        from maverick.llm import LLM
        from maverick.orchestrator import run_goal_sync
        from maverick.world_model import WorldModel
        w = WorldModel()
        goal_id = args.get("goal_id")
        if goal_id is None:
            g = w.active_goal()
            if not g:
                return "no active or blocked goal to resume"
            goal_id = g.id
        return run_goal_sync(LLM(), w, Budget(), int(goal_id))

    def _tool_answer(self, args: dict) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        w.answer(int(args["question_id"]), str(args["answer"]))
        return f"answered #{args['question_id']}"

    def _tool_skill_install(self, args: dict) -> str:
        from maverick.skills import install_skill
        s = install_skill(args["source"])
        return f"installed: {s.name} -> {s.path}"

    def _tool_skills_list(self) -> str:
        from maverick.skills import load_skills
        items = load_skills()
        if not items:
            return "no skills installed"
        return "\n".join(
            f"{s.name}: {', '.join(s.triggers[:3])}" for s in items
        )

    def _tool_fact_set(self, args: dict) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        w.upsert_fact(args["key"], args["value"])
        return f"set {args['key']}"

    def _tool_facts_get(self) -> str:
        from maverick.world_model import WorldModel
        w = WorldModel()
        facts = w.get_facts()
        if not facts:
            return "no facts known"
        return "\n".join(f"{k}: {v}" for k, v in facts.items())

    def _send(self, message: dict) -> None:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    def _send_error(self, request_id: Any, code: int, message: str) -> None:
        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        })

    def _send_result(self, request_id: Any, result: dict) -> None:
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def run(self) -> None:
        log.info("Maverick MCP server starting (protocol %s)", PROTOCOL_VERSION)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("bad JSON: %s", e)
                continue

            method = msg.get("method")
            request_id = msg.get("id")
            params = msg.get("params", {}) or {}
            is_notification = request_id is None

            try:
                if method == "initialize":
                    self._send_result(request_id, self.handle_initialize(params))
                elif method == "tools/list":
                    self._send_result(request_id, self.handle_tools_list(params))
                elif method == "tools/call":
                    self._send_result(request_id, self.handle_tools_call(params))
                elif method == "notifications/initialized":
                    pass
                elif method == "ping":
                    self._send_result(request_id, {})
                else:
                    if not is_notification:
                        self._send_error(request_id, -32601, f"method not found: {method}")
            except Exception as e:
                log.exception("handler error")
                if not is_notification:
                    self._send_error(
                        request_id, -32603,
                        f"internal error: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                    )


def main() -> None:
    MCPServer().run()


if __name__ == "__main__":
    main()
