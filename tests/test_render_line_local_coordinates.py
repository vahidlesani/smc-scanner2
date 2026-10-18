"""Regression guard for render-line ranking across fit-window sizes.

The renderer fits candidates in local tail windows (60/90/120/180 bars).
Proximity must be measured at each candidate's local endpoint with its
price_at() method so log-fit curves are not treated as linear projections.
"""
from pathlib import Path


def test_render_line_score_uses_local_endpoint_and_calibrated_price():
    source = Path(__file__).resolve().parents[1] / "analysis" / "render_kit.py"
    text = source.read_text(encoding="utf-8")
    start = text.index("        def _score(ln)")
    end = text.index("\n        def _best(side: str):", start)
    body = text[start:end]

    assert 'getattr(ln, "last_index", n)' in body
    assert "ln.price_at(_x_live)" in body
    assert 'float(getattr(ln, "slope")) * n' not in body
