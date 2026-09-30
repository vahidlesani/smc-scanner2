"""r33 (Viva 09-26 channel screenshots): OUT_OF_REACH measured to the nearest
EDGE (inside-zone never cancels), zone-stop heal for pre-r30 chains, the
50-bar line lifecycle law, and render-identity/zoom-freeze persistence."""
from types import SimpleNamespace

REPO = "/home/user/smc-scanner2"


def _cand(zb, zt, sl, direction="LONG", atr=0.01057, confirmed=False):
    return SimpleNamespace(
        symbol="LTCUSDT", signal_id="T-HEAL",
        direction=direction, entry_zone_bottom=zb, entry_zone_top=zt, sl=sl,
        metadata={} if not confirmed else {"technical_confirmation_complete": True},
    )


def _with_atr(c, atr):
    c.metadata = dict(c.metadata or {}); c.metadata["atr"] = atr
    return c


# ── 1. THE FIL bug: live INSIDE the zone was «4.59 ATR away» → cancelled ──
def test_out_of_reach_never_fires_inside_zone():
    import main as m
    c = _with_atr(_cand(0.889, 1.05, 0.96), 0.01057)
    assert m._scenario_out_of_reach(c, 1.018) is False   # FIL 09-26 case
    c2 = _with_atr(_cand(63.37, 72.4, 70.0), 3.7)
    assert m._scenario_out_of_reach(c2, 72.35) is False  # LTC 09-26 case


def test_out_of_reach_measures_to_nearest_edge():
    import main as m
    c = _with_atr(_cand(0.889, 1.05, 0.96), 0.01057)
    # 3.03 ATR above the TOP edge → genuinely gone (threshold 2.0)
    assert m._scenario_out_of_reach(c, 1.05 + 3.03 * 0.01057) is True
    # 2.9 ATR below the BOTTOM edge → premise gone (09-21 law preserved)
    assert m._scenario_out_of_reach(c, 0.889 - 2.9 * 0.01057) is True
    # just outside the edge (< threshold) → still waiting
    assert m._scenario_out_of_reach(c, 1.05 + 1.0 * 0.01057) is False


# ── 2. zone-stop heal: pre-r30 chains get a protective invalidation ──────
def test_zone_stop_heal_fixes_inside_zone_stops():
    import main as m
    c = _cand(63.37, 72.4, 70.244)          # the LTC display bug, verbatim
    assert m._heal_zone_stop(c, 72.22) is True
    assert c.sl < 63.37, "LONG stop must sit BELOW the zone floor"
    assert c.metadata["stop_clamped"] is True
    s = _cand(63.37, 72.4, 69.0, direction="SHORT")
    assert m._heal_zone_stop(s, 70.0) is True
    assert s.sl > 72.4, "SHORT stop must sit ABOVE the zone ceiling"


def test_zone_stop_heal_skips_confirmed_and_correct_rows():
    import main as m
    ok = _cand(63.37, 72.4, 62.0)           # already protective → untouched
    assert m._heal_zone_stop(ok, 70.0) is False and ok.sl == 62.0
    conf = _cand(63.37, 72.4, 70.244, confirmed=True)
    assert m._heal_zone_stop(conf, 70.0) is False  # lifecycle owns its stop


def test_heal_is_wired_into_monitor():
    src = open(f"{REPO}/main.py", encoding="utf-8").read()
    assert "_heal_zone_stop(candidate, current_price)" in src


# ── 3. the 50-candle lifecycle law ────────────────────────────────────────
def test_fresh_break_window_is_50_bars():
    from analysis.viva_tlbreak import load_config
    assert load_config().fresh_break_bars == 50


def test_render_keeps_broken_lines_50_bars():
    src = open(f"{REPO}/analysis/render_kit.py", encoding="utf-8").read()
    assert "max(50, int(0.5 * max(n, 1)))" in src


# ── 4. identity + zoom-freeze survive object copies (bot_kv) ─────────────
def test_render_identity_and_zoom_freeze_persist():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert 'f"render_identity:{candidate.signal_id}"' in src
    assert 'f"zoom_freeze:{candidate.signal_id}"' in src
    assert src.count("render_identity:") >= 2  # read AND write
    assert src.count("zoom_freeze:") >= 2


# ── 5. «0.00 ATR» → «داخل ناحیه» wording ──────────────────────────────────
def test_inside_zone_distance_wording():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert "داخل ناحیهٔ بررسی" in src
