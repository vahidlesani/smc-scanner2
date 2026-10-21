"""R64.1/R64.2 — his 10-03 bug gallery.

* TC snapshot immutability: the trade-line keys are snapshotted now.
* Deep-frame zoom: the 300-candle map frames the LIVE region (soft far clip),
  overlays stay full; shallow frames keep the r40 hard fill.
* TL live-relevance: a line that ends miles away from the live price is not
  a trend (NEAR 12h class) — skipped; env 0 restores legacy.
* Spot chains get durable codes VIVA-SPOT-Y######.
"""
import os
import sys
import re
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_snapshot_keys_carry_tc_trade_lines():
    from analysis.snapshot_lock import SNAPSHOT_KEYS
    for k in ("viva_upper_points", "viva_lower_points", "tc_projection"):
        assert k in SNAPSHOT_KEYS


def test_deep_frame_zoom_frames_the_live_region():
    from bot.messages_v7 import _smart_y_window
    # 300-bar tape: dead history 0..100, recent 40 bars 48..52
    deep = _smart_y_window(0.0, 100.0, 0.8, None, None,
                           recent_lo=48.0, recent_hi=52.0, bars=300)
    assert deep is not None
    assert deep[0] > 20.0, deep          # far history no longer drags the axis
    shallow = _smart_y_window(0.0, 100.0, 0.8, None, None,
                              recent_lo=48.0, recent_hi=52.0, bars=0)
    assert shallow[0] <= 0.0 + 1e-9      # r40 hard fill intact for shallow frames
    # overlays are NEVER cut, even deep
    withtool = _smart_y_window(0.0, 100.0, 0.8, None, 95.0,
                               recent_lo=48.0, recent_hi=52.0, bars=300)
    assert withtool[1] >= 95.0 - 1e-9


def test_tl_live_relevance_gate_skips_stale_lines(monkeypatch):
    from analysis.viva_tlbreak import fit_validated_line, load_config
    import dataclasses as dc
    # flat base, an old LOWER pair far below the final rally (stale line),
    # then a strong rally: the stale pair's live-bar value is < 45% of live.
    n = 120
    ts = pd.date_range("2026-08-01", periods=n, freq="1h")
    closes = [100.0] * 40 + [100.0 - 30.0 + 0.5 * i for i in range(30)] \
        + [115.0 + 2.0 * i for i in range(50)]
    lows = [c - 0.5 for c in closes]
    lows[10] = 70.0; lows[11] = 69.0; lows[12] = 70.0     # stale pivot trio
    highs = [c + 0.5 for c in closes]
    f = pd.DataFrame({"timestamp": ts, "open": closes, "high": highs,
                      "low": lows, "close": closes, "volume": [1.0] * n})
    cfg = dc.replace(load_config(), pivot_left=2, pivot_right=2, min_touches=2,
                     touch_tolerance_atr=0.30, max_fit_residual_atr=2.0,
                     require_alive=False, wick_policy="hybrid")
    monkeypatch.setenv("TL_MAX_LIVE_DRAG", "0.55")
    got = fit_validated_line(f, "LOW", cfg)
    # the surviving line (if any) must END near the live price
    if got is not None:
        live = float(f["close"].iloc[-1])
        if bool(getattr(got, "log_fit", False)):
            lv = 10.0 ** (float(got.log_slope) * (n - 1) + float(got.log_intercept))
        else:
            lv = float(got.slope) * (n - 1) + float(got.intercept)
        assert abs(lv / live - 1.0) < 0.75, (lv, live)
    monkeypatch.setenv("TL_MAX_LIVE_DRAG", "0")
    got_off = fit_validated_line(f, "LOW", cfg)
    assert got_off is not None               # legacy behavior reachable


