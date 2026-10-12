"""R72-VIVA (2026-10-12) — مولتی‌تایم فقط در توضیحات و تحلیل.

His verbatim ruling: «مولتی تایم فقط در توضیحات و تحلیل باید بیاد حق نداده تایم
تریگر و چارت رو هرجا خواست تغییر بده .. اصلا قفل اسنپ شات واسه همین بود که گذاشته
شده .. اگر نیست بذار .. هر شناسه کد از اولین هشدار و رسم پترن تا پایان نتیجه نباید
ریفیت و مولتی تایم فریم بشه .. فقط برای کشیده نشدن ابزار لانگ و شورت اگر کندلها از
آن خارج شدند در تایم بالاتر میتونه نشون بده .. اونم بدون ریفیت پترنها یا ترندلاین ها»

Pinned here:
1. a locked code NEVER re-fits (even with allow_refit=True);
2. the ONLY legal TF change: candle leaves the long/short tool → view one step
   up, trigger_timeframe and the stored pattern geometry untouched;
3. no escape → no TF change, no note;
4. MTF data feeds text builders only — never chart geometry;
5. trigger_timeframe is written only at candidate construction;
6. the snapshot lock is wired into every chart path («اگر نیست بذار»).
"""

import os
import re
import sys

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _src(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ───────────────── 1) locked code never re-fits ─────────────────

def test_locked_code_never_refits_even_with_refit_allowed():
    from bot.messages_v7 import _native_patterns_for_frame
    stored = [{"type": "WEDGE_FALLING",
               "lines": [{"side": "LOW", "points": [
                   {"timestamp": "2026-09-01 00:00", "price": 90.0},
                   {"timestamp": "2026-09-02 00:00", "price": 95.0}]}]}]
    ts = pd.date_range("2026-10-10 00:00", periods=120, freq="15min")
    frame = pd.DataFrame({"timestamp": ts, "open": [100.0] * 120,
                          "high": [101.0] * 120, "low": [99.0] * 120,
                          "close": [100.5] * 120, "volume": [10.0] * 120})
    frame = frame.set_index("timestamp")
    # anchors are weeks outside this frame — an unlocked refit would swap them
    out = _native_patterns_for_frame(frame, "LONG", "1h", "R72-LOCK", stored,
                                     locked=True, allow_refit=True)
    assert out == stored


# ─────────── 2+3) the tool-exit exception (and nothing else) ───────────

def _view_candidate(**meta):
    from analysis.models import SignalCandidate
    md = {"atr": 1.0, "touched": True}
    md.update(meta)
    return SignalCandidate(
        signal_id="R72-VIEW", symbol="LINKUSDT", style="DAYTRADE",
        setup_code="TLBREAK", setup_name="t", strategy_fa="t",
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=11.0, entry_zone_top=11.1, planned_entry=11.05,
        sl=10.42, tp1=11.67, tp2=12.35, rr_tp1=1.0, rr_tp2=2.0, bias="BULL",
        trigger_timeframe="15m", mandatory_gates={"zone": True},
        created_at="2026-10-10T09:00:00+00:00",
        confirmed_at="2026-10-10T09:10:00+00:00", metadata=md)


def test_tool_escape_steps_view_up_without_refit_or_trigger_change():
    import bot.messages_v7 as M
    stored_pats = [{"type": "CHANNEL_ASCENDING",
                    "lines": [{"side": "HIGH", "points": [
                        {"timestamp": "2026-10-09 12:00", "price": 11.90},
                        {"timestamp": "2026-10-10 06:00", "price": 12.40}]}]}]
    cand = _view_candidate(tool_entry_ts="2026-10-10T09:00:00+00:00",
                           render_patterns=[dict(p) for p in stored_pats])
    # candles CLOSED above the tool band (top level 12.35) → escape
    ts = pd.date_range("2026-10-10 09:00", periods=30, freq="15min")
    frame = pd.DataFrame({"timestamp": ts, "open": [12.90] * 30,
                          "high": [13.10] * 30, "low": [12.80] * 30,
                          "close": [13.00] * 30, "volume": [1000.0] * 30})
    view, escaped, note = M._lifecycle_view_plan(
        cand, now=pd.Timestamp("2026-10-10 17:00"), frame=frame)
    assert escaped >= 1
    assert view == "1h"                       # ONE step up the ladder, no more
    assert cand.trigger_timeframe == "15m"    # trigger TF untouched
    assert cand.metadata["render_patterns"] == stored_pats   # no refit
    assert "تریگر" in note                    # the ordered note carries it


