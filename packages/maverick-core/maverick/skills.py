"""Skill auto-generation, community install, and retrieval.

v0.1.5: ``relevant_skills`` now tries the embedding-based retriever in
``maverick.skill_embeddings`` first, falling back to the lexical scorer
when ``fastembed`` isn't installed. This keeps the closed-loop
learning effective on paraphrased goals (e.g. "compare these two
things" matches a skill triggered by "vs.") without forcing the heavy
ONNX runtime on users who don't want it.
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .blackboard import Blackboard
from .budget import Budget
from .llm import LLM, MODEL_SONNET

log = logging.getLogger(__name__)

SKILLS_DIR = Path.home() / ".maverick" / "skills"
INSTALL_TIMEOUT = 30.0


DISTILLER_SYSTEM = """You distill successful agent trajectories into reusable SKILL.md files.

Output format: a markdown file with YAML frontmatter, exactly:

---
name: <short-kebab-case-id>
triggers:
  - <natural language phrase that should activate this skill>
  - <another phrase>
tools_needed:
  - <tool name>
---

# What this skill does

<one paragraph describing the goal class>

# Steps

1. <step>
2. <step>
3. <step>

# Notes

<gotchas, anti-patterns, things that did NOT work>

Be specific. Cite exact tool calls, exact commands. Skills are only useful if a future agent can follow them mechanically."""


@dataclass
class Skill:
    name: str
    triggers: list[str]
    tools_needed: list[str]
    body: str
    path: Path

    @classmethod
    def parse(cls, text: str, path: Path) -> "Skill":
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
        if not m:
            raise ValueError("missing YAML frontmatter")
        front, body = m.group(1), m.group(2)
        meta: dict = {}
        current_key = None
        for line in front.splitlines():
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("  - ") and current_key:
                meta.setdefault(current_key, []).append(line[4:].strip())
            elif ":" in line:
                k, _, v = line.partition(":")
                k = k.strip()
                v = v.strip()
                current_key = k
                if v:
                    meta[k] = v
                else:
                    meta[k] = []
        return cls(
            name=meta.get("name", path.stem),
            triggers=meta.get("triggers", []) if isinstance(meta.get("triggers"), list) else [],
            tools_needed=meta.get("tools_needed", []) if isinstance(meta.get("tools_needed"), list) else [],
            body=body.strip(),
            path=path,
        )


def load_skills(skills_dir: Path = SKILLS_DIR) -> list[Skill]:
    if not skills_dir.exists():
        return []
    out = []
    for p in skills_dir.glob("*.md"):
        try:
            out.append(Skill.parse(p.read_text(), p))
        except Exception:
            continue
    return out


def _relevant_skills_lexical(goal: str, all_skills: list[Skill], max_n: int = 3) -> list[Skill]:
    """Original word-overlap + substring scorer. Always available, fast."""
    goal_lower = goal.lower()
    goal_words = set(re.findall(r"\w+", goal_lower))

    scored: list[tuple[int, Skill]] = []
    for s in all_skills:
        score = 0
        for trig in s.triggers:
            trig_words = set(re.findall(r"\w+", trig.lower()))
            score += len(trig_words & goal_words) * 2
            if trig.lower() in goal_lower:
                score += 5
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_n]]


def relevant_skills(goal: str, all_skills: list[Skill], max_n: int = 3) -> list[Skill]:
    """Pick the top-N skills for a goal.

    Tries embedding-based retrieval first (when ``fastembed`` is installed)
    and falls back to lexical scoring otherwise. The fallback is also used
    when embeddings fail for any reason (corrupt cache, OOM, etc.).
    """
    try:
        from .skill_embeddings import relevant_skills_embed
        result = relevant_skills_embed(goal, all_skills, max_n=max_n)
        if result is not None:
            return result
    except Exception as e:
        log.debug("embedding retrieval failed; falling back to lexical: %s", e)
    return _relevant_skills_lexical(goal, all_skills, max_n=max_n)


def render_for_prompt(skills: list[Skill]) -> str:
    if not skills:
        return ""
    parts = ["# Relevant skills from past runs", ""]
    for s in skills:
        parts.append(f"## {s.name}")
        parts.append(s.body)
        parts.append("")
    return "\n".join(parts)


def _safe_name(raw: str) -> str:
    name = re.sub(r"[^a-z0-9-]", "-", raw.lower()).strip("-")
    return name or "skill"


def install_skill(source: str, skills_dir: Path = SKILLS_DIR) -> Skill:
    skills_dir.mkdir(parents=True, exist_ok=True)

    if source.startswith("gh:"):
        rest = source[3:]
        if ":" in rest:
            repo, path = rest.split(":", 1)
        else:
            repo, path = rest, "SKILL.md"
        url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
        content = _fetch_url(url)
    elif source.startswith(("http://", "https://")):
        content = _fetch_url(source)
    else:
        p = Path(source).expanduser()
        if not p.exists():
            raise ValueError(f"local file {source!r} does not exist")
        content = p.read_text(encoding="utf-8")

    m = re.search(r"^name:\s*(\S+)", content, re.MULTILINE)
    name = _safe_name(m.group(1)) if m else "imported-skill"
    target = skills_dir / f"{name}.md"
    target.write_text(content, encoding="utf-8")
    return Skill.parse(content, target)


def _fetch_url(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=INSTALL_TIMEOUT) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status} from {url}")
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise ValueError(f"failed to fetch {url}: {e}") from e


def remove_skill(name: str, skills_dir: Path = SKILLS_DIR) -> bool:
    target = skills_dir / f"{_safe_name(name)}.md"
    if target.exists():
        target.unlink()
        return True
    return False


def distill(
    goal: str,
    summary: str,
    blackboard: Blackboard,
    llm: LLM,
    budget: Optional[Budget] = None,
    skills_dir: Path = SKILLS_DIR,
) -> Optional[Skill]:
    skills_dir.mkdir(parents=True, exist_ok=True)

    trajectory = blackboard.render(200)
    prompt = (
        f"Goal: {goal}\n\n"
        f"Outcome summary:\n{summary}\n\n"
        f"Trajectory (blackboard):\n{trajectory}\n\n"
        "Distill this into a SKILL.md file that would let a future agent "
        "solve a similar goal faster. Only output the markdown."
    )

    resp = llm.complete(
        system=DISTILLER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        budget=budget,
        max_tokens=2048,
        model=MODEL_SONNET,
    )
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("markdown"):
            text = text[len("markdown") :]
        text = text.strip()

    try:
        m = re.search(r"^name:\s*(\S+)", text, re.MULTILINE)
        name = _safe_name(m.group(1)) if m else "skill"
        path = skills_dir / f"{name}.md"
        path.write_text(text)
        return Skill.parse(text, path)
    except Exception:
        return None
