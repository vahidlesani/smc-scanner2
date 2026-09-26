"""r37 — the chart-engine calibration round (Viva 09-26, 17 screenshots).

His verbatim complaints, each mapped to the code fix this file pins:
  1. «زوم باید طوری باشه که کندلها تا حد امکان در مرکز صفحه چارت قرار بگیرند»
     → _smart_y_window centers the RECENT block (≥60% target) instead of
     clipping overlays at 45%/side.
  2. «ابزار لانگ و شورت نصفه نیمه رسم میشه» → overlays are included IN FULL;
     the 45% clip law is dead (stops are hard-bounded now, so it is safe).
  3. «ترندهای ماژور و مینور مهم اصلا دیده نمیشن و رسم نمیشن» → the render
     window widens to cover the stored r33 identity anchors.
  4. «برچسب ترند لاین و اسم الگوها رو بزنی بردار» → pattern/TRENDLINE name
     pills are deleted from the renderer.
  5. «اسپات ابزار لانگ و شورت نداره … فقط باکس سبز … وسطش هم فلش نمیخواد»
     → the futures tool (pills/guides/ledger/INFO box) never renders on
     market=SPOT; the green box anchors at the shape's UPPER edge, arrowless.
  6. «ساعت لایو کندلش درست نیست» → LIVE clock/stamp = Tehran render moment;
     3d/1w get a synthesized forming candle from a 1h probe.
  7. «برخی از تارگت ها احمقانه هستن … در روزانه در ena مثلا» → tc_projection
     is skipped when it outruns the ladder or the TF sanity band.
  8. spot stops hug the minor swing (not the far pattern base → −10.00%
     artifacts); targets anchor on real overhead resistance.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()


# ── 1+2. smart zoom: centered candles, whole tool on canvas ──────────────
def test_spot_case_tool_fully_inside_and_candles_centered():
    """DOGE-like 12h spot: 40% frame range, stop −10%, TP +6%. The window
    must contain EVERY overlay and keep the recent block centered."""
    from bot.messages_v7 import _smart_y_window
    win = _smart_y_window(0.075, 0.105, atr=0.0022,
                          ov_lo=0.0890,          # stop 10% under entry 0.0989
                          ov_hi=0.1050,          # spot box top / TP3
                          recent_lo=0.0900, recent_hi=0.0990)
    assert win is not None
    ylo, yhi = win
    assert ylo <= 0.0890 and yhi >= 0.1050, "the tool may never be clipped again"
    # r40 CHART-FILL: the whole tape is a hard bound — nothing renders invisible
    assert ylo <= 0.075 and yhi >= 0.105, "every candle visible, nothing sticks out"
    r_mid = 0.5 * (0.0900 + 0.0990)
    w_mid = 0.5 * (ylo + yhi)
    assert abs(r_mid - w_mid) <= 0.25 * (yhi - ylo), "recent block drifts off-center"
    # r40: candles may get shorter when the frame is wide — the user accepted
    # «خیلی ریز بودن کندل‌ها اشکال نداره» in exchange for full fill.
    occ = (0.0990 - 0.0900) / (yhi - ylo)
    assert occ >= 0.25, (occ,)


def test_far_level_case_still_fights_the_basement():
    """r28 regression: DASH 1D far stop (13.3 vs 55-65 candles) stays clamped."""
    from bot.messages_v7 import _smart_y_window
    ylo, yhi = _smart_y_window(55.0, 65.0, atr=4.0, ov_lo=13.3, ov_hi=65.0)
    assert ylo > 40.0 and ylo < 55.0 < yhi
    assert (10.0 / (yhi - ylo)) >= 0.34


def test_healthy_overlays_included_fully():
    from bot.messages_v7 import _smart_y_window
    ylo, yhi = _smart_y_window(97.0, 103.0, atr=1.2, ov_lo=95.8, ov_hi=104.5)
    assert ylo <= 95.8 and yhi >= 104.5


# ── 3+4+5. spot: no tool, no arrows, no name pills, upper-edge box ───────
def test_spot_never_renders_the_futures_tool():
    src = _src()
    assert "if confirmed and not _is_spot:" in src          # tool block
    assert "if confirmed and not _is_spot:\n            try:\n                _pl32" in src  # ledger
    # the pattern-name pills are GONE (Viva: «اسم الگوها رو بزنی بردار»)
    assert 'str(_pat.get("label") or _pat.get("type"))' not in src
    # no double-arrow spine anywhere — «وسطش هم فلش نمیخواد»
    assert 'arrowstyle="<->"' not in src


def test_spot_box_anchors_at_the_upper_edge():
    src = _src()
    assert "_up8 = max(float(_a8[\"slope\"]) * (count - 1)" in src   # edge AT the last candle
    assert "_bt8 = _up8" in src
    assert "NO panel clamp" in src                            # box never squashed
    assert "_bt9 = max(_bt9, _lc9)" in src                  # single-line branch
    assert "NO arrow inside the spot box" in src


def test_spot_box_top_owns_zoom_room():
    src = _src()
    assert "if _is_spot:\n                    _sbt28" in src


# ── 6. the live clock is the Tehran render moment ────────────────────────
def test_live_stamp_is_now_tehran():
    src = _src()
    assert '_live_clock = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%H:%M")' in src
    assert '_live_stamp = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%m-%d %H:%M")' in src
    # the bucket-stamp implementation is gone for good
    assert '_lt.tz_convert("Asia/Tehran").strftime("%m-%d %H:%M")' not in src


def test_synthetic_live_candle_only_for_aggregate_tfs():
    src = _src()
    assert "def _synthetic_live_candle(" in src
    assert 'if str(tf).lower() in ("3d", "1w"):' in src
    # r12 honesty elsewhere: closed tape stays closed
    assert "return None  # the tape has already closed; nothing is forming" in src


def test_synthetic_live_candle_never_fabricates_without_a_price(monkeypatch):
    import pandas as pd
    import bot.messages_v7 as M
    import data.fetcher as F

    class _C:
        symbol = "DOGEUSDT"

    monkeypatch.setattr(F, "get_klines", lambda *a, **k: None)
    df = pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-09-25 12:00", tz="UTC")],
        "open": [0.098], "high": [0.099], "low": [0.097], "close": [0.0985],
    })
    assert M._synthetic_live_candle(_C(), df) is None


# ── 7. identity anchors keep their window (major/minor trendlines) ──────
def test_render_window_widens_for_stored_anchors():
    src = _src()
    assert '_gj37(f"render_identity:{candidate.signal_id}")' in src
    assert "_need37 > _lookback" in src
    assert "_lookback = max(_lookback, min(_need37, len(df), int(_lookback * 2.2)))" in src


# ── 8. silly projections never print ─────────────────────────────────────
def test_tc_projection_clamped_to_ladder_and_tf_band():
    src = _src()
    assert '"15m": 0.05' in src and '"1d": 0.15' in src      # TF sanity band
    assert "_insane37" in src and "if _insane37:\n                            proj = None" in src
    assert "max(_lad37) * 1.01" in src                        # ladder outranks fantasy


# ── 9. spot risk levels: swing stop + structural targets ────────────────
def test_spot_stop_hugs_the_minor_swing_not_the_pattern_base():
    from analysis.spot_engine import spot_risk_levels
    out = spot_risk_levels(close=0.09894, upper=0.0985, lower_vals=[0.0800],
                           atr=0.0022, path_abs=0.09894 * 0.06,
                           swing_low=0.0955, df_highs=[0.1001, 0.1025])
    # 0.0955, NOT min(swing, 0.0800) → no more mechanical −10.00% artifacts
    assert abs(out["sl"] - 0.0955) < 1e-9, out


def test_spot_targets_anchor_on_real_resistance():
    from analysis.spot_engine import spot_risk_levels
    close = 100.0
    path = 6.0
    highs = [101.8, 103.4, 105.2]           # real overhead resistance
    out = spot_risk_levels(close=close, upper=100.2, lower_vals=[97.0],
                           atr=0.9, path_abs=path, swing_low=98.4,
                           df_highs=highs)
    t1, t2, t3 = out["targets"]
    assert abs(t1 - 101.8) < 1e-9            # TP1 = first resistance
    assert abs(t3 - 105.2) < 1e-9            # TP3 = structural top
    assert t1 < t2 < t3, (t1, t2, t3)


def test_spot_targets_fallback_stays_monotone_and_atr_honest():
    from analysis.spot_engine import spot_risk_levels
    close, path = 50.0, 3.0                  # virgin air above
    out = spot_risk_levels(close=close, upper=50.05, lower_vals=[48.0],
                           atr=0.5, path_abs=path, swing_low=49.1,
                           df_highs=[])
    t1, t2, t3 = out["targets"]
    assert t1 >= close + 0.6 * 0.5 - 1e-9    # ATR floor keeps TP1 honest
    assert t1 < t2 < t3 and t3 <= close + 1.10 * path + 1e-9


def test_scan_calls_the_risk_helper():
    src = open(os.path.join(REPO, "analysis", "spot_engine.py"), encoding="utf-8").read()
    assert "_risk = spot_risk_levels(" in src
    assert 'df_highs=list(d["high"].tail(120))' in src
    # the old far-base stop is gone
    assert "sl_struct = min(sl_struct, min(lower_vals))" not in src