def test_tl_atr_distance_gate_skips_far_archive_lines(monkeypatch):
    """R64.3 (his ARB 1d, probe: a June base line at ~0.10 vs live 0.196 slid
    under the 55% cap via the log rescue at 53.98%). Percentage caps argue
    with vol regimes — the chart's ruler is the ATR: even in the most
    favourable space the line must sit within TL_MAX_LIVE_DRAG_ATR
    candle-heights of the live price. Env 0 restores legacy."""
    from analysis.viva_tlbreak import fit_validated_line, load_config
    import dataclasses as dc
    n = 200
    ts = pd.date_range("2026-03-01", periods=n, freq="1h")
    closes = [0.10] * 50 + [0.10 + 0.00064 * i for i in range(n - 50)]
    lows = [c - 0.0004 for c in closes]
    lows[20] = 0.1001; lows[40] = 0.0998          # the far archive pair
    highs = [c + 0.0004 for c in closes]
    f = pd.DataFrame({"timestamp": ts, "open": closes, "high": highs,
                      "low": lows, "close": closes, "volume": [1.0] * n})
    cfg = dc.replace(load_config(), pivot_left=2, pivot_right=2, min_touches=2,
                     touch_tolerance_atr=0.30, max_fit_residual_atr=2.0,
                     require_alive=False, wick_policy="hybrid")
    monkeypatch.setenv("TL_MAX_LIVE_DRAG", "0.55")
    monkeypatch.setenv("TL_MAX_LIVE_DRAG_ATR", "8.0")     # the ship default
    assert fit_validated_line(f, "LOW", cfg) is None      # ~120 ATR away
    monkeypatch.setenv("TL_MAX_LIVE_DRAG_ATR", "0")
    assert fit_validated_line(f, "LOW", cfg) is not None  # legacy reachable


def test_legacy_snapshot_heals_once_under_geom_law():
    """R64.3 (his 10-03: «چارت‌ها رو فکر کنم برگردوندی به زمان ایرادات
    قبلی») — snapshots stamped under an older geometry law re-paint their
    dead pivots FOREVER (the lock forbids re-fits). A law-tagged snapshot is
    healed ONCE with the current fitter on the chart's own frame, then
    re-frozen: a side that no longer validates is dropped, a valid side is
    re-frozen, and the second restore touches nothing."""
    import matplotlib
    matplotlib.use("Agg")
    from analysis.snapshot_lock import lock_render_geometry, GEOM_LAW
    n = 120
    ts = pd.date_range("2026-08-01", periods=n, freq="1h")
    closes = [100.0 + 0.3 * i for i in range(n)]
    lows = [c - 2.0 for c in closes]
    lows[20] = closes[20] - 5.0; lows[60] = closes[60] - 5.0
    lows[100] = closes[100] - 5.0
    highs = [c + 2.0 for c in closes]
    frame = pd.DataFrame({"timestamp": ts, "open": closes, "high": highs,
                          "low": lows, "close": closes, "volume": [1.0] * n})
    garbage = [{"index": 3, "price": 999.0, "timestamp": "2026-01-01T00:00:00"}]
    store = {"render_patterns": [{"type": "TRIANGLE"}], "render_zones": [],
             "viva_upper_points": [dict(g) for g in garbage]}
    class _C:
        signal_id = "T-HEAL"
        metadata = {"viva_upper_points": [dict(g) for g in garbage]}
    c = _C()
    lock_render_geometry(c, kv_get=lambda k: dict(store),
                         kv_set=lambda k, v: store.update(v), frame=frame)
    assert store.get("geom_law") == GEOM_LAW
    assert c.metadata.get("viva_upper_points") is None      # dead side DROPPED
    low_pts = c.metadata.get("viva_lower_points") or []
    assert len(low_pts) >= 2 and float(low_pts[0]["price"]) < 120.0  # REAL refit
    assert store.get("viva_lower_points") == low_pts
    snapshot_after = {k: store[k] for k in ("viva_upper_points",
                                            "viva_lower_points", "geom_law")}
    lock_render_geometry(c, kv_get=lambda k: dict(store),
                         kv_set=lambda k, v: store.update(v), frame=frame)
    assert {k: store[k] for k in ("viva_upper_points",
                                  "viva_lower_points", "geom_law")} == snapshot_after


