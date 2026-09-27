"""
tests/test_statistics.py
Automated tests for Applied Statistics & Student's t-test (backend/comparison.py)
"""

import pytest
from backend.comparison import _calc_stats


def test_calc_stats_descriptive_metrics():
    sample = [10.0, 20.0, 30.0, 40.0, 50.0]
    res = _calc_stats(sample)

    assert res["mean"] == 30.0
    assert res["median"] == 30.0
    assert res["min"] == 10.0
    assert res["max"] == 50.0
    assert res["variance"] == 250.0
    assert round(res["std_dev"], 1) == 15.8


def test_calc_stats_empty_sample():
    res = _calc_stats([])
    assert res["mean"] == 0.0
    assert res["variance"] == 0.0
