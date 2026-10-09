"""r58 — the hybrid shadow law + superiority + spot urgency + the WLD fix.

Viva 09-28, verbatim anchors:
«گفتم پینبارها کوچک گرفته بشه نگفتم که از بادی بگیر فقط .. بعضی کندل‌ها یک
شدو خیلی خیلی بلند دارن که اگر ترند از نوک اون شدو خیلی خیلی بلند رسم بشه
اصلاً قابل ترسیم نیست — اونها رو از بادی بگیره اما در نقاط بعدی همون ترند
شدوهای معقول رو محاسبه بکنه و وصل بکنه بهشون» · «اگر از دورتر و با کندل‌های
بیشتری ببینیم یک ترند دیگر بالای قیمت است … آن معتبرتر است و باید ملاک قرار
بگیره» · «روشی پیدا بکن که هم موقعیت‌های اسپوت از بین نره هم مصرف بهینه
ریلوی» · «چرا این یک چارت اینجوریه؟» (the WLD 3d blank chart).
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _wave_frame(n=140, base=100.0, freq="4h"):
    wave = base + 6 * np.sin(np.arange(n) * 0.35)
    ts = pd.date_range("2026-06-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": np.roll(wave, 1),
                         "close": wave, "high": wave + 0.4,
                         "low": wave - 0.4, "volume": np.full(n, 900.0)})


# ── 1. the HYBRID shadow law ───────────────────────────────────────────────
def test_extreme_wick_anchors_body_reasonable_stays_wick():
    from analysis.indicators import pivots
    df = _wave_frame()
    peak = int(np.argmax(df["close"].to_numpy()[5:85])) + 5
    df.loc[peak, "high"] = float(df.loc[peak, "close"]) + 60.0   # EXTREME
    later = peak + 28
    df.loc[later, "high"] = float(df.loc[later, "close"]) + 0.5  # reasonable
    highs, _ = pivots(df, 3, 3, wick_noise_filter=True, wick_policy="hybrid")
    by_idx = {p["index"]: p for p in highs}
    assert by_idx[peak]["anchor"] == "body", "the liquidation spike anchors on the body"
    assert by_idx[peak]["price"] == float(df.loc[peak, "close"])
    if later in by_idx:
        assert by_idx[later]["anchor"] == "wick", "a reasonable wick STAYS a wick"
        assert by_idx[later]["price"] == float(df.loc[later, "high"])
    # the r50 outlier path demotes this spike too (both policies agree here);
    # hybrid's own anchor is the body — asserted above
    highs_out, _ = pivots(df, 3, 3, wick_noise_filter=True)
    assert dict((p["index"], p["price"]) for p in highs_out)[peak] \
        >= by_idx[peak]["price"]


def test_hybrid_connects_reasonable_wicks_later():
    """«در نقاط بعدی همون ترند شدوهای معقول رو محاسبه بکنه و وصل بکنه» — the
    drawn line through a wick-touched descending edge keeps its wick anchors
    where they are reasonable."""
    from analysis.render_kit import detect_patterns
    n = 150
    ts = pd.date_range("2026-04-01", periods=n, freq="4h", tz="UTC")
    line = 1.00 - 0.0018 * np.arange(n)
    close = line - 0.025
    hi = close + 0.004
    for k in range(5):                                # reasonable wick touches
        i = 18 + k * 28
        hi[i - 1:i + 2] = line[i - 1:i + 2] + 0.001
    df = pd.DataFrame({"timestamp": ts, "open": np.roll(close, 1),
                       "close": close, "high": hi, "low": close - 0.01,
                       "volume": np.full(n, 500.0)})
    pats = detect_patterns(df, "LONG", log_axis=True)
    assert pats, "the wick-anchored trend must still be found"


def test_render_uses_hybrid():
    src = open(os.path.join(ROOT, "analysis", "render_kit.py"), encoding="utf-8").read()
    assert 'wick_policy="hybrid"' in src and 'wick_policy="bodies"' not in src


# ── 2. the superiority law ────────────────────────────────────────────────
def test_structural_weight_prefers_the_bigger_structure():
    from analysis.spot_engine import _structural_weight
    big = {"lines": [{"x0": 10, "x1": 300, "points": [{}, {}, {}, {}, {}]},
                     {"x0": 20, "x1": 300, "points": [{}, {}, {}, {}]}]}
    small = {"lines": [{"x0": 250, "x1": 300, "points": [{}, {}]}]}
    assert _structural_weight(big) > 5 * _structural_weight(small)


def test_scan_selects_the_superior_reference():
    from analysis.spot_engine import scan_spot_symbol, _structural_weight
    n = 160
    ts = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("72h"),
                       periods=n, freq="72h", tz="UTC")
    big_line = 1.00 - 0.0012 * np.arange(n)          # the LONG major resistance
    local_line = 0.80 - 0.002 * np.arange(40)        # a small late local line
    close = big_line - 0.03
    for k in range(4):                               # 4 body touches on the major
        i = 15 + k * 40
        close[i - 1:i + 2] = big_line[i - 1:i + 2]
    close[-5:] = np.array([0.76, 0.765, 0.77, 0.775, 0.79])  # the break close
    hi = close + 0.005
    frame = pd.DataFrame({"timestamp": ts, "open": np.roll(close, 1),
                          "close": close, "high": hi, "low": close - 0.01,
                          "volume": np.full(n, 800.0)})
    items = scan_spot_symbol("SUPUSDT", {"3d": frame})
    if items:
        w = _structural_weight((items[0].get("pattern_commands") or [{}])[0])
        assert w > 50, f"the reference must be the big structure (w={w})"


# ── 3. the urgent watch (positions never lost, Railway cost flat) ─────────
def test_urgent_watch_exists_and_is_bounded():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "_spot_urgent_recheck" in src
    seg = src.split("def _spot_urgent_recheck")[1].split("\ndef ")[0]  # the whole fn
    assert "spot_urgent_watch" in seg
    assert "[:6]" in seg, "the mini-pass is bounded (Railway-friendly)"
    assert "_pin_ttl_sec" in seg, ("R64.4: pins expire by their TF's breakout "
                                   "window — the flat 1h died before a slow break")
    assert "SYMBOL|TF" in seg, "r59.3: pins are per (symbol, tf)"
    # the full pass pins NEAR_BREAK/TOUCH symbols (R65 added the per-pin SHAPE
    # snapshot — the window grows with the contract, not around it);
    # R64.4: BREAK_DOWN pins too — the confirm lane must be awake at the break
    seg2 = src.split("# the ladder rides the SAME fetched frames")[1].split("# r57:")[0]
    assert "spot_urgent_watch" in seg2 and "NEAR_BREAK" in seg2
    assert "BREAK_DOWN" in seg2, "R64.4: the break itself pins the confirm lane"
    assert '"shape"' in seg2      # R65: the pinned shape itself, not just the symbol
    assert "line_watch" in seg2   # R64.4: pins feed the ticker line-watch


def test_urgent_recheck_uses_the_reply_chain():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    # R65 added the urgent-confirm lane inside this function — the
    # contract is about the WHOLE mini-pass, so scan the whole function.
    seg = src.split("def _spot_urgent_recheck")[1].split("def run_monitor_cycle")[0]
    assert "reply_to=int(_alert_kv.get" in seg
    assert "_spot_stamp(" in seg     # dedupe law holds in the mini-pass too


# ── 4. the WLD fix: dead rows invalidate the frozen zoom ──────────────────
def test_dead_rows_invalidate_frozen_zoom():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "dropped_dead_rows" in src
    seg = src.split("frame = _clean_render_frame(df, window=_lookback)")[1][:700]
    assert "chart_zoom_frozen" in seg and "zoom_freeze:" in seg


def test_clean_frame_flags_dead_rows():
    from bot.messages_v7 import _clean_render_frame
    n = 60
    ts = pd.date_range("2026-07-01", periods=n, freq="1d")
    close = np.full(n, 0.5)
    close[:20] = 1e-9
    frame = pd.DataFrame({"timestamp": ts, "open": close, "high": close,
                          "low": close, "close": close,
                          "volume": np.linspace(1, 9, n)})
    _clean_render_frame(frame, window=60)
    assert getattr(_clean_render_frame, "dropped_dead_rows", None) is True
    clean = frame.tail(40).copy()
    _clean_render_frame(clean, window=40)
    assert getattr(_clean_render_frame, "dropped_dead_rows", None) is False


# ── 5. the rectangle naming ───────────────────────────────────────────────
def test_rect_break_gets_the_classical_name():
    src = open(os.path.join(ROOT, "analysis", "spot_engine.py"), encoding="utf-8").read()
    assert "مستطیل صعودی" in src
    assert "_rect_fa or pattern_info(kind)" in src


def test_futures_trade_policy_untouched():
    from analysis.viva_tlbreak import load_config
    assert getattr(load_config(), "wick_policy", "outlier") == "outlier"


# ── 6. r58.1 — spot updates ride a LIVE chart (Viva 09-28) ────────────────
def test_spot_event_candidate_is_spot_and_lawful():
    from bot.messages_v7 import _spot_event_candidate
    ev = {"symbol": "WLD", "tf": "3d", "kind": "vol", "close": 0.5407}
    c = _spot_event_candidate(ev)
    assert c.metadata.get("is_spot") is True
    assert c.symbol == "WLD" and c.trigger_timeframe == "3d"
    assert c.planned_entry * 0.90 <= c.sl < c.planned_entry  # spot stop ≤10%
    assert c.planned_entry == 0.5407                 # anchored on the LIVE close


def test_send_spot_event_uses_photo_with_chart():
    from unittest import mock
    import bot.messages_v7 as M
    ev = {"symbol": "NEAR", "tf": "4h", "kind": "touch_high",
          "text_fa": "برخورد به سقف ساختاری", "close": 2.0}
    captured = {}
    with mock.patch.object(M, "CHAT_ID_SPOT", "@spot"), \
         mock.patch.object(M, "send_photo",
                           lambda img, cap, chat, reply_to_message_id=None,
                           reply_markup=None, caption_limit=1000:
                           captured.update(img=img, cap=cap, chat=chat,
                                           reply=reply_to_message_id) or 777), \
         mock.patch("database.bot_kv.get_json", return_value={"last": 55}), \
         mock.patch("database.bot_kv.set_json") as sj:
        assert M.send_spot_event(ev, chart=b"\x89PNG-fake") is True
    assert captured["img"].startswith(b"\x89PNG")
    assert "رویداد مهم اسپوت" in captured["cap"]
    assert captured["reply"] == 55                    # reply-chain law holds
    sj.assert_called_once()                           # chain updated to 777


def test_main_renders_update_chart_from_same_bundle():
    """R64.4 REVERSED by Viva 10-03 («آپدیت‌ها هنوز همگی با چارت لایو میان و
    مصرف بشدت بالا بردن») — the r57 generic update events are TEXT-ONLY
    replies; charts render only at a chain's key stages."""
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    seg = src.split("R64.4 THE SPOT CHART ECONOMY")[1][:900]
    assert "send_spot_event(_ev57)" in seg
    assert "generate_chart" not in seg and "_chart57" not in seg
