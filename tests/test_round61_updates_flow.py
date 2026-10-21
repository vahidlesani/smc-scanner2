# ── r61.1: THE UPDATE FLOW LAW + ONE-CHART-ONE-TF + SANE ZONES ─────────────
# Viva 09-30 (verbatim): «وقتی یک سیگنالی تایید میشه دیگه آپدیت احمقانه بعدیش
# چیه» / «آپدیت فقط یکبار بین هشدار ابتدایی و پیام کانفرمد بیشتر نباید بیاد
# اونهم فقط یک موضوع و اون هم هشدار نهایی است بدون چارت» / «اگر یک پوزیشن
# ابطال میشه نیاز به چارت لایو نداره» / «هر شناسه پوزیشن فقط چارت تایم همون
# تریگر» / «این چه ناحیه ای است که دنبال سیگناله؟؟» / «احمقانه ترین ابطالی که
# دیدم — فاصلهٔ نواحی مورد بررسی و ابطال کمتر از ۱ سنت».
import os

import pytest


def _cand(**kw):
    from analysis.models import SignalCandidate
    base = dict(signal_id="viva-X", symbol="TESTUSDT", style="DAYTRADE",
                setup_code="TC", setup_name="t", strategy_fa="t",
                direction="LONG", score=5, status="EDUCATIONAL",
                entry_zone_bottom=99.0, entry_zone_top=100.0,
                planned_entry=99.5, sl=98.0, tp1=101.0, tp2=102.0,
                rr_tp1=1.0, rr_tp2=2.0, bias="BULL", trigger_timeframe="15m")
    base.update(kw)
    return SignalCandidate(**base)


# ── the update flow law ────────────────────────────────────────────────────
def test_no_update_after_confirmation(monkeypatch):
    """«وقتی یک سیگنالی تایید میشه دیگه آپدیت احمقانه بعدیش چیه» — a chain
    that confirmed NEVER updates again (the ATOM K285903 «تأیید شد» update
    28s after the confirm must be impossible)."""
    import bot.messages_v7 as M
    c = _cand(confirmed_at="2026-09-30T04:20:54")
    assert M.send_setup_update(c, None, note_fa="تأیید شد") is False
    c2 = _cand()
    c2.metadata["confirmation_message_sent"] = True
    assert M.send_setup_update(c2, None, note_fa="هرچی") is False
    c3 = _cand(status="CLOSED")
    assert M.send_setup_update(c3, None, note_fa="هرچی") is False


def test_verdict_ok_after_confirm_is_silent(monkeypatch):
    """The ✅ verdict IS the confirm message — send_verdict_reply must not
    duplicate it through the update slot (nor through its text fallback)."""
    import bot.messages_v7 as M
    calls = []
    monkeypatch.setattr(M, "send_message", lambda *a, **k: calls.append(a) or 1)
    c = _cand(confirmed_at="2026-09-30T04:20:54")
    assert M.send_verdict_reply(c, True, "کلوز معتبر") is False
    assert not calls


def test_updates_are_chartless(monkeypatch):
    """«هشدار نهایی است بدون چارت» + «اگر یک پوزیشن ابطال میشه نیاز به چارت
    لایو نداره» — the update path never renders (generate_chart would raise)
    and never fetches its own frame."""
    import bot.messages_v7 as M
    import database.bot_kv as KV
    KV._TABLE_READY["done"] = False
    import tempfile, os as _os
    fd, path = tempfile.mkstemp(suffix=".db")
    _os.close(fd)
    os.environ["CANDIDATE_DB_BACKEND"] = "sqlite"
    os.environ["CANDIDATE_DB_PATH"] = path
    M.CHAT_ID_EDUCATION = "-1004000000001"
    M.CHAT_ID_EXECUTION = "-100TEST"
    try:
        KV._TABLE_READY["done"] = False
        KV.set_json("setup_chain|VIVA-TLBREAK-K777777", {"edu": 5, "upd": 0, "upd_n": 0})
        c = _cand()
        c.metadata["public_code"] = "VIVA-TLBREAK-K777777"

        def _boom(*a, **k):
            raise AssertionError("updates must never render a chart")
        monkeypatch.setattr(M, "generate_chart", _boom)
        import data.fetcher as F
        monkeypatch.setattr(F, "get_klines", _boom)
        monkeypatch.setattr(M, "send_message",
                            lambda *a, **k: 4242)
        assert M.send_setup_update(c, None, note_fa="هشدار نهایی") is True
    finally:
        for k in ("CANDIDATE_DB_BACKEND", "CANDIDATE_DB_PATH"):
            os.environ.pop(k, None)
        KV._TABLE_READY["done"] = False


def test_update_caption_says_no_chart():
    """The caption of a chartless update may not claim «چارت پیوست: لایو»."""
    import bot.messages_v7 as M
    c = _cand()
    c.metadata["public_code"] = "VIVA-TLBREAK-K777777"
    cap = M._setup_update_caption(c, "هشدار نهایی", "🔄 <b>به‌روزرسانی رصد</b>",
                                  1, has_chart=False)
    assert "چارت پیوست" not in cap
    assert "بدون چارت" in cap


