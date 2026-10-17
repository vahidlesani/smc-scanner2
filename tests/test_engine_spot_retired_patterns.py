"""Regression tests for Spot's retired pivot-pattern boundary."""
from types import SimpleNamespace

import pandas as pd


def test_spot_best_pattern_does_not_rank_retired_pivot_families(monkeypatch):
    from analysis import engine_spot

    retired = SimpleNamespace(slug="DOUBLE_TOP", score=99.0)
    live = SimpleNamespace(slug="WEDGE_FALLING", score=8.0)
    monkeypatch.setattr(engine_spot.vg, "fit_patterns", lambda *a, **k: [live])
    monkeypatch.setattr(engine_spot.vg, "detect_pivot_patterns", lambda *a, **k: [retired])

    assert engine_spot.best_pattern(pd.DataFrame(), "4h") is live


def test_spot_best_pattern_returns_none_when_only_retired_pivots_exist(monkeypatch):
    from analysis import engine_spot

    retired = SimpleNamespace(slug="INV_HEAD_SHOULDERS", score=99.0)
    monkeypatch.setattr(engine_spot.vg, "fit_patterns", lambda *a, **k: [])
    monkeypatch.setattr(engine_spot.vg, "detect_pivot_patterns", lambda *a, **k: [retired])

    assert engine_spot.best_pattern(pd.DataFrame(), "4h") is None


def test_spot_best_pattern_filters_retired_results_from_geometry_detector(monkeypatch):
    from analysis import engine_spot

    retired = SimpleNamespace(slug="DOUBLE_BOTTOM", score=99.0)
    live = SimpleNamespace(slug="WEDGE_FALLING", score=8.0)
    monkeypatch.setattr(engine_spot.vg, "fit_patterns", lambda *a, **k: [retired])
    monkeypatch.setattr(engine_spot.vg, "detect_pivot_patterns", lambda *a, **k: [live])

    assert engine_spot.best_pattern(pd.DataFrame(), "4h") is live
