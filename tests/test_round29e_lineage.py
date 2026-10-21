"""r29e regression: stable alert lineage (cherry-picked R31.7b).

Root cause of «از دیروز 2H/4H هیچ تأییدی نیامد»: every rescan minted a NEW
signal_id for the SAME broken edge — the sloped line drifts ~0.2 ATR per
scan, the old 0.08-ATR lineage test failed, the alert was re-created/
superseded, and the confirmation clock restarted → TECHCLASSIC/TLBREAK
alerts died «superseded» before any confirm-TF close. The lineage is now
keyed by the defining pivots' TIMESTAMPS (which never move) and a keyed
match only replaces on a full-ATR zone relocation.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_v7 import make_candidate


def _pts(*hours):
    return [{"timestamp": f"2026-09-2{d}T{h:02d}:00", "price": 100.0 + i}
            for i, (d, h) in enumerate(hours)]


def test_lineage_key_is_pivot_ts_stable_and_drift_proof():
    from analysis.pattern_engine import alert_lineage_key
    a = alert_lineage_key("TECHCLASSIC", "BTCUSDT", "2h", "4h", "upper", "LONG", _pts((3, 8), (3, 20)))
    b = alert_lineage_key("TECHCLASSIC", "BTCUSDT", "2h", "4h", "upper", "LONG", _pts((3, 8), (3, 20)))
    assert a and a == b, "same pivots → same scenario id across rescans"
    # prices drift with refit — timestamps do NOT: key must ignore prices
    c_pts = [{"timestamp": "2026-09-23T08:00", "price": 105.7},
             {"timestamp": "2026-09-23T20:00", "price": 104.9}]
    c = alert_lineage_key("TECHCLASSIC", "BTCUSDT", "2h", "4h", "upper", "LONG", c_pts)
    assert c == a, "price drift must not change the identity"
    assert alert_lineage_key("TECHCLASSIC", "BTCUSDT", "2h", "4h", "upper", "LONG", [_pts((3, 8))]) == ""
    assert alert_lineage_key("TECHCLASSIC", "BTCUSDT", "2h", "4h", "upper", "SHORT", _pts((3, 8), (3, 20))) != a


def test_keyed_lineage_blocks_small_drift_supersede():
    """Same lineage key + 0.2 ATR zone drift → NOT a new alert (old rule
    superseded at 0.08-0.2 ATR and reset the confirm clock)."""
    from database.candidate_store import is_material_update as should_supersede
    prev = make_candidate()
    prev.metadata["alert_lineage_key"] = "TECHCLASSIC|BTCUSDT|2h|4h|upper|LONG|BRK|t1|t2"
    prev.metadata["atr"] = 1.0
    prev.entry_zone_bottom, prev.entry_zone_top = 99.9, 100.1
    new = make_candidate()
    new.metadata["alert_lineage_key"] = prev.metadata["alert_lineage_key"]
    new.metadata["atr"] = 1.0
    new.entry_zone_bottom, new.entry_zone_top = 100.1, 100.3                      # 0.2 ATR drift, < 1.0 ATR gate
    assert should_supersede(prev, new) is False
    new.entry_zone_bottom, new.entry_zone_top = 101.4, 101.6                      # full-ATR relocation → replace
    assert should_supersede(prev, new) is True
