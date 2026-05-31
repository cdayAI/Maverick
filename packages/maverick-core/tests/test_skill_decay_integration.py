"""Skill decay folded into retrieval ranking + recorded by the orchestrator."""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick import skill_stats as ss
from maverick.budget import Budget
from maverick.orchestrator import run_goal
from maverick.sandbox import LocalBackend
from maverick.skills import Skill, _relevant_skills_lexical, quality_weight
from maverick.world_model import WorldModel


def _skill(name: str, trigger: str, tmp_path: Path) -> Skill:
    p = tmp_path / f"{name}.md"
    p.write_text(
        f"---\nname: {name}\ndistilled_confidence: 1.0\n"
        f"triggers:\n  - {trigger}\n---\n\n# Body\n\ndo {trigger}\n"
    )
    return Skill.parse(p.read_text(), p)


class TestDecayInRanking:
    def test_quality_weight_includes_decay(self, tmp_path, monkeypatch):
        stats = tmp_path / "stats.json"
        monkeypatch.setattr(ss, "DEFAULT_PATH", stats)
        # A skill with a losing track record.
        for _ in range(4):
            ss.record_use(["loser"], path=stats)
            ss.record_outcome(["loser"], success=False, path=stats)
        loser = _skill("loser", "x", tmp_path)
        winner = _skill("winner", "x", tmp_path)
        # Both have distilled_confidence 1.0; only the track record differs.
        assert quality_weight(loser) < quality_weight(winner)

    def test_losing_skill_ranks_below_equal_relevance(self, tmp_path, monkeypatch):
        stats = tmp_path / "stats.json"
        monkeypatch.setattr(ss, "DEFAULT_PATH", stats)
        for _ in range(4):
            ss.record_use(["loser"], path=stats)
            ss.record_outcome(["loser"], success=False, path=stats)
        loser = _skill("loser", "deploy the app", tmp_path)
        fresh = _skill("fresh", "deploy the app", tmp_path)
        ranked = _relevant_skills_lexical("deploy the app", [loser, fresh], max_n=2)
        assert ranked[0].name == "fresh"


class TestOrchestratorRecordsOutcome:
    @pytest.mark.asyncio
    async def test_success_records_win_for_used_skill(
        self, tmp_path, fake_llm, make_llm_response, monkeypatch,
    ):
        stats = tmp_path / "stats.json"
        monkeypatch.setattr(ss, "DEFAULT_PATH", stats)
        monkeypatch.setenv("MAVERICK_USE_SKILLS", "1")

        # load_skills() binds its skills_dir default at import time, so seed
        # the skill at the live skills.SKILLS_DIR location (the autouse
        # home-isolation fixture has already pointed it under tmp).
        import maverick.skills as sk
        skills_dir = sk.SKILLS_DIR
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "research.md").write_text(
            "---\nname: research\ntriggers:\n  - research the topic\n---\n"
            "\n# Body\n\nresearch it\n"
        )

        fake_llm.scripted = [
            make_llm_response(text="FINAL: done"),
            make_llm_response(
                text='{"confidence": 0.95, "accepts": true, "critique": "ok", "issues": []}',
            ),
            make_llm_response(text="FINAL: (no skill)"),
        ]
        world = WorldModel(path=tmp_path / "world.db")
        gid = world.create_goal("research the topic", "please research the topic")

        await run_goal(
            llm=fake_llm, world=world, budget=Budget(max_dollars=1.0),
            goal_id=gid, sandbox=LocalBackend(workdir=tmp_path), max_depth=1,
        )

        st = ss.get("research", path=stats)
        # The skill was recalled (use recorded) and the run succeeded (win).
        assert st is not None
        assert st.uses >= 1
        assert st.wins >= 1
