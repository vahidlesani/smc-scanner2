# ── Round 21 (Viva 09-23/24 شب) — حکم ماهیت الگو + هویت اسنپ‌شات.
# «رایزینگ وج ماهیت نزولی داره، با شکست کف و کلوز زیرش تایید میشه» — سیگنال
# صعودیِ داخلیِ تهِ رایزینگ‌وج (و نزولیِ سرِ فالینگ‌وج) کاملاً ممنوع.
# «اسنپ‌شات برای همون شناسه یکتا باید بمونه» — خطِ کش‌آمدهٔ زنجیرهٔ زنده.
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.pattern_engine import _EDGE_RULES  # noqa: E402
from database.candidate_store import absorb_update_into_chain  # noqa: E402
from analysis.models import SignalCandidate  # noqa: E402


def test_wedge_rules_trade_nature_only():
    # rising wedge: ONLY the floor-break SHORT rule exists — no LONG anywhere
    assert _EDGE_RULES["WEDGE_RISING"] == {"lower": "SHORT"}
    assert "upper" not in _EDGE_RULES["WEDGE_RISING"]
    # falling wedge: ONLY the ceiling-break LONG rule exists — no SHORT
    assert _EDGE_RULES["WEDGE_FALLING"] == {"upper": "LONG"}
    assert "lower" not in _EDGE_RULES["WEDGE_FALLING"]
    # channels keep BOTH break sides + are the only fade home (is_parallel)
    assert _EDGE_RULES["CHANNEL_FLAT"] == {"upper": "LONG", "lower": "SHORT"}


def _mk_candidate(sid: str, direction: str = "LONG", status: str = "APPROACHING",
                  metadata: dict | None = None) -> SignalCandidate:
    md = dict(metadata or {})
    return SignalCandidate(
        signal_id=sid, symbol="ADAUSDT", style="SWING", setup_code="TECHCLASSIC",
        setup_name="تست", strategy_fa="تست", direction=direction, score=8,
        status=status, entry_zone_bottom=99.0, entry_zone_top=101.0,
        planned_entry=100.0, sl=95.0, tp1=108.0, tp2=115.0,
        rr_tp1=1.6, rr_tp2=3.0, bias="BULLISH", trigger_timeframe="1h",
        metadata=md, mandatory_gates={"zone": True},
    )


def test_absorb_never_redraws_a_published_trendline():
    """«اسنپ‌شات برای همون شناسه یکتا باید بمونه» — the live chain's drawn
    structure keeps its alert-time anchors even after a fresh re-fit scan."""
    holder = _mk_candidate("r21-snap", metadata={
        "tl_a_ts": "2026-09-01 00:00", "tl_a_price": 80.0,
        "tl_b_ts": "2026-09-10 00:00", "tl_b_price": 88.0,
        "tl_line": 92.0, "viva_upper_points": [{"index": 3, "price": 80.0}],
        "viva_major_break_line": 90.92, "atr": 1.0,
    })
    holder.approaching_sent = True            # the chain is PUBLIC
    fresh = _mk_candidate("r21-snap", metadata={
        "tl_a_ts": "2026-09-05 00:00", "tl_a_price": 83.0,     # re-fit moved it
        "tl_b_ts": "2026-09-20 00:00", "tl_b_price": 91.0,     # «خط کش اومده باز»
        "tl_line": 95.0, "viva_upper_points": [{"index": 9, "price": 99.0}],
        "viva_major_break_line": 95.5, "atr": 1.2,
        "score_ctx": "fresh market context is still welcome",
    })
    absorb_update_into_chain(holder, fresh)
    md = holder.metadata
    assert md["tl_a_ts"] == "2026-09-01 00:00" and float(md["tl_a_price"]) == 80.0
    assert md["tl_b_ts"] == "2026-09-10 00:00" and float(md["tl_b_price"]) == 88.0
    assert float(md["tl_line"]) == 92.0
    assert md["viva_upper_points"] == [{"index": 3, "price": 80.0}]
    assert float(md["viva_major_break_line"]) == 90.92   # the MAJOR-TL law level
    assert md["score_ctx"] == "fresh market context is still welcome"  # context refreshes


def test_absorb_before_publication_still_refreshes_geometry():
    """No alert sent yet → there is no snapshot identity; the freshest fit wins."""
    holder = _mk_candidate("r21-fresh", status="DETECTED", metadata={
        "tl_a_ts": "2026-09-01 00:00", "tl_a_price": 80.0, "atr": 1.0,
    })
    holder.approaching_sent = False
    fresh = _mk_candidate("r21-fresh", status="DETECTED", metadata={
        "tl_a_ts": "2026-09-05 00:00", "tl_a_price": 84.0, "atr": 1.0,
    })
    absorb_update_into_chain(holder, fresh)
    assert holder.metadata["tl_a_ts"] == "2026-09-05 00:00"
    assert float(holder.metadata["tl_a_price"]) == 84.0


@pytest.mark.parametrize("pattern,direction,ok", [
    ("WEDGE_RISING", "LONG", False),     # ADA bug: long at the wedge bottom
    ("WEDGE_RISING", "SHORT", True),     # the wedge's own confirmation
    ("WEDGE_FALLING", "SHORT", False),   # short at the top of a falling wedge
    ("WEDGE_FALLING", "LONG", True),
    ("CHANNEL_FLAT", "LONG", True),      # کانال: کف→سقف مجاز
    ("CHANNEL_FLAT", "SHORT", True),
])
def test_wedge_nature_law_helper(pattern, direction, ok):
    from analysis.pattern_engine import scan_edges  # import sanity only
    rules = _EDGE_RULES.get(pattern) or {}
    has_rule = rules.get(
        "upper" if direction == "LONG" else "lower") == direction
    assert has_rule is ok