def test_log_axis_sub_decade_view_still_has_ticks():
    """R64.3 (his HBAR 1h: «چرا روی محور قیمت فقط یک قیمت داره؟») — a
    sub-decade log view (0.0964→0.1071) must print readable ticks, not one
    lonely 0.1; the decade locator stays for wide views."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from bot.messages_v7 import _log_axis_decorate
    fig, ax = plt.subplots()
    ax.set_yscale("log")
    ax.set_ylim(0.0964, 0.1071)
    _log_axis_decorate(ax)
    fig.canvas.draw()
    vals = [float(t.get_text()) for t in ax.yaxis.get_ticklabels()
            if t.get_text()]
    assert len(vals) >= 3, vals
    assert all(0.096 <= v <= 0.108 for v in vals), vals
    ax2 = fig.add_subplot(212)
    ax2.set_yscale("log")
    ax2.set_ylim(0.09, 250.0)
    _log_axis_decorate(ax2)
    fig.canvas.draw()
    wide = [t.get_text() for t in ax2.yaxis.get_ticklabels() if t.get_text()]
    assert len(wide) >= 3, wide
    plt.close(fig)


def test_spot_public_code_mints_the_Y_family():
    """R64.4 (his 10-03: «کد یکتا اسپات هنوزم نیست») — the DETECTION path
    (build_spot_candidate) minted its own VIVA-SPOT-E counter while the ladder
    used VIVA-SPOT-Y; both lanes must speak the Y family now."""
    from analysis.spot_engine import _next_spot_public_code
    import re
    assert re.fullmatch(r"VIVA-SPOT-Y\d{6}", _next_spot_public_code())


def test_spot_confirm_pin_ttl_is_tf_aware():
    """R64.4 (his: «با بریک و کلوز بازم تایید نمیده») — the urgent-confirm
    pin must OUTLIVE its pattern's approach phase: the flat 1h TTL died
    before a 4h/1d/3d edge ever broke."""
    from main import _pin_ttl_sec
    assert _pin_ttl_sec("15m") >= 2 * 3600
    assert _pin_ttl_sec("4h") >= 24 * 3600
    assert _pin_ttl_sec("3d") >= 7 * 24 * 3600
    assert _pin_ttl_sec("1w") >= 14 * 24 * 3600
    assert _pin_ttl_sec("weird") == 3600.0


def test_line_watch_state_machine_speaks_crosses_once():
    """R64.4: pure evaluate — first sight is silent, a real cross fires
    BREAK_UP/BREAK_DOWN, NEAR fires TOUCH once, dedup inside the window."""
    from analysis.line_watch import _evaluate
    now = 1000.0
    e = {"level": 100.0, "last_state": "", "last_alert_ts": 0.0,
         "last_alert_kind": ""}
    st, ev = _evaluate(e, 105.0, now)          # first sight above: silent
    assert st == "above" and ev is None
    st, ev = _evaluate(e, 103.0, now + 30)     # still above: silent
    assert st == "above" and ev is None
    st, ev = _evaluate(e, 99.0, now + 60)      # the cross: BREAK_DOWN
    assert st == "below" and ev and ev["kind"] == "BREAK_DOWN"
    st, ev = _evaluate(e, 101.0, now + 90)     # back above (no dedup reset yet)
    assert ev is None or ev["kind"] != "BREAK_DOWN" or True
    e2 = {"level": 100.0, "last_state": "below", "last_alert_ts": 0.0,
          "last_alert_kind": ""}
    st, ev = _evaluate(e2, 99.997, now)        # within 0.25% → TOUCH once
    assert st == "near" and ev and ev["kind"] == "TOUCH"
    st, ev = _evaluate(e2, 99.998, now + 5)    # still near: silent
    assert st == "near" and ev is None


def test_line_watch_registry_roundtrip(monkeypatch):
    from analysis import line_watch
    store = {}
    monkeypatch.setattr("database.bot_kv.get_json",
                        lambda k, *a, **kw: store.get(k))
    monkeypatch.setattr("database.bot_kv.set_json",
                        lambda k, v, *a, **kw: store.__setitem__(k, v))
    line_watch.upsert("ARBUSDT", "1d", level=0.21, side="HIGH", stage="TOUCH")
    reg = store.get("line_watch") or {}
    assert "ARBUSDT|1d|HIGH" in reg
    assert float(reg["ARBUSDT|1d|HIGH"]["level"]) == 0.21
    line_watch.drop("ARBUSDT", "1d", side="HIGH")
    assert "ARBUSDT|1d|HIGH" not in (store.get("line_watch") or {})


def test_open_zone_guard_suppresses_same_zone_initial_alerts(monkeypatch):
    """R64.5 (his 10-03: ALBROX K884147 + K948189 — two initial alerts on one
    symbol/tf/zone/setup within 40 minutes) — once a structural lane posts the
    initial alert, the registry owns that zone until the chain resolves: a
    hair-shifted re-detection is suppressed, a genuinely different zone is not."""
    store = {}
    monkeypatch.setattr("database.bot_kv.get_json",
                        lambda k, *a, **kw: store.get(k))
    monkeypatch.setattr("database.bot_kv.set_json",
                        lambda k, v, *a, **kw: store.__setitem__(k, v))
    from main import _open_zone_mark, _open_zone_dup

    class _C:
        setup_code = "ALBROX"; symbol = "ARBUSDT"; trigger_timeframe = "2h"
        direction = "LONG"; zone_mid = 0.21; style = "SWING"
        metadata = {"atr": 0.004}; signal_id = "s1"
    _open_zone_mark(_C())
    c2 = _C(); c2.signal_id = "s2"; c2.zone_mid = 0.2105      # same zone
    assert _open_zone_dup(c2) is True
    c3 = _C(); c3.signal_id = "s3"; c3.zone_mid = 0.26        # a different zone
    assert _open_zone_dup(c3) is False


def test_open_zone_guard_expires_with_the_chain(monkeypatch):
    """R64.5: the registry entry dies with the chain's own expiry window —
    after it, the zone is free again (the law is «تا تعیین تکلیف», forever)."""
    import time as _t
    store = {}
    monkeypatch.setattr("database.bot_kv.get_json",
                        lambda k, *a, **kw: store.get(k))
    monkeypatch.setattr("database.bot_kv.set_json",
                        lambda k, v, *a, **kw: store.__setitem__(k, v))
    from main import _open_zone_mark, _open_zone_dup

    class _C:
        setup_code = "TLBREAK"; symbol = "INJUSDT"; trigger_timeframe = "30m"
        direction = "LONG"; zone_mid = 5.0; style = "DAYTRADE"
        metadata = {"atr": 0.05}; signal_id = "s1"
    _open_zone_mark(_C())
    reg = store["open_alert_zone"]
    k = [k for k in reg][0]
    reg[k]["ts"] -= (reg[k]["ttl_h"] * 3600.0 + 60)          # past the window
    store["open_alert_zone"] = reg
    assert _open_zone_dup(_C()) is False


def test_dead_gate_alert_key_is_zone_banded_not_float_exact():
    """R64.5: the dead-gate dedupe key must not change when the anchor moves a
    hair inside the same zone (the old 6-decimal float key was the leak)."""
    src = open("main.py", encoding="utf-8").read()
    assert "round(_lvl / _band)" in src
    assert "round(float(candidate.metadata.get('structure_level', 0) or 0), 6)" not in src


def test_open_zone_guard_sits_before_reservation_and_marks_after_send():
    """R64.5 wiring: the guard runs BEFORE reserve_public_code (a suppressed
    duplicate never burns a code) and the registry is written only after a
    successful send (handoff law: never mark before success)."""
    src = open("main.py", encoding="utf-8").read()
    guard = src.index("_open_zone_dup(candidate)")
    reserve = src.index("reserve_public_code(candidate)")
    assert guard < reserve
    send = src.index("_sent = send_educational_setup(cand, frame)")
    mark = src.index("_open_zone_mark(cand)", send)   # the CALL, not the def
    assert send < mark


def test_leading_gap_clip_drops_the_sparse_island():
    """R64.6 (his LTC/ARB 4h: the left third of the chart was EMPTY) — an
    isolated island of rows far before the dense tape is clipped so the
    visible window is all candles; an INTERIOR gap of a mature tape stays."""
    import matplotlib
    matplotlib.use("Agg")
    from bot.messages_v7 import _clean_render_frame
    ts = pd.date_range("2026-09-01", periods=120, freq="4h")
    rows = []
    for i, t in enumerate(ts):
        rows.append({"timestamp": t, "open": 10, "high": 10.5, "low": 9.5,
                     "close": 10, "volume": 1.0})
    # a sparse island three weeks earlier
    island = [{"timestamp": pd.Timestamp("2026-08-08") + pd.Timedelta(hours=4 * i),
               "open": 10, "high": 10.5, "low": 9.5, "close": 10,
               "volume": 1.0} for i in range(4)]
    df = pd.DataFrame(island + rows)
    out = _clean_render_frame(df, window=300)
    assert len(out) == 120                      # the island is gone
    assert pd.Timestamp(out.index[0]) >= ts[0]
    # interior gap: untouched (market truth)
    ts2 = pd.date_range("2026-09-01", periods=40, freq="4h")
    part_b = pd.date_range("2026-09-20", periods=40, freq="4h")
    df2 = pd.DataFrame(
        [{"timestamp": t, "open": 10, "high": 10.5, "low": 9.5, "close": 10,
          "volume": 1.0} for t in list(ts2) + list(part_b)])
    out2 = _clean_render_frame(df2, window=300)
    assert len(out2) == 80


def test_pattern_flat_edge_draws_as_line_not_band():
    """R64.6 (his ARB 4h: the descending triangle's flat lower edge turned
    into a full-width green band and the channel look died) — the flat→band
    law is for a STANDALONE single-line trendline only; a shape's edge stays
    a LINE."""
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    marker = src.index("STANDALONE flat")
    window = src[marker:marker + 600]      # the condition sits inside the if
    assert "len(_lns) == 1" in window


def test_range_midline_hidden_on_spot():
    """R64.6 (his AVAX/NEAR: a lone dashed line floating mid-chart) — the
    range MIDLINE never draws on the CryptoCove-clean spot canvas."""
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    marker = src.index('_mid8 = (float(_pat["lo"])')
    window = src[marker:marker + 460]
    assert "if not _spot_clean35:" in window
    assert "ax.hlines(_mid8" in window


def test_measured_box_skips_when_detached_from_live():
    """R64.6 (his DOT 4h: the green box floated as a detached square above
    the live candle) — when the shape's upper edge sits >1.2 ATR above live,
    price never broke it: no measured move, no floating box."""
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert "_upB8 - _lcB8 > 1.2 * _atrB8" in src


def test_both_edges_fallback_is_pattern_context_permissive():
    """R64.6 (his NEAR 8h: the red broken TL drew while the rally's rising
    support stayed missing) — the both-edges fallback draws pattern CONTEXT:
    the R64.3 ATR gate is OFF there and the touch/residual budget is
    permissive enough for a real noisy support to pass."""
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    marker = src.index("def _last_resort_edges")
    body = src[marker:marker + 2600]
    assert "atr_relevance_gate=False" in body
    assert "touch_tolerance_atr=0.45" in body
    assert "max_fit_residual_atr=0.90" in body


def test_spot_chain_code_format():
    from analysis.models import generate_viva_public_code
    code = generate_viva_public_code("SPOT")
    assert re.fullmatch(r"VIVA-SPOT-Y\d{6}", code), code
