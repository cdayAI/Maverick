"""Quality-weighted skill ranking.

A skill's distilled_confidence provenance re-ranks retrieval so an
equally-relevant skill from a high-confidence run outranks one from a
barely-passing run — without fully suppressing the low-confidence one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick.skills import (
    Skill,
    _relevant_skills_lexical,
    quality_weight,
    relevant_skills,
)


def _skill(name: str, trigger: str, confidence: float, tmp_path: Path) -> Skill:
    p = tmp_path / f"{name}.md"
    p.write_text(
        f"---\nname: {name}\ndistilled_confidence: {confidence}\n"
        f"triggers:\n  - {trigger}\n---\n\n# Body\n\ndo {trigger}\n"
    )
    return Skill.parse(p.read_text(), p)


class TestQualityWeight:
    def test_high_confidence_near_one(self, tmp_path):
        s = _skill("a", "x", 1.0, tmp_path)
        assert quality_weight(s) == pytest.approx(1.0)

    def test_low_confidence_floored_at_half(self, tmp_path):
        s = _skill("a", "x", 0.0, tmp_path)
        assert quality_weight(s) == pytest.approx(0.5)

    def test_monotonic(self, tmp_path):
        lo = _skill("a", "x", 0.4, tmp_path)
        hi = _skill("b", "x", 0.9, tmp_path)
        assert quality_weight(hi) > quality_weight(lo)

    def test_disabled_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAVERICK_SKILL_QUALITY_WEIGHT", "0")
        s = _skill("a", "x", 0.0, tmp_path)
        assert quality_weight(s) == 1.0


class TestLexicalRanking:
    def test_high_confidence_outranks_equal_relevance(self, tmp_path):
        # Both match the goal identically; the high-confidence one wins.
        lo = _skill("lo", "deploy the app", 0.5, tmp_path)
        hi = _skill("hi", "deploy the app", 1.0, tmp_path)
        ranked = _relevant_skills_lexical("deploy the app", [lo, hi], max_n=2)
        assert [s.name for s in ranked] == ["hi", "lo"]

    def test_low_confidence_still_surfaces_when_alone(self, tmp_path):
        lo = _skill("lo", "deploy the app", 0.2, tmp_path)
        ranked = _relevant_skills_lexical("deploy the app", [lo], max_n=3)
        assert [s.name for s in ranked] == ["lo"]

    def test_strong_relevance_beats_quality(self, tmp_path):
        # A weak-confidence but exact-trigger match should still be able to
        # outrank a high-confidence partial match — quality only breaks
        # near-ties, it doesn't dominate relevance.
        exact = _skill("exact", "migrate the database schema", 0.5, tmp_path)
        partial = _skill("partial", "database", 1.0, tmp_path)
        ranked = _relevant_skills_lexical(
            "migrate the database schema", [partial, exact], max_n=2,
        )
        assert ranked[0].name == "exact"


class TestRelevantSkillsDispatch:
    def test_relevant_skills_uses_quality_when_no_embeddings(self, tmp_path, monkeypatch):
        # Force the lexical path (no fastembed in CI) and confirm the
        # public entry point applies quality weighting end to end.
        lo = _skill("lo", "summarize a report", 0.5, tmp_path)
        hi = _skill("hi", "summarize a report", 1.0, tmp_path)
        ranked = relevant_skills("summarize a report", [lo, hi], max_n=2)
        assert ranked[0].name == "hi"
