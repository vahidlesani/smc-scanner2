"""r61.3-R62 — the 2026-10-01 night-fix laws (his 10-chart gallery verdict).

* «از هر جای چارت که پیوت های مهمتری است رسم بشه اما باید تا قیمت لایو بره و
  بعدش خطچین ادامه بده» — a broken leg runs DASHED through LIVE (TRX teal).
* «یک ترند میکشه بالایی رو نمیکشه» — BOTH edges always paint (DOT/LTC/ETHFI
  one-sided; the shell + zone-lane guarantees).
* STX-class: a stored edge floating FAR below the window demotes to faint
  context, never a bold trade line.
* SUI-30M-class: an apex-cut pair still REACHES LIVE dashed past the apex.
* «اهداف ۴ و ۵ رو حذف بکن چون تا تی پی ۳ داریم» — messages stop at TP3.
* LTC T739534: an ESTABLISHED break is never «out of reach»-cancelled.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot.messages_v7 as M
from test_v7 import make_candidate


def _tape(periods=170, base=100.0, drift=0.12, amp=1.6):
    import math
    ts = pd.date_range("2026-09-20", periods=periods, freq="15min")
    closes = [base + i * drift + amp * math.sin(i / 7.0) for i in range(periods)]
    return pd.DataFrame({"timestamp": ts,
                         "open": [c - 0.05 for c in closes],
                         "high": [c + 0.35 for c in closes],
                         "low": [c - 0.35 for c in closes],
                         "close": closes, "volume": [100.0] * periods})


def _cand(tape, variant="VIVA_TLBREAK", status="APPROACHING"):
    c = make_candidate(status, 8)
    c.trigger_timeframe = "15m"
    c.setup_code = "TLBREAK"
    cl = float(tape["close"].iloc[-1])
    lo_all = float(tape["low"].min())
    hi_all = float(tape["high"].max())
    c.symbol = "TESTUSDT"
    c.entry_zone_bottom, c.entry_zone_top = cl * 0.997, cl * 1.003
    c.planned_entry = cl * 1.001
    c.sl = lo_all * 0.99
    c.tp1, c.tp2 = hi_all * 1.01, hi_all * 1.04
    c.rr_tp1, c.rr_tp2 = 2.0, 4.0
    c.metadata.update({"strategy_variant": variant, "atr": 1.2,
                       "render_zones": [], "render_patterns": [],
                       "viva_break_line": round(cl * 0.995, 6)})
    return c


def _capture(monkeypatch, tape, cand):
    import matplotlib.figure as mfig
    cap = {}
    orig = mfig.Figure.savefig

    def _spy(self, *a, **k):
        cap["fig"] = self
        return orig(self, *a, **k)

    monkeypatch.setattr(mfig.Figure, "savefig", _spy)
    img = M.generate_chart(tape, cand, confirmed=False)
    assert img is not None and img[:8] == b"\x89PNG\r\n\x1a\n"
    return cap["fig"].axes[0]


# ── 1. broken leg → dashed through LIVE ─────────────────────────────────────

def test_broken_leg_dashes_through_live(monkeypatch):
    tape = _tape()
    cand = _cand(tape, variant="ALBROX_ZONE", status="EDUCATIONAL")
    ibk = len(tape) - 45
    cand.metadata["render_patterns"] = [{
        "type": "TRENDLINE",
        "lines": [{"side": "LOW", "slope": 0.10,
                   "intercept": float(tape["low"].iloc[20]) - 0.10 * 20,
                   "log_fit": False, "log_slope": 0.0, "log_intercept": 0.0,
                   "break_x": ibk, "x0": 20, "x1": len(tape) - 1,
                   "points": [], "break_ts": str(tape["timestamp"].iloc[ibk])}]}]
    ax = _capture(monkeypatch, tape, cand)
    demand = M.CHART_THEME["demand"]
    dashes = [ln for ln in ax.lines
              if ln.get_color() == demand and ln.get_linestyle() != "-"]
    assert dashes, "no dashed continuation for the broken lower edge"
    assert max(max(ln.get_xdata()) for ln in dashes) >= len(tape) - 3


# ── 2. zone lane with no stored points → BOTH edges ─────────────────────────

def test_zone_lane_gets_both_edges(monkeypatch):
    tape = _tape()
    cand = _cand(tape, variant="ALBROX_ZONE", status="EDUCATIONAL")
    ax = _capture(monkeypatch, tape, cand)
    supply, demand = M.CHART_THEME["supply"], M.CHART_THEME["demand"]

    def _solid(col):
        return [ln for ln in ax.lines if ln.get_color() == col
                and ln.get_linestyle() == "-" and ln.get_linewidth() >= 1.5]

    assert _solid(supply), "no upper edge fitted"
    assert _solid(demand), "no lower edge fitted"


# ── 3. TP rows stop at TP3 ──────────────────────────────────────────────────

def test_confirmed_message_stops_at_tp3():
    tape = _tape()
    cand = _cand(tape, status="CONFIRMED")
    cl = float(tape["close"].iloc[-1])
    cand.metadata["target_ladder"] = {
        "targets": [cl * 1.02, cl * 1.04, cl * 1.06, cl * 1.08, cl * 1.10],
        "weights": [40.0, 30.0, 30.0, 0.0, 0.0]}
    out = M._tf_channel_text(cand, "تست")
    assert "TP4" not in out and "TP5" not in out
    assert out.count("TP3") >= 1


# ── 4. an established break is never «out of reach» ─────────────────────────

def test_established_break_is_never_out_of_reach():
    import main as MAIN
    tape = _tape()
    cand = _cand(tape)
    cl = float(tape["close"].iloc[-1])
    # price 6 ATR beyond the zone in the scenario direction (the LTC shape)
    px = cl + 6.0 * 1.2
    cand.metadata["tl_fast_break"] = "اولین کلوزِ معتبر فراتر از خط/لبه"
    assert MAIN._scenario_out_of_reach(cand, px) is False
    # the same distance WITHOUT a break premise may close the chain
    cand.metadata.pop("tl_fast_break", None)
    cand.metadata.pop("break_seen_at", None)
    cand.metadata["touched"] = False
    assert MAIN._scenario_out_of_reach(cand, px) is True


# ── 5. shell guarantee: one-sided stored set gains the missing side ─────────

def test_one_sided_shell_gains_refit_side(monkeypatch):
    tape = _tape()
    cand = _cand(tape)
    hi = tape.tail(70).nlargest(3, "high").sort_values("timestamp")
    cand.metadata["viva_upper_points"] = [
        {"timestamp": str(t), "price": float(h)}
        for t, h in zip(hi["timestamp"], hi["high"])]
    src = io_src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert "len(_fits9) < 2" in src, "shell guarantee missing"
    ax = _capture(monkeypatch, tape, cand)
    # muted refit edge must exist (solid segment reaching live)
    muted = M.CHART_THEME.get("muted")
    refit = [ln for ln in ax.lines
             if muted and str(ln.get_color()).upper() == str(muted).upper()]
    assert refit, "missing-side refit line did not paint"