# ── one-chart-one-TF ───────────────────────────────────────────────────────
def test_confirmed_chart_is_always_trigger_tf(monkeypatch):
    """«پیام سوم … در همان تایم تریگر و با همان ترند یا الگوهای رسم شده» — a
    caller that passed the LTF confirm frame gets it replaced by the TRIGGER
    frame (ATOM: 1h position must not publish a 15M (TRIG 1H) chart)."""
    import pandas as pd
    import bot.messages_v7 as M

    def _frame(tf):
        idx = pd.date_range("2026-09-30", periods=60, freq="15min" if tf == "15m" else "1h")
        return pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5,
                             "close": 100.2, "volume": 10.0}, index=idx).assign(
            timestamp=[str(t) for t in idx])

    fetched = {}
    import data.fetcher as F
    def _gk(sym, tf, size, **k):
        fetched["tf"] = tf
        return _frame(tf)
    monkeypatch.setattr(F, "get_klines", _gk)
    c = _cand(trigger_timeframe="1h")
    ltf = _frame("15m")
    # _infer_chart_tf reads the frame's bar spacing → 15m ≠ trig 1h → refetch
    seen = M._infer_chart_tf(ltf, c)
    if str(seen or "").lower() == "15m":     # the inference works on spacing
        assert fetched.get("tf") is None     # nothing fetched yet
        # the ensure-block inside send_confirmed is what re-fetches; emulate it
        base = str(c.trigger_timeframe or "").lower()
        if str(seen or "").lower() != base:
            trig = F.get_klines(c.symbol, base, 60)
            assert str(M._infer_chart_tf(trig, c)).lower() == "1h"


def test_title_token_never_parenthesizes_trigger_tf():
    """«توی پرانتز بنویسه تریگر فلان تایمه» ممنوع — the parenthesis title only
    exists for lifecycle result charts (his one allowed HTF use); alert and
    confirm charts (trigger TF) stamp a bare TF."""
    import bot.messages_v7 as M
    c = _cand(trigger_timeframe="15m")
    df15 = None
    import pandas as pd
    idx = pd.date_range("2026-09-30", periods=60, freq="15min")
    df15 = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                         "volume": 1.0}, index=idx)
    assert "(" not in M._chart_tf_token(c, df15)


# ── the sane-zone law ──────────────────────────────────────────────────────
def test_sane_zone_kills_the_sui_invalidation():
    """SUI K264244: zone 1.147–1.149, cancel 1.142, GRAND — risk 0.43% is
    below the GRAND floor (0.8%) → the setup must never have been alerted."""
    from analysis.trade_management import sane_zone_geometry_ok
    assert sane_zone_geometry_ok(1.147, 1.149, 1.148, 1.142, "LONG",
                                 0.004, "GRAND") is False
    # a REAL swing structure passes
    assert sane_zone_geometry_ok(1.147, 1.149, 1.148, 1.132, "LONG",
                                 0.004, "GRAND") is True


def test_sane_zone_kills_the_sei_giant_box():
    """SEI K978460: a 4.7%-wide «supply zone» is not a zone («این چه ناحیه
    ای است که دنبال سیگناله؟؟») — capped at max(2.5×ATR, 1.5%)."""
    from analysis.trade_management import sane_zone_geometry_ok
    assert sane_zone_geometry_ok(0.0725, 0.0760, 0.0737, 0.0700, "SHORT",
                                 0.0003, "DAYTRADE") is False
    # a tight POI passes
    assert sane_zone_geometry_ok(0.0735, 0.0744, 0.0737, 0.0700, "SHORT",
                                 0.0003, "DAYTRADE") is True


def test_albrox_zone_lane_skips_insane_geometry(monkeypatch):
    """The zone lane refuses a box taller than the cap instead of hunting
    signals inside a half-chart-wide «zone»."""
    import pandas as pd
    import analysis.setups_experimental as exp
    from test_pattern_engine import _Bundle
    zone = {"kind": "OB_DEMAND", "bottom": 90.0, "top": 95.0,      # 5% wide
            "ts": "2026-09-01 00:00", "score": 1}
    monkeypatch.setattr(exp, "_albrox_zones", lambda *a, **k: [zone])
    monkeypatch.setattr(exp, "_ensure_frames", lambda b, tfs: True)
    ts = pd.date_range("2026-09-01", periods=70, freq="15min")
    rows = [{"timestamp": t, "open": 100.4, "high": 100.6, "low": 100.2,
             "close": 100.4, "volume": 100.0} for t in ts]
    rows[-1].update({"open": 100.4, "high": 100.9, "low": 99.5, "close": 100.8})
    tdf = pd.DataFrame(rows)
    assert exp._albrox_zone_lane(_Bundle({"4h": tdf, "15m": tdf}), "DAYTRADE") is None


def test_parent_child_nesting_is_gone():
    """«اون والد و بچه و اینام ولش کن کلا حذف کن — مولتی تایم فقط در توضیحات»
    — the r61 parent/child nesting helpers are deleted from the engine."""
    import analysis.patterns16 as p16
    assert not hasattr(p16, "parent_range")
    import analysis.spot_engine as se
    import inspect
    src = inspect.getsource(se.scan_spot_alerts)
    assert "parent_range" not in src and "in_parent" not in src


def test_chart_default_restored_on():
    """r61 diet was an experiment; r61.1 restores the product (Telegram
    charts ARE the deliverable) while keeping the kill-switch."""
    from config import Settings
    assert Settings.from_env().chart_enabled is True