def test_inside_the_tool_the_view_stays_on_trigger_tf():
    import bot.messages_v7 as M
    cand = _view_candidate(tool_entry_ts="2026-10-10T09:00:00+00:00")
    ts = pd.date_range("2026-10-10 09:00", periods=30, freq="15min")
    frame = pd.DataFrame({"timestamp": ts, "open": [11.20] * 30,
                          "high": [11.35] * 30, "low": [11.05] * 30,
                          "close": [11.20] * 30, "volume": [1000.0] * 30})
    view, escaped, note = M._lifecycle_view_plan(
        cand, now=pd.Timestamp("2026-10-10 17:00"), frame=frame)
    assert (view, escaped, note) == ("15m", 0, "")


# ───────────────── 4) MTF feeds text builders only ─────────────────

def test_mtf_data_never_feeds_chart_geometry_modules():
    for rel in ("analysis/render_kit.py", "analysis/snapshot_lock.py",
                "analysis/viva_geometry.py", "analysis/pattern_engine.py",
                "analysis/spot_pattern_engine.py"):
        src = _src(rel)
        assert "mtf_struct" not in src, rel
        assert "mtf_fa" not in src, rel


def test_mtf_consumers_in_messages_are_text_builders():
    src = _src("bot/messages_v7.py").splitlines()
    text_fns = {"_htf_context_bits", "_tf_channel_text", "send_ladder_event",
                "send_trade_close_event", "send_trailing_note"}
    cur = ""
    offenders = []
    for i, line in enumerate(src, 1):
        m = re.match(r"\s*def (\w+)", line)
        if m:
            cur = m.group(1)
        if re.search(r"mtf_struct|mtf_fa|monitor_tf", line) \
                and not line.strip().startswith("#"):
            if cur not in text_fns:
                offenders.append(f"{i}:{cur}: {line.strip()[:70]}")
    assert not offenders, "MTF data reached a non-text function:\n" + "\n".join(offenders)


# ───────────── 5) trigger TF is written only at construction ─────────────

def test_trigger_timeframe_written_only_at_creation():
    for base in ("bot", "analysis"):
        for fn in sorted(os.listdir(os.path.join(_ROOT, base))):
            if not fn.endswith(".py"):
                continue
            rel = f"{base}/{fn}"
            src = _src(rel)
            for m in re.finditer(r"\.trigger_timeframe\s*=(?!=)", src):
                line = src[:m.start()].count("\n") + 1
                body = src.splitlines()[line - 1]
                assert rel == "bot/messages_v7.py" and "event[" in body, (
                    f"{rel}:{line} rewrites trigger_timeframe: {body.strip()}")


# ───────────── 6) the snapshot lock is wired into every chart path ─────────────

def test_snapshot_lock_exists_and_is_wired():
    assert "lock_render_geometry" in _src("bot/messages_v7.py")
    assert "lock_render_geometry" in _src("analysis/spot_engine.py")
    from analysis.snapshot_lock import SNAPSHOT_KEYS
    for k in ("render_patterns", "render_zones", "render_htf_pattern",
              "viva_upper_points", "viva_lower_points",
              "pattern_geo", "break_line_geo"):
        assert k in SNAPSHOT_KEYS, k
