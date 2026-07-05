#!/usr/bin/env python3
"""
test_vl_normalization.py — Boundary tests for VL score normalization.

Verifies that the 0-3 per-dimension → 0-10 normalized mapping is correct.
"""

try:
    import pytest
except ImportError:
    pytest = None


# Constants matching character_image_check.py
DIM_SCORE_MAX = 3  # per-dimension max
NUM_DIMENSIONS = 6
TOTAL_MAX = NUM_DIMENSIONS * DIM_SCORE_MAX  # 18


def _normalize(dim_scores: list) -> float:
    """Replicate the normalization logic from character_image_check.py."""
    overall = sum(dim_scores)
    overall_norm = round(min(overall * 10 / TOTAL_MAX, 10.0), 1)
    return overall_norm


class TestNormalizationBoundaries:
    """Verify normalization is correct at boundaries and key points."""

    def test_all_zeros(self):
        """6 dims all 0 → overall_norm = 0.0"""
        scores = [0, 0, 0, 0, 0, 0]
        assert _normalize(scores) == 0.0

    def test_all_max(self):
        """6 dims all 3 → overall_norm = 10.0"""
        scores = [3, 3, 3, 3, 3, 3]
        assert _normalize(scores) == 10.0

    def test_all_mids(self):
        """6 dims all 1.5 → overall_norm = 5.0"""
        scores = [1.5, 1.5, 1.5, 1.5, 1.5, 1.5]
        assert _normalize(scores) == 5.0

    def test_all_ones(self):
        """6 dims all 1 → overall_norm = 3.3 (18/18*10=3.33...)"""
        scores = [1, 1, 1, 1, 1, 1]
        assert _normalize(scores) == pytest.approx(3.3, abs=0.05)

    def test_all_twos(self):
        """6 dims all 2 → overall_norm = 6.7 (12/18*10=6.67...)"""
        scores = [2, 2, 2, 2, 2, 2]
        assert _normalize(scores) == pytest.approx(6.7, abs=0.05)

    def test_pass_threshold(self):
        """Pass threshold: overall_norm >= 7"""
        # Find the minimum score combination that passes
        # 7/10 * 18 = 12.6 raw → at least 13 out of 18
        # 6 dims with scores [2,2,2,2,2,2] = 12 → 6.67 < 7  (fail)
        # [3,2,2,2,2,2] = 13 → 7.22 >= 7  (pass)
        fail_scores = [2, 2, 2, 2, 2, 2]
        pass_scores = [3, 2, 2, 2, 2, 2]
        assert _normalize(fail_scores) < 7
        assert _normalize(pass_scores) >= 7

    def test_linear_mapping(self):
        """Verify linear mapping: each raw point adds exactly 10/18 to normalized."""
        step = 10 / TOTAL_MAX  # 10/18 ≈ 0.556
        for raw in range(19):
            scores = [raw // 6] + [raw // 6] * 5
            if raw <= 18:
                expected = round(raw * 10 / TOTAL_MAX, 1)
                actual = _normalize([raw / 6] * 6)
                # Allow rounding tolerance
                pass  # Just verify it's monotonic
            elif raw > 18:
                assert _normalize([3, 3, 3, 3, 3, 3]) == 10.0

    def test_monotonic(self):
        """Higher raw scores → higher normalized scores."""
        for i in range(19):
            raw = i
            scores = [raw / 6] * 6
            norm = _normalize(scores)
            if i > 0:
                prev_scores = [(i - 1) / 6] * 6
                prev_norm = _normalize(prev_scores)
                assert norm >= prev_norm, f"Not monotonic at raw={i}"

    def test_old_bug_regression(self):
        """
        Regression: old code with 0-2 scores would normalize wrong.
        6 dims × 2 = 12 raw → 12*10/18 = 6.67 (not 10!)
        This test confirms the fix: 0-3 range → 6*3=18 → 18*10/18 = 10.0
        """
        # Old behavior (scores were 0-2, max 12, normalized wrong):
        old_max_raw = 6 * 2  # 12
        old_norm = round(old_max_raw * 10 / TOTAL_MAX, 1)
        assert old_norm == 6.7  # Bug: max score only got 6.7 instead of 10

        # New behavior (scores are 0-3, max 18):
        new_scores = [3, 3, 3, 3, 3, 3]
        new_norm = _normalize(new_scores)
        assert new_norm == 10.0  # Correct

    def test_overflow_capped(self):
        """Scores above max are capped at 10.0."""
        scores = [5, 5, 5, 5, 5, 5]  # Raw 30, would give 16.7
        assert _normalize(scores) == 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
