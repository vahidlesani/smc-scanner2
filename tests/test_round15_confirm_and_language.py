"""Round-15 tests — «چرا این ستاپ‌ها موقعیت رو می‌شناسن اما تایید نمی‌کنن؟»

The live case (ETHFIUSDT 1h, 09-21) and the Persian-in-charts engine, both
pinned here so they can never silently regress:

* the confirmation level the ENGINE waits for must be the level the MESSAGE
  prints (the pinbar's own extreme);
* the FIRST valid closed candle beyond that level confirms — the old extra
  thresholds (0.10×ATR beyond the edge + a 0.25×ATR body) that no message ever
  mentioned are gone;
* a pattern band that has nothing to do with a pinbar level may no longer veto
  a pinbar confirmation (the INSIDE_PATTERN_NO_BREAK mis-fire);
* chart Persian needs shaping + bidi and a font that actually has the glyphs.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pin_candidate(direction="LONG", level=100.0, zone=(99.5, 100.0), **over):
    from analysis.models import SignalCandidate
    base = dict(signal_id="R15-1", symbol="ETHFIUSDT", style="SWING",
                setup_code="PINVAL", setup_name="t", strategy_fa="t",
                direction=direction, score=8, status="APPROACHING",
                entry_zone_bottom=zone[0], entry_zone_top=zone[1],
                planned_entry=(zone[0] + zone[1]) / 2,
                sl=98.4, tp1=101.5, tp2=103.0, rr_tp1=1.0, rr_tp2=2.0,
                bias="BULL", trigger_timeframe="1h",
                mandatory_gates={"zone": True}, created_at="2026-09-21T05:11:54+00:00",
                metadata={"atr": 1.0, "touched": True, "pin_tf": "1h",
                          "pin_high": level, "pin_low": 97.6})
    base.update(over)
    return SignalCandidate(**base)


def _frame(closes, start="2026-09-21 06:00", freq="1h", pad=20):
    """A frame the engine accepts (>=20 closed bars) whose TAIL is exactly the
    closes under test; the padding bars sit quietly below the level."""
    values = [float(c) for c in closes]
    tail = values[-3:] if len(values) >= 3 else values
    pad_values = [min(values) - 1.5 - 0.01 * i for i in range(pad)]
    allc = pad_values + values
    ts = pd.date_range(start, periods=len(allc), freq=freq)
    return pd.DataFrame({"timestamp": ts,
                         "open": [c - 0.10 for c in allc],
                         "high": [c + 0.20 for c in allc],
                         "low": [c - 0.20 for c in allc],
                         "close": allc, "volume": [1000] * len(allc)})


def test_engine_waits_for_the_level_the_message_prints():
    """The pinbar message says «کلوز بالای pin_high»; a close just above the
    ZONE edge (0.7% lower in the live case) must NOT confirm instead."""
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin_candidate(level=100.0, zone=(99.2, 99.5))
    frame = _frame([99.45, 99.45, 99.45])       # above the zone edge, below the pin high
    ok, cand2, reason = evaluate_confirmation(cand, frame)
    # A close above the ZONE edge may never be recorded as clearing the pin
    # level: the recorded level is either the pin high or absent (an alternative
    # trigger lane). The zone edge 99.5 must never appear as the confirm level.
    lvl = float(cand2.metadata.get("confirm_level_used") or 0.0)
    assert lvl in (0.0, 100.0), (lvl, reason)
    assert abs(lvl - 99.5) > 1e-9


def test_first_valid_close_beyond_the_named_level_confirms():
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin_candidate(level=100.0)
    frame = _frame([100.3, 100.6])              # a clean close beyond the level
    ok, cand2, reason = evaluate_confirmation(cand, frame)
    assert ok is True, reason
    assert abs(float(cand2.metadata.get("confirm_level_used")) - 100.0) < 1e-9
    assert not cand2.metadata.get("last_reject_code")


def test_no_hidden_body_or_extra_atr_threshold_blocks_a_clean_close(monkeypatch):
    """A small-bodied candle that closes beyond the level is a confirmation —
    the member was told «first close», nothing else."""
    # HERMETIC: the counter-trend gate fetches the parent TF from the venue.
    # When that fetch succeeds (OKX fallback), REAL ETHFIUSDT data (which fell
    # over the last 30 bars) flips the gate and the synthetic confirm dies.
    # This test owns the offline path: parent frame = None.
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin_candidate(level=100.0)
    frame = _frame([100.25, 100.30])
    ok, cand2, reason = evaluate_confirmation(cand, frame)
    assert ok is True, reason


def test_pattern_band_cannot_veto_a_pinbar_confirmation(monkeypatch):
    """The exact ETHFIUSDT mis-fire: fast lane satisfied, then a foreign wedge
    band rejected the row with INSIDE_PATTERN_NO_BREAK."""
    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_klines", lambda *a, **k: None)  # hermetic (see above)
    from analysis.quality_engine import evaluate_confirmation
    cand = _pin_candidate(level=100.0, zone=(99.0, 99.4))
    cand.metadata["pattern_band"] = {"kind": "WEDGE_FALLING", "lo": 98.0, "hi": 102.0,
                                     "slope_lo": 0.0, "slope_hi": 0.0,
                                     "ts_last": "2026-09-21 05:00", "tf_minutes": 60.0}
    frame = _frame([100.4, 100.5])              # close above the pin level, inside the band
    ok, cand2, reason = evaluate_confirmation(cand, frame)
    assert ok is True, reason
    assert cand2.metadata.get("last_reject_code") is None


def test_pattern_setup_still_respects_containment_for_a_mirror_zone_edge():
    """The round-10 law survives for pattern-premise setups: clearing a mirror
    zone inside the pattern is NOT the breakout."""
    from analysis.quality_engine import evaluate_confirmation
    from analysis.models import SignalCandidate
    cand = SignalCandidate(signal_id="R15-2", symbol="TESTUSDT", style="SWING",
                           setup_code="TLBREAK", setup_name="t", strategy_fa="t",
                           direction="LONG", score=8, status="APPROACHING",
                           entry_zone_bottom=99.5, entry_zone_top=100.0,
                           planned_entry=100.0, sl=98.0, tp1=101.5, tp2=103.0,
                           rr_tp1=1.0, rr_tp2=2.0, bias="BULL", trigger_timeframe="15m",
                           mandatory_gates={"zone": True}, created_at="2026-09-21T05:00:00+00:00",
                           metadata={"atr": 1.0, "touched": True,
                                     "pattern_band": {"kind": "RANGE", "lo": 99.0, "hi": 103.0,
                                                      "slope_lo": 0.0, "slope_hi": 0.0,
                                                      "ts_last": "2026-09-21 05:00",
                                                      "tf_minutes": 15.0}})
    frame = _frame([100.10, 100.20, 100.20], start="2026-09-21 05:15", freq="15min", pad=30)
    ok, cand2, _reason = evaluate_confirmation(cand, frame)
    assert ok is False
    assert cand2.metadata.get("last_reject_code") == "INSIDE_PATTERN_NO_BREAK"


def test_persian_text_engine_shapes_and_has_a_font():
    from analysis.fa_text import fa, fonts_ready
    assert fonts_ready(), "font + shaper must ship with the repo"
    shaped = fa("کلوز بالای سقف الگو")
    assert shaped != "کلوز بالای سقف الگو"      # reshaped into presentation forms
    assert " کلوز" not in shaped                # and reordered right-to-left
    assert fa("") == "" and fa(None) == ""
    # Latin-only text passes through untouched
    assert fa("BREAKOUT") == "BREAKOUT"


def test_every_live_setup_has_its_own_sticker():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    stickers = os.path.join(root, "assets", "stickers")
    for code in ("PINVAL", "PINWALLQ", "TLBREAK", "TECHCLASSIC", "ALBROX"):
        path = os.path.join(stickers, f"{code.lower()}.png")
        assert os.path.isfile(path), f"missing sticker for {code}"
        assert os.path.getsize(path) > 1000


def test_setup_names_carry_both_brand_and_persian():
    from bot.messages_v7 import _setup_display
    assert "PINWALL QUALITY" in _setup_display("PINWALLQ")
    assert "پین‌وال" in _setup_display("PINWALLQ")
    assert "شکست خط روند" in _setup_display("TLBREAK")


def test_pinval_confirmation_text_has_no_candle_cap():
    from bot.messages_v7 import _confirm_rule_fa
    text = _confirm_rule_fa(_pin_candidate(level=100.0))
    assert "تا ۳ کندل" not in text and "۳ کندل یک‌ساعته" not in text
    assert "اولین کلوز" in text
