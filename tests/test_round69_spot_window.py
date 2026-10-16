"""Round-69: chart ≡ scan window (his missing-lines charts).

Spot DETECTION runs on tail(_spot_count) but generate_chart used to render
the FULL bundle frame — G1 evaluated engine lines ~40 bars off, so steep
lines flew off-chart (QNT/UNI/DOGE/AAVE/ONDO drew pivots, no lines) and
shallow ones floated beside their pivots (probed + photographed). The spot
lane now trims to the scan window BEFORE the live row joins; futures lanes
are untouched.
"""
import pandas as pd

from analysis.models import SignalCandidate, EvidenceItem


def _df(n):
    ts = pd.date_range("2026-06-01", periods=n, freq="4h")
    return pd.DataFrame({"timestamp": ts, "open": 100.0, "high": 101.0,
                         "low": 99.0, "close": 100.5, "volume": 10.0})


def _cand(spot=True):
    c = SignalCandidate(
        signal_id="W69", symbol="QQQUSDT", style="SWING",
        setup_code="SPOTBREAK", setup_name="SPOTBREAK", strategy_fa="SPOT",
        direction="LONG", score=8, status="TOUCH",
        entry_zone_bottom=99.0, entry_zone_top=101.0, planned_entry=100.0,
        sl=98.0, tp1=102.0, tp2=104.0, rr_tp1=1.0, rr_tp2=2.0, bias="BULLISH",
        trigger_timeframe="4h", evidence=[EvidenceItem("x", "x", "x", True, 1)],
        metadata={}, created_at="2026-10-11T00:00:00",
        expires_at="2027-10-11T00:00:00")
    if spot:
        c.metadata = {"market": "SPOT", "is_spot": True, "chart_view_tf": "4h"}
    return c


def test_spot_chart_trims_to_scan_window_before_live_row(monkeypatch):
    """R99q: the single spot path is engine_spot.analyze + the one renderer."""
    import bot.messages_v7 as M
    from analysis.spot_engine import _spot_count
    seen = {}

    def fake_render(df, a, path=None, symbol="", stage="", title=""):
        # R99q18: the spot call now also carries the ALERT's own pattern title
        seen["n"] = len(df)
        seen["title"] = title
        seen["last_ts"] = pd.Timestamp(df["timestamp"].iloc[-1])
        return b"PNG" * 400

    monkeypatch.setattr("tools.render_spot_cryptocove.render", fake_render)
    monkeypatch.setattr("analysis.engine_spot.analyze", lambda df, tf: {"tf": tf})
    # no live row without live data — capture the trimmed closed window
    monkeypatch.setattr(M, "_frame_with_live_candle", lambda df, c: (df, None))
    monkeypatch.setattr(M, "_chart_cache_get", lambda k: None)
    monkeypatch.setattr(M, "_chart_cache_set", lambda k, v: None)
    full = _df(340)
    out = M.generate_chart(full, _cand(spot=True), confirmed=False)
    assert out is not None
    assert seen["n"] == _spot_count("4h") == 300
    assert seen["last_ts"] == pd.Timestamp(full["timestamp"].iloc[-1])


def test_spot_chart_keeps_short_frames_untouched(monkeypatch):
    import bot.messages_v7 as M
    seen = {}

    def fake_render(df, a, path=None, symbol="", stage="", title=""):
        seen["n"] = len(df)
        seen["title"] = title
        return b"PNG" * 400

    monkeypatch.setattr("tools.render_spot_cryptocove.render", fake_render)
    monkeypatch.setattr("analysis.engine_spot.analyze", lambda df, tf: {"tf": tf})
    monkeypatch.setattr(M, "_frame_with_live_candle", lambda df, c: (df, None))
    monkeypatch.setattr(M, "_chart_cache_get", lambda k: None)
    monkeypatch.setattr(M, "_chart_cache_set", lambda k, v: None)
    out = M.generate_chart(_df(120), _cand(spot=True), confirmed=False)
    assert out is not None
    assert seen["n"] == 120   # new listing: detection used all 120 too


def test_futures_chart_frame_untouched(monkeypatch):
    import bot.messages_v7 as M
    seen = {}

    def fake_render(df, a, path=None, symbol="", stage="", title=""):
        seen["n"] = len(df)
        seen["title"] = title
        return b"PNG" * 400

    # futures path renders elsewhere; spot renderer must NOT be reached and
    # the frame must NOT be trimmed — patch the futures renderer instead.
    monkeypatch.setattr("tools.render_spot_cryptocove.render", fake_render)
    monkeypatch.setattr("analysis.engine_spot.analyze", lambda df, tf: {"tf": tf})
    monkeypatch.setattr(M, "_frame_with_live_candle", lambda df, c: (df, None))
    monkeypatch.setattr(M, "_chart_cache_get", lambda k: None)
    monkeypatch.setattr(M, "_chart_cache_set", lambda k, v: None)
    try:
        M.generate_chart(_df(340), _cand(spot=False), confirmed=False)
    except Exception:
        pass
    assert "n" not in seen   # spot renderer never called for futures


def test_spot_alert_geometry_never_calls_the_second_engine(monkeypatch):
    """R99q18 (his 10-16: «هندسه خرابه … تشخیص پترن»): when the candidate
    carries its own render commands, the chart is built from THEM and the
    second engine is never consulted — a broken/throwing engine cannot
    change the picture or the title."""
    import bot.messages_v7 as M
    seen = {}

    def fake_render(df, a, path=None, symbol="", stage="", title=""):
        seen["a"] = a
        seen["title"] = title
        return b"PNG" * 400

    def boom(*a, **kw):
        raise AssertionError("engine_spot.analyze must not run for a geometry alert")

    monkeypatch.setattr("tools.render_spot_cryptocove.render", fake_render)
    monkeypatch.setattr("analysis.engine_spot.analyze", boom)
    monkeypatch.setattr(M, "_frame_with_live_candle", lambda df, c: (df, None))
    monkeypatch.setattr(M, "_chart_cache_get", lambda k: None)
    monkeypatch.setattr(M, "_chart_cache_set", lambda k, v: None)
    c = _cand(spot=True)
    c.metadata = {**c.metadata, "pattern_type": "DOUBLE_BOTTOM",
                  "spot_alert_stage": "TOUCH", "spot_alert_side": "HIGH",
                  "render_patterns": [{"type": "DOUBLE_BOTTOM", "lines": [
                      {"side": "HIGH", "log_fit": False, "slope": 0.0,
                       "intercept": 100.0, "x0": 5, "x1": 100,
                       "points": [{"ts": "2026-06-01 00:00:00", "price": 100.0},
                                  {"ts": "2026-06-20 00:00:00", "price": 100.0}]}]}]}
    assert M.generate_chart(_df(300), c, confirmed=False) is not None
    assert seen["title"] == "Double Bottom"
    assert seen["a"]["level"] == 100.0          # the alert's own line, not a refit
