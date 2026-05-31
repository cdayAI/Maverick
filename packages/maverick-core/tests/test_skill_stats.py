"""Skill usage tracking + decay.

Records skill recalls (record_use) and run outcomes (record_outcome), then
derives a track-record multiplier (decay_weight) and eviction candidates
(evictable). Stats are fail-safe and never block a run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from maverick import skill_stats as ss


@pytest.fixture
def path(tmp_path) -> Path:
    return tmp_path / "skill_stats.json"


class TestRecording:
    def test_record_use_increments(self, path):
        ss.record_use(["a", "b"], path=path)
        ss.record_use(["a"], path=path)
        assert ss.get("a", path=path).uses == 2
        assert ss.get("b", path=path).uses == 1

    def test_record_outcome_splits_win_loss(self, path):
        ss.record_outcome(["a"], success=True, path=path)
        ss.record_outcome(["a"], success=False, path=path)
        ss.record_outcome(["a"], success=True, path=path)
        st = ss.get("a", path=path)
        assert st.wins == 2 and st.losses == 1

    def test_empty_names_noop(self, path):
        ss.record_use([], path=path)
        ss.record_outcome([], success=True, path=path)
        assert not path.exists()

    def test_disabled_via_env(self, path, monkeypatch):
        monkeypatch.setenv("MAVERICK_SKILL_DECAY", "0")
        ss.record_use(["a"], path=path)
        assert not path.exists()


class TestDecayWeight:
    def test_neutral_before_min_uses(self, path):
        ss.record_use(["a"], path=path)
        ss.record_outcome(["a"], success=False, path=path)
        # Only 1 use < min_uses=3 -> no penalty yet.
        assert ss.decay_weight("a", path=path) == 1.0

    def test_all_wins_stays_high(self, path):
        for _ in range(4):
            ss.record_use(["a"], path=path)
            ss.record_outcome(["a"], success=True, path=path)
        assert ss.decay_weight("a", path=path) == pytest.approx(1.0)

    def test_all_losses_decays_to_floor(self, path):
        for _ in range(4):
            ss.record_use(["a"], path=path)
            ss.record_outcome(["a"], success=False, path=path)
        assert ss.decay_weight("a", path=path, floor=0.5) == pytest.approx(0.5)

    def test_mixed_is_between(self, path):
        for _ in range(4):
            ss.record_use(["a"], path=path)
        ss.record_outcome(["a"], success=True, path=path)
        ss.record_outcome(["a"], success=True, path=path)
        ss.record_outcome(["a"], success=False, path=path)
        ss.record_outcome(["a"], success=False, path=path)
        # win_rate 0.5 -> 0.5 + 0.5*0.5 = 0.75
        assert ss.decay_weight("a", path=path) == pytest.approx(0.75)

    def test_unknown_skill_is_neutral(self, path):
        assert ss.decay_weight("never-seen", path=path) == 1.0

    def test_disabled_returns_one(self, path, monkeypatch):
        for _ in range(4):
            ss.record_use(["a"], path=path)
            ss.record_outcome(["a"], success=False, path=path)
        monkeypatch.setenv("MAVERICK_SKILL_DECAY", "0")
        assert ss.decay_weight("a", path=path) == 1.0


class TestEvictable:
    def test_identifies_chronic_loser(self, path):
        for _ in range(6):
            ss.record_use(["loser"], path=path)
            ss.record_outcome(["loser"], success=False, path=path)
        for _ in range(6):
            ss.record_use(["winner"], path=path)
            ss.record_outcome(["winner"], success=True, path=path)
        ev = ss.evictable(path=path)
        assert "loser" in ev
        assert "winner" not in ev

    def test_spares_untried_skills(self, path):
        ss.record_use(["new"], path=path)
        ss.record_outcome(["new"], success=False, path=path)
        # Only 1 use < min_uses=5 -> not evictable yet.
        assert ss.evictable(path=path) == []


class TestFailSafe:
    def test_corrupt_file_degrades_to_neutral(self, path):
        path.write_text("{ not json", encoding="utf-8")
        assert ss.decay_weight("a", path=path) == 1.0
        assert ss.get("a", path=path) is None
        assert ss.evictable(path=path) == []
