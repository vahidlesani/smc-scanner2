"""R99q26 — 2026-10-19 pattern-name and zone-gate corrections (Viva's audit).

Three production complaints, each fixed here with an executable guard:

1. «پرچم کانال می‌کشه می‌گه فلگ» — an ordinary ascending channel that merely
   FOLLOWED a rise was published as a bull flag, because the old gate accepted
   any <=27-bar window whose drifts were under +2%, with no direction test and
   no displacement test. A flag's pause must lean BACK against its pole.

2. «کانال صعودی آرام بعد از قطب» — same root cause; must stay a non-flag.

3. «نواحی نباید ورود ستاپ‌های دیگر را وتو کند» (law §6.9) — the zone-mid
   requirement used to apply to every setup in evaluate_confirmation; it is a
   PIN-family privilege now.
"""
from __future__ import annotations

import pandas as pd

from analysis.pattern_law import classify_pair, pair_metrics


class _L:
    """Minimal line double usable by pair_metrics (price_at / points)."""

    def __init__(self, slope, intercept, first_index=0, last_index=99):
        self.slope = slope
        self.intercept = intercept
        self.first_index = first_index
        self.points = [{"index": first_index}, {"index": last_index}]
        self.touch_count = 2

    def price_at(self, x):
        return self.slope * float(x) + self.intercept


def _frame(opens_for_close, bar_frac=0.004):
    close = list(opens_for_close)
    return pd.DataFrame({
        "open": close,
        "high": [c * (1 + bar_frac) for c in close],
        "low": [c * (1 - bar_frac) for c in close],
        "close": close,
        "volume": [1.0] * len(close),
    })


def _ramp(n, start, per_bar, tail_per_bar=0.0, tail_at=None):
    out, v = [], float(start)
    for i in range(n):
        v *= (1 + (per_bar if (tail_at is None or i < tail_at) else tail_per_bar))
        out.append(v)
    return out


# ── ① a channel that RISES with the trend is never a flag ──────────────────
def test_rising_channel_after_a_pole_is_not_a_flag():
    """The exact production misread: a 26-bar ascending channel right after a
    ~5% rise used to be renamed FLAG_BULL. Brooks: a pause that keeps rising
    WITH the impulse is a channel. It must not reach the flag branch."""
    n = 60
    df = _frame(_ramp(n, 9.0, 0.0016, 0.00045, tail_at=34))
    up = _L(0.0011, 10.0, 34, 59)
    low = _L(0.0011, 9.70, 34, 59)
    m = pair_metrics(up, low, n, df=df)
    meta: dict = {}
    slug = classify_pair(m, meta)
    assert "FLAG" not in slug and "PENNANT" not in slug, (slug, meta.get("why"))
    assert str(slug).startswith(("CHANNEL", "RECTANGLE", "TRIANGLE")), slug


# ── ② a genuine bull flag still classifies ──────────────────────────────────
def test_true_bull_flag_still_classifies():
    """Strong pole up, then a brief TIGHT pause that leans back down."""
    n = 60
    rows = []
    v = 9.0
    for i in range(n):
        v *= 1.006 if i < 40 else 0.9993
        rows.append(v)
    df = _frame(rows, bar_frac=0.002)
    up = _L(-0.0012, 11.55, 40, 59)
    low = _L(-0.0012, 11.35, 40, 59)
    m = pair_metrics(up, low, n, df=df)
    meta: dict = {}
    assert classify_pair(m, meta) == "FLAG_BULL", meta.get("why")
    assert "leaning back" in " ".join(meta.get("why") or [])


# ── ③ a pole that is too small is never a flag ─────────────────────────────
def test_a_small_pole_is_never_a_flag():
    """`pole_min = max(3%, 1.2 × height)` — a move smaller than the pattern's
    own height cannot be the impulse a flag pauses on."""
    n = 60
    # pole of ~0.8% only, then a tight pause
    df = _frame(_ramp(n, 9.0, 0.00033, 0.0, tail_at=40))
    up = _L(-0.0008, 9.10, 40, 59)
    low = _L(-0.0008, 8.92, 40, 59)
    m = pair_metrics(up, low, n, df=df)
    assert abs(float(m.get("pole_rel") or 0.0)) < 0.03, m.get("pole_rel")
    meta: dict = {}
    slug = classify_pair(m, meta)
    assert "FLAG" not in slug and "PENNANT" not in slug, (slug, meta.get("why"))


# ── ④ the wedge/channel flip-killer must stay intact ───────────────────────
def test_parallel_channel_never_becomes_a_wedge():
    """Guard against re-loosening the 10-19 experiment: a truly parallel pair
    with a tiny fitted-slope difference must remain a channel."""
    n = 150
    up = _L(-0.00035, 0.26, 0, n - 1)
    low = _L(-0.00035, 0.235, 0, n - 1)
    df = _frame(_ramp(n, 0.235, 0.0))
    m = pair_metrics(up, low, n, df=df)
    meta: dict = {}
    slug = classify_pair(m, meta)
    assert "WEDGE" not in slug, (slug, meta.get("why"))


# ── ⑤ zone-mid is a PIN privilege, never a cross-setup veto ────────────────
def test_zone_mid_gate_is_scoped_to_the_pin_family():
    """Law §6.9: «هر گیت دیگری باید حذف بشه». The zone-mid requirement must
    never hold TECHCLASSIC/TLBREAK/ALBROX/SPOT hostage to where the
    supply/demand box sits — it belongs to the pin family only."""
    import inspect
    import analysis.quality_engine as qe
    src = inspect.getsource(qe)
    assert "_pin_mid_owner" in src, "the zone-mid gate lost its PIN scoping"
    assert '"PINVAL", "PINWALLQ", "PINWALL"' in src
    # the raw setting alone must not decide anymore
    assert "require_mid = SETTINGS.confirm_require_zone_mid" not in src
