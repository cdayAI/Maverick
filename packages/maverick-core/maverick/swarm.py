"""Swarm context: shared state for all agents in a single run.

Every agent in a swarm shares:
  - one LLM client (with its own connection pool)
  - one WorldModel (persistent state)
  - one Budget (global cost/time/token cap)
  - one Blackboard (shared workspace for the run)
  - one Sandbox (execution backend)
  - one Shield (input/tool-call/output scans; may be None if disabled)

Children inherit the parent's context but get their own brief, role, and depth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .blackboard import Blackboard
from .budget import Budget
from .llm import LLM
from .world_model import WorldModel


@dataclass
class SwarmContext:
    llm: LLM
    world: WorldModel
    budget: Budget
    blackboard: Blackboard
    sandbox: Any  # LocalBackend | DockerBackend; duck-typed via .exec(cmd) -> ExecResult
    goal_id: int
    max_depth: int = 3
    # Whether to attempt to load relevant skills into each agent's brief.
    use_skills: bool = True
    # Optional Shield instance from maverick_shield. None = scans disabled.
    # Typed as Any to keep maverick-core importable without maverick-shield.
    shield: Optional[Any] = None
