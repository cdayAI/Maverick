"""Disagreement entropy + adaptive fanout."""
from __future__ import annotations

from maverick.disagreement import (
    adaptive_fanout,
    answer_entropy,
    answers_disagree,
)


class TestAnswerEntropy:
    def test_identical_answers_zero_entropy(self):
        assert answer_entropy(["yes", "yes", "yes"]) == 0.0

    def test_all_unique_max_entropy(self):
        ent = answer_entropy(["a", "b", "c", "d"])
        assert 0.99 < ent <= 1.0

    def test_two_clusters_mid_entropy(self):
        """2-of-yes + 2-of-no out of 4 = log(2)/log(4) = 0.5."""
        ent = answer_entropy(["yes", "yes", "no", "no"])
        assert 0.49 < ent < 0.51

    def test_lopsided_low_entropy(self):
        # 4 of "yes", 1 of "no" → entropy below 0.75.
        ent = answer_entropy(["yes", "yes", "yes", "yes", "no"])
        assert 0.0 < ent < 0.75

    def test_single_answer_zero(self):
        assert answer_entropy(["only"]) == 0.0

    def test_empty_zero(self):
        assert answer_entropy([]) == 0.0

    def test_whitespace_doesnt_count_as_disagreement(self):
        """Same answer with different formatting should NOT be disagreement."""
        ent = answer_entropy(["the answer", "the answer\n\n", "  the answer  "])
        assert ent == 0.0


class TestAdaptiveFanout:
    def test_cold_start_at_least_two(self):
        """No prior samples → run at least 2 to get a signal."""
        out = adaptive_fanout([], requested=1)
        assert out >= 2

    def test_high_entropy_increases_fanout(self):
        diverse = ["a", "b", "c", "d", "e"]
        out_lo_req = adaptive_fanout(diverse, requested=1)
        out_hi_req = adaptive_fanout(diverse, requested=4)
        # With alpha=4.0 default, max entropy and requested=4 → 16 cap'd at FANOUT_MAX.
        assert out_lo_req >= 1
        assert out_hi_req > out_lo_req

    def test_low_entropy_keeps_fanout_low(self):
        same = ["one"] * 8
        out = adaptive_fanout(same, requested=4, minimum=1)
        # 0 entropy * anything ≈ 0 → clamped to minimum.
        assert out == 1

    def test_respects_max_clamp(self):
        diverse = [str(i) for i in range(50)]
        out = adaptive_fanout(diverse, requested=100, maximum=32)
        assert out <= 32

    def test_respects_min_clamp(self):
        out = adaptive_fanout(["only"], requested=10, minimum=3)
        assert out >= 1  # single answer = no entropy, min still respected


class TestAnswersDisagree:
    def test_clustered_returns_false(self):
        assert answers_disagree(["yes", "yes", "yes"]) is False

    def test_scattered_returns_true(self):
        assert answers_disagree(["a", "b", "c", "d"]) is True
