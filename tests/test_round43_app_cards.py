"""r43 — the app-card numbers round (Viva 09-26, 22:06 screenshot).

His screenshot showed two number defects on the Signals cards:
  1. `TP3 0.7859250000000001` — a raw binary float riding straight onto the
     pill (ladder_targets left the API unformatted).
  2. `TP2 == TP3` on every 3-pill card — the TP2 pill read the LEGACY tp2
     column (the "final target" convention) while TP3 read the saved ladder's
     last pill, i.e. the same number twice; the ladder's real middle pill was
     never displayed.
Laws in play: app cards render EXACTLY the publish-time saved ladder (r41),
and every number on a card must be clean enough to read aloud.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(REPO, "webapp_viva.py"), encoding="utf-8").read()


# ── 1. the float garbage from the screenshot dies ──────────────────────────

def test_fmt_price_trims_binary_float_artifact():
    from webapp_viva import _fmt_price
    assert _fmt_price(0.7859250000000001) == "0.785925"
    assert _fmt_price(0.79275) == "0.79275"


def test_feed_sends_formatted_ladder_targets():
    src = _src()
    assert 'ladder_targets=[_fmt_price(_t43) for _t43 in _lv41["targets"]],' in src


def test_ladder_view_formats_end_to_end():
    from webapp_viva import _ladder_view, _fmt_price
    import json
    lad = json.dumps({"targets": [{"price": 0.755985}, {"price": 0.770955},
                                  {"price": 0.7859250000000001}],
                      "hit_index": 1})
    lv = _ladder_view(lad)
    out = [_fmt_price(t) for t in lv["targets"]]
    assert out == ["0.755985", "0.770955", "0.785925"], out


# ── 2. the middle pill finally shows the real TP2 ──────────────────────────

def test_sigcard_pills_read_saved_ladder_with_column_fallback():
    js = _src()
    assert "const p1=L43[0]||x.tp1,p2=L43[1]||x.tp2,t3=L43[2]||null;" in js
    assert '${fnum(p1)}' in js and '${fnum(p2)}' in js
    # the old "pill2 = legacy column" expression is gone
    old_pill2 = '<span>TP2${x.tp2_hit?\' ✓\':\'\'}</span><b class="grn">${fnum(x.tp2)}</b>'
    assert old_pill2 not in js


def test_detail_ladder_prefers_saved_three_pill_ladder():
    src = _src()
    part = src.split("lh1, lh2 = _ladder_hits(row.get(\"target_state_json\"))")[1]
    assert "if len(_lv43[\"targets\"]) >= 3" in part      # saved ladder wins
    assert "hit=(_lv43[\"hit_index\"] > _i)" in part       # per-pill hit flags


# ── 3. touch comparator survives thousands separators ──────────────────────

def test_touch_comparator_strips_commas_before_parsefloat():
    js = _src()
    assert "function pf(v){return parseFloat(String(v).replace(/,/g,''))}" in js
    assert "px>=pf(lv)" in js and "px<=pf(lv)" in js
    assert "px<=pf(x.sl)" in js and "px>=pf(x.sl)" in js
