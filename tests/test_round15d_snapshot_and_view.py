"""Round 15 phase 4 — his 09-22 list, the two structural items.

1. «اون اسنپ‌شات که گفتی چی شد؟ انجام بده» → the confirmation moment freezes
   entry / stop / target ladder / render commands (confirmed_snapshot) and every
   later absorb or update must re-impose it — only trailing and hit-index move.
2. «ابزار لانگ و شورت مثل چارت لینک کش اومده … به‌جاش یه تایم بالاتر بره» →
   a tool that spans more than its own designed tape (42 forward bars) is
   re-rendered ONE timeframe up with the ordered note, shape and place intact.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────── 1) snapshot freeze ───────────────────────────

def _confirmed():
    from analysis.models import SignalCandidate
    return SignalCandidate(
        signal_id="R15D-1", symbol="SUIUSDT", style="DAYTRADE",
        setup_code="PINWALLQ", setup_name="t", strategy_fa="t",
        direction="SHORT", score=8, status="CONFIRMED",
        entry_zone_bottom=91.4, entry_zone_top=92.0, planned_entry=91.8,
        sl=93.4, tp1=90.2, tp2=88.9, rr_tp1=1.0, rr_tp2=2.0, bias="BEAR",
        trigger_timeframe="15m", mandatory_gates={"zone": True},
        created_at="2026-09-21T09:03:00+00:00",
        confirmed_at="2026-09-21T09:05:00+00:00",
        metadata={"atr": 0.8, "touched": True,
                  "target_ladder": {"targets": [90.2, 88.9, 87.1],
                                    "weights": [40.0, 30.0, 30.0],
                                    "path_pct": 4.2},
                  "tool_entry_ts": "2026-09-21T09:04:00+00:00",
                  "render_patterns": [{"type": "WEDGE_FALLING", "lo": 88.0, "hi": 93.0}],
                  "pattern_band": {"kind": "WEDGE_FALLING", "lo": 88.0, "hi": 93.0,
                                   "ts_last": "2026-09-21 09:00", "tf_minutes": 15.0}})


def test_confirmation_freezes_the_whole_plan():
    from analysis.quality_engine import freeze_confirmed_snapshot
    cand = _confirmed()
    snap = freeze_confirmed_snapshot(cand)
    assert snap["entry"] == 91.8 and snap["sl"] == 93.4
    assert snap["targets"] == [90.2, 88.9, 87.1]
    assert snap["weights"] == [40.0, 30.0, 30.0]
    assert snap["tool_entry_ts"] == "2026-09-21T09:04:00+00:00"
    assert snap["pattern_band"]["kind"] == "WEDGE_FALLING"
    assert cand.metadata["confirmed_snapshot_fa"]


def test_an_update_or_absorb_can_never_slide_a_confirmed_plan():
    from analysis.quality_engine import freeze_confirmed_snapshot, apply_confirmed_snapshot
    cand = _confirmed()
    freeze_confirmed_snapshot(cand)
    # an absorb / fresh scan moved everything — the snapshot must win
    cand.planned_entry = 95.0
    cand.sl = 99.9
    cand.tp1 = 70.0
    cand.tp2 = 60.0
    cand.metadata["target_ladder"] = {"targets": [70.0, 60.0], "weights": [60.0, 40.0]}
    cand.metadata["tool_entry_ts"] = "2026-09-22T00:00:00+00:00"
    assert apply_confirmed_snapshot(cand) is True
    assert cand.planned_entry == 91.8 and cand.sl == 93.4
    assert cand.tp1 == 90.2 and cand.tp2 == 88.9
    assert cand.metadata["target_ladder"]["targets"] == [90.2, 88.9, 87.1]
    assert cand.metadata["target_ladder"]["weights"] == [40.0, 30.0, 30.0]
    assert cand.metadata["tool_entry_ts"] == "2026-09-21T09:04:00+00:00"
    assert cand.metadata["snapshot_reapplied_at"]


def test_enforce_freezes_on_first_sight_and_reapplies_later():
    from analysis.quality_engine import enforce_confirmed_snapshot
    cand = _confirmed()
    assert enforce_confirmed_snapshot(cand) == "frozen"
    cand.sl = 100.0
    assert enforce_confirmed_snapshot(cand) == "applied"
    assert cand.sl == 93.4
    # an APPROACHING scenario is never touched
    cand2 = _confirmed()
    cand2.status = "APPROACHING"
    cand2.metadata.pop("confirmed_snapshot", None)
    assert enforce_confirmed_snapshot(cand2) == ""


def test_the_monitor_and_the_absorb_path_both_call_the_freeze():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
    assert "freeze_confirmed_snapshot" in main_src
    assert "enforce_confirmed_snapshot" in main_src
    store_src = open(os.path.join(root, "database", "candidate_store.py"),
                     encoding="utf-8").read()
    assert "_apply_snap(holder)" in store_src


# ───────────────────── 2) the stretched tool steps up a TF ─────────────────

def _view_candidate(**meta):
    from analysis.models import SignalCandidate
    md = {"atr": 1.0, "touched": True}
    md.update(meta)
    return SignalCandidate(
        signal_id="R15D-2", symbol="LINKUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="t", strategy_fa="t",
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=11.0, entry_zone_top=11.1, planned_entry=11.05,
        sl=10.42, tp1=11.67, tp2=12.35, rr_tp1=1.0, rr_tp2=2.0, bias="BULL",
        trigger_timeframe="15m", mandatory_gates={"zone": True},
        created_at="2026-09-17T05:00:00+00:00",
        confirmed_at="2026-09-17T05:10:00+00:00", metadata=md)


def _quiet_frame(entry_ts, bars=150):
    ts = pd.date_range(entry_ts, periods=bars, freq="15min")
    return pd.DataFrame({"timestamp": ts, "open": [11.2] * bars,
                         "high": [11.35] * bars, "low": [11.05] * bars,
                         "close": [11.2] * bars, "volume": [1000] * bars})


def test_a_days_old_tool_is_never_shown_stretched_on_the_trigger_tf():
    """The LINK case: a 15m tool that has been alive for days must come out on
    ONE TF up with its own shape — never as a canvas-wide stretched box."""
    import bot.messages_v7 as M
    cand = _view_candidate(tool_entry_ts="2026-09-17T05:00:00+00:00")
    frame = _quiet_frame(pd.Timestamp("2026-09-17 05:00"), bars=150)
    now = pd.Timestamp("2026-09-21 12:00")          # ~430 bars of 15m later
    view, escaped, note = M._lifecycle_view_plan(cand, now=now, frame=frame)
    assert view == "1h", (view, note)
    assert escaped >= 1 and note


def test_a_tool_wider_than_its_own_tape_steps_up_even_without_escape(monkeypatch):
    """Safety net for the no-tape path: when escape cannot be measured but the
    tool already spans more than its own 42-bar tape, the same one-TF step up
    fires with the ordered «کش می‌آمد» note."""
    import bot.messages_v7 as M
    monkeypatch.setattr(M, "_tool_escape", lambda *a, **k: 0)
    cand = _view_candidate(tool_entry_ts="2026-09-17T05:00:00+00:00")
    frame = _quiet_frame(pd.Timestamp("2026-09-21 11:00"), bars=60)
    view, escaped, note = M._lifecycle_view_plan(
        cand, now=pd.Timestamp("2026-09-21 12:00"), frame=frame)
    assert view == "1h" and escaped == 0
    assert "کش" in note and "1H" in note


def test_inside_the_designed_tape_the_view_stays_on_the_trigger_tf():
    import bot.messages_v7 as M
    cand = _view_candidate(tool_entry_ts="2026-09-21T09:00:00+00:00")
    frame = _quiet_frame(pd.Timestamp("2026-09-21 09:00"), bars=43)
    view, escaped, note = M._lifecycle_view_plan(
        cand, now=pd.Timestamp("2026-09-21 19:30"), frame=frame)   # 42 bars
    assert (view, escaped) == ("15m", 0), (view, note)


def test_chart_writings_and_the_green_marker_never_sit_on_the_candles():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    # the entry triangle glyph is gone
    assert 'marker="^", s=130' not in src and 'marker="v", s=130' not in src
    # Viva 09-23 REVISED: the chart owns the FULL canvas — no carved left
    # margin any more; notes float INSIDE the panel as chips (his «چارت من
    # باید کامل باشه مثل چارت تریدینگ ویو»)
    assert "_MARGIN = 0.115" not in src and "fig.text(_x_notes," not in src
    assert "notes float INSIDE the panel" in src.replace("'", '"') or "_x = _pos.x0" in src
    # …and the tool's own read-out left the tape as well
    assert "fig.text(\n                _posi.x0 + 0.012," in src
    # zones are on a diet: at most two per side
    assert "sorted(_zs8, key=_zone_importance)[:2]" in src
