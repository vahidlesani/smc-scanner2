"""Zone Polarity Gate for PINVAL (Pinbar in Important Zone).

Viva's refinement (2026-09): a pinbar is a *location* clue, not just a candle
shape. The pin's direction is only tradable when it agrees with the polarity of
the nearest higher-timeframe supply/demand structure:

  * LONG is valid when price is AT a key DEMAND zone, OR when overhead supply has
    already been broken with a valid closed-candle breakout (the supply flips to
    demand / retest support). A long printed *under untouched, nearby supply* is
    rejected — that is exactly where corrections cap longs and turn them down.
  * SHORT is the mirror: valid at a key SUPPLY zone, or after a valid breakdown
    of demand (demand flips to supply). A short printed *above untouched nearby
    demand* is rejected.

A "valid breakout" (moderate definition, per Viva's tuning):
  the last closed CONTEXT-TF candle closes beyond the zone's DISTAL edge (not a
  wick) with a directional displacement body >= ``breakout_body_atr`` (default
  0.5 ATR). Mitigation only counts when price has reached the zone's proximal
  edge afterwards.

Everything is measured in the *trigger* ATR so thresholds are comparable across
context/trigger timeframes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from analysis.indicators import candle_displacement, pivots


@dataclass
class Zone:
    side: str            # "SUPPLY" (above price) or "DEMAND" (below price)
    level: float         # cluster mean
    top: float           # distal for supply / proximal for demand
    bottom: float        # proximal for supply / distal for demand
    touches: int
    last_index: int
    tf: str = ""
    origin: str = "PIVOT"   # PIVOT, FVG, FLIP
    broken: bool = False    # price has closed through the distal edge
    flipped: bool = False   # broken and confirmed by displacement candle
    dist_atr: float = 0.0   # distance from probe to the proximal edge (trigger ATR)

    @property
    def proximal(self) -> float:
        return self.bottom if self.side == "SUPPLY" else self.top

    @property
    def distal(self) -> float:
        return self.top if self.side == "SUPPLY" else self.bottom


@dataclass
class PolarityVerdict:
    direction: str                       # "LONG" / "SHORT"
    allowed: bool
    reason: str                          # machine code: AT_DEMAND, AT_SUPPLY,
                                         # SUPPLY_FLIP, DEMAND_FLIP,
                                         # UNDER_SUPPLY (reject), ABOVE_DEMAND (reject),
                                         # NO_ZONE (reject when gate requires zone)
    reason_fa: str = ""
    zone_kind: str = "NONE"              # DEMAND / SUPPLY / FLIP / FVG
    nearest_supply: Optional[Zone] = None
    nearest_demand: Optional[Zone] = None
    active_zone: Optional[Zone] = None   # the zone that authorises the trade
    details: Dict = field(default_factory=dict)


def _cluster_zones(
    points: List[Dict],
    side: str,
    price: float,
    band_atr: float,
    cluster_atol_atr: float = 0.25,
    tf: str = "",
    keep_atr: float = 6.0,
    min_touches: int = 2,
) -> List[Zone]:
    """Cluster same-side pivots into *significant* shelf zones near ``price``.

    A real wall is a cluster of >= ``min_touches`` pivots (or a single very
    recent extreme) at roughly the same level. Mid-range isolated pivots are
    noise and do not form a wall. Keeps the facing walls (supply above / demand
    below) and recently-broken walls a little behind price (for post-breakout
    flip retests). Stale shelves far from price are dropped.
    """
    band = band_atr
    levels = sorted({round(float(p["price"]), 8) for p in points})
    clusters: List[List[float]] = []
    for lv in levels:
        if clusters and abs(lv - float(np.mean(clusters[-1]))) <= cluster_atol_atr * band:
            clusters[-1].append(lv)
        else:
            clusters.append([lv])
    index_by_price: Dict[float, List[Dict]] = {}
    for p in points:
        index_by_price.setdefault(round(float(p["price"]), 8), []).append(p)
    last_idx = max((int(p["index"]) for p in points), default=-1)

    raw: List[Zone] = []
    for cl in clusters:
        members = [rec for lv in cl for rec in index_by_price.get(round(lv, 8), [])]
        touches = len(members)
        mean = float(np.mean(cl))
        member_last = max(int(p["index"]) for p in members)
        # Significance: multi-touch shelf, OR a single pivot that is the most
        # recent structural extreme (a fresh swing high/low still acts as wall).
        significant = touches >= min_touches or member_last == last_idx
        if not significant:
            continue
        top = mean + 0.5 * band
        bottom = mean - 0.5 * band
        z = Zone(side, mean, top=top, bottom=bottom, touches=touches,
                 last_index=member_last, tf=tf)
        if side == "SUPPLY":
            facing = bottom >= price - band
            broken_behind = top < price and (price - top) <= keep_atr * band
        else:
            facing = top <= price + band
            broken_behind = bottom > price and (bottom - price) <= keep_atr * band
        if not (facing or broken_behind):
            continue
        raw.append(z)

    # Merge neighbouring shelves whose CENTRES are within 0.8 ATR (same wall).
    raw.sort(key=lambda z: z.level)
    merged: List[Zone] = []
    for z in raw:
        if merged and abs(z.level - merged[-1].level) <= 0.8 * band:
            base = merged[-1]
            total = base.touches + z.touches
            base.level = (base.level * base.touches + z.level * z.touches) / total
            base.top = max(base.top, z.top)
            base.bottom = min(base.bottom, z.bottom)
            base.touches = total
            base.last_index = max(base.last_index, z.last_index)
        else:
            merged.append(z)
    return merged


def _fvg_zones(df: pd.DataFrame, side: str, price: float, band_atr: float,
               lookback: int = 60) -> List[Zone]:
    """Un-mitigated fair-value gaps as supply/demand shelves on one timeframe."""
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    n = len(df)
    out: List[Zone] = []
    for i in range(n - 3, max(2, n - lookback) - 1, -1):
        if side == "DEMAND" and lows[i] > highs[i - 2]:
            lo, hi = float(highs[i - 2]), float(lows[i])
            if hi - lo < 0.15 * band_atr:
                continue
            if np.any(closes[i + 1:] < lo):   # mitigated
                continue
            if hi < price - band_atr or lo > price + band_atr * 3:
                pass
            z = Zone("DEMAND", (lo + hi) / 2, top=hi, bottom=lo, touches=0,
                     last_index=i, tf="", origin="FVG")
            out.append(z)
        elif side == "SUPPLY" and highs[i] < lows[i - 2]:
            lo, hi = float(highs[i]), float(lows[i - 2])
            if hi - lo < 0.15 * band_atr:
                continue
            if np.any(closes[i + 1:] > hi):   # mitigated
                continue
            z = Zone("SUPPLY", (lo + hi) / 2, top=hi, bottom=lo, touches=0,
                     last_index=i, tf="", origin="FVG")
            out.append(z)
    return out


def _mark_breakouts(df: pd.DataFrame, zones: List[Zone], direction_for_long: str,
                    body_atr_min: float) -> None:
    """Tag each zone as broken/flipped based on the most recent CLOSED context candle.

    A zone's polarity flips once price closes BEYOND its distal edge (beyond the
    far side, so a mere wick through the near edge does not count) with a
    directional displacement body >= ``body_atr_min`` ATR. Broken walls stay in
    the list so the caller can authorise the post-breakout retest even though
    they are no longer on the "facing" side of price.

    direction_for_long: the pin candidate direction. For LONG we care whether
    SUPPLY overhead was broken upward (flips to demand). For SHORT whether
    DEMAND below was broken downward (flips to supply).
    """
    if df is None or len(df) < 6:
        return
    closes = df["close"]
    opens = df["open"]
    last_i = len(df) - 1
    last_close = float(closes.iloc[last_i])
    # Look back over the last few closed context candles for the breakout. The
    # pin/retest candle itself may be a pullback (opposite colour), so the
    # decisive breakout can be a candle or two before it. We measure each
    # candle's body against the ATR *prior* to that candle so a large breakout
    # cannot inflate its own denominator.
    lookback = min(4, last_i)
    for z in zones:
        if direction_for_long == "LONG" and z.side == "SUPPLY":
            z.broken = last_close > z.distal
            z.flipped = False
            if z.broken:
                for j in range(last_i, last_i - lookback - 1, -1):
                    cc = float(closes.iloc[j]); oo = float(opens.iloc[j])
                    if cc > z.distal and cc > oo:
                        prev_atr = float(candle_displacement(df, max(0, j - 1), 0.0).get("atr", 0) or 0)
                        if prev_atr <= 0:
                            prev_atr = float(candle_displacement(df, j, 0.0).get("atr", 0) or 1.0)
                        if abs(cc - oo) / prev_atr >= body_atr_min:
                            z.flipped = True
                            break
        elif direction_for_long == "SHORT" and z.side == "DEMAND":
            z.broken = last_close < z.distal
            z.flipped = False
            if z.broken:
                for j in range(last_i, last_i - lookback - 1, -1):
                    cc = float(closes.iloc[j]); oo = float(opens.iloc[j])
                    if cc < z.distal and cc < oo:
                        prev_atr = float(candle_displacement(df, max(0, j - 1), 0.0).get("atr", 0) or 0)
                        if prev_atr <= 0:
                            prev_atr = float(candle_displacement(df, j, 0.0).get("atr", 0) or 1.0)
                        if abs(cc - oo) / prev_atr >= body_atr_min:
                            z.flipped = True
                            break


def evaluate_polarity(
    context_df: pd.DataFrame,
    trigger_df: Optional[pd.DataFrame],
    direction: str,
    probe: float,
    atr_trigger: float,
    *,
    near_atr: float = 1.2,
    block_atr: float = 1.8,
    breakout_body_atr: float = 0.5,
    include_fvg: bool = True,
) -> PolarityVerdict:
    """Return a :class:`PolarityVerdict` for a pinbar of ``direction`` whose
    rejection extreme is ``probe`` (low for a bullish pin, high for a bearish pin).

    Distances are expressed in trigger-TF ATR units.
    """
    direction = direction.upper()
    atr_c = atr_trigger or 0.0

    supply: List[Zone] = []
    demand: List[Zone] = []

    if context_df is not None and len(context_df) >= 60 and atr_c > 0:
        ph, pl = pivots(context_df, 3, 3)
        supply = _cluster_zones(ph, "SUPPLY", probe, atr_c, cluster_atol_atr=0.40,
                                tf=getattr(context_df, "_tf", ""))
        demand = _cluster_zones(pl, "DEMAND", probe, atr_c, cluster_atol_atr=0.40,
                                tf=getattr(context_df, "_tf", ""))
        if include_fvg and trigger_df is not None:
            supply += _fvg_zones(trigger_df, "SUPPLY", probe, atr_c)
            demand += _fvg_zones(trigger_df, "DEMAND", probe, atr_c)
        _mark_breakouts(context_df, supply, "LONG", breakout_body_atr)
        _mark_breakouts(context_df, demand, "SHORT", breakout_body_atr)

        def _facing_dist(z: Zone, side: str) -> float:
            # distance from probe to the zone's proximal (near) edge; only
            # meaningful when the wall is still on the facing side.
            if side == "SUPPLY":
                if z.flipped or z.top <= probe:
                    return 1e9  # broken/behind supply is not an overhead wall
                return (z.bottom - probe) / atr_c if z.bottom >= probe else (probe - z.bottom) / atr_c
            if z.flipped or z.bottom >= probe:
                return 1e9  # broken/above demand is not a floor
            return (probe - z.top) / atr_c if z.top <= probe else (z.top - probe) / atr_c

        def _flip_dist(z: Zone, side: str) -> float:
            # post-breakout retest distance: zone now sits behind price but close.
            if side == "SUPPLY":  # broken supply now below (support for LONG)
                if not z.flipped or not (z.top < probe):
                    return 1e9
                return (probe - z.top) / atr_c
            # broken demand now above (resistance for SHORT)
            if not z.flipped or not (z.bottom > probe):
                return 1e9
            return (z.bottom - probe) / atr_c

        for z in supply:
            z.dist_atr = min(_facing_dist(z, "SUPPLY"), _flip_dist(z, "SUPPLY"))
        for z in demand:
            z.dist_atr = min(_facing_dist(z, "DEMAND"), _flip_dist(z, "DEMAND"))

    # Nearest *facing* wall (untouched) — the wall that blocks a continuation.
    # The pin's rejection extreme (probe) can be sitting just inside the wall
    # (a wick that tags it), so we allow the probe to be a little past the near
    # edge and still count the wall as the active facing level.
    facing_supply = [
        z for z in supply
        if not z.flipped
        and (z.bottom - probe) >= -atr_c * block_atr
        and (z.bottom - probe) <= atr_c * block_atr
    ]
    facing_demand = [
        z for z in demand
        if not z.flipped
        and (probe - z.top) >= -atr_c * block_atr
        and (probe - z.top) <= atr_c * block_atr
    ]
    # Facing supply = wall whose near edge is closest to the probe from below/at
    # (smallest gap above the probe; a probe a hair inside the wall is allowed).
    def _supply_gap(z: Zone) -> float:
        return z.bottom - probe
    def _demand_gap(z: Zone) -> float:
        return probe - z.top
    nearest_supply = min(facing_supply, key=_supply_gap, default=None)
    nearest_demand = min(facing_demand, key=_demand_gap, default=None)
    if nearest_supply is not None:
        nearest_supply.dist_atr = max(0.0, _supply_gap(nearest_supply)) / atr_c
    if nearest_demand is not None:
        nearest_demand.dist_atr = max(0.0, _demand_gap(nearest_demand)) / atr_c

    def _near(z: Optional[Zone], limit: float) -> bool:
        return z is not None and z.dist_atr <= limit

    def _supply_blocking_long() -> bool:
        # Untouched supply sitting overhead within block distance blocks a
        # continuation long regardless of a farther demand shelf below.
        return nearest_supply is not None and nearest_supply.dist_atr <= block_atr

    def _demand_blocking_short() -> bool:
        return nearest_demand is not None and nearest_demand.dist_atr <= block_atr

    if direction == "LONG":
        # Priority: a near post-breakout flipped supply (support) is the strongest
        # long location, then rejection AT demand — but only when the nearest
        # facing wall is not untouched supply (which would block continuation).
        flipped_supply = min(
            (z for z in supply if z.flipped and z.top < probe and (probe - z.top) / atr_c <= block_atr),
            key=lambda z: probe - z.top, default=None,
        )
        if flipped_supply is not None:
            flipped_supply.dist_atr = (probe - flipped_supply.top) / atr_c
            return PolarityVerdict(
                "LONG", True, "SUPPLY_FLIP",
                "عرضهٔ بالای سر با کلوز و دیسپلیسمنت معتبر شکسته شده و به فلیپ/حمایت تبدیل شده است؛ "
                "بنابراین پین صعودی پس از شکست معتبر مجاز است.",
                zone_kind="FLIP", nearest_supply=nearest_supply, nearest_demand=nearest_demand,
                active_zone=flipped_supply,
                details={"zone_dist_atr": round(flipped_supply.dist_atr, 2)},
            )
        at_demand = _near(nearest_demand, near_atr)
        if at_demand and not _supply_blocking_long():
            kind = "FVG" if nearest_demand.origin == "FVG" else "DEMAND"
            return PolarityVerdict(
                "LONG", True, "AT_DEMAND",
                f"پین صعودی در تقاضای کلیدی (فاصله {nearest_demand.dist_atr:.1f} ATR) رخ داده است؛ "
                "قطبیت ناحیه با جهت پین هم‌خوان است.",
                zone_kind=kind, nearest_supply=nearest_supply, nearest_demand=nearest_demand,
                active_zone=nearest_demand,
                details={"zone_dist_atr": round(nearest_demand.dist_atr, 2)},
            )
        # Untouched, nearby supply overhead and no valid breakout → reject.
        if _supply_blocking_long():
            return PolarityVerdict(
                "LONG", False, "UNDER_SUPPLY",
                f"پین صعودی دقیقاً زیر یک عرضهٔ کلیدیِ دست‌نخورده (فاصله {nearest_supply.dist_atr:.1f} ATR) "
                "شکل گرفته است؛ بدون شکست معتبرِ عرضه، سیگنال صعودی تأیید نمی‌شود و باید دنبال سناریوی نزولی بود.",
                zone_kind="SUPPLY", nearest_supply=nearest_supply, nearest_demand=nearest_demand,
                active_zone=nearest_supply,
                details={"zone_dist_atr": round(nearest_supply.dist_atr, 2)},
            )
        if at_demand:
            kind = "FVG" if nearest_demand.origin == "FVG" else "DEMAND"
            return PolarityVerdict(
                "LONG", True, "AT_DEMAND",
                f"پین صعودی در تقاضای کلیدی (فاصله {nearest_demand.dist_atr:.1f} ATR) رخ داده است و "
                "هیچ عرضهٔ نزدیکی بالای سر وجود ندارد.",
                zone_kind=kind, nearest_supply=nearest_supply, nearest_demand=nearest_demand,
                active_zone=nearest_demand,
                details={"zone_dist_atr": round(nearest_demand.dist_atr, 2)},
            )
        return PolarityVerdict(
            "LONG", False, "NO_ZONE",
            "پین صعودی در هیچ تقاضای کلیدی یا فلیپِ ناشی از شکست معتبر قرار ندارد.",
            zone_kind="NONE", nearest_supply=nearest_supply, nearest_demand=nearest_demand,
            details={},
        )

    # SHORT — mirror
    flipped_demand = min(
        (z for z in demand if z.flipped and z.bottom > probe and (z.bottom - probe) / atr_c <= block_atr),
        key=lambda z: z.bottom - probe, default=None,
    )
    if flipped_demand is not None:
        flipped_demand.dist_atr = (flipped_demand.bottom - probe) / atr_c
        return PolarityVerdict(
            "SHORT", True, "DEMAND_FLIP",
            "تقاضای زیر پا با کلوز و دیسپلیسمنت معتبر شکسته شده و به فلیپ/مقاومت تبدیل شده است؛ "
            "بنابراین پین نزولی پس از شکست معتبر مجاز است.",
            zone_kind="FLIP", nearest_supply=nearest_supply, nearest_demand=nearest_demand,
            active_zone=flipped_demand,
            details={"zone_dist_atr": round(flipped_demand.dist_atr, 2)},
        )
    at_supply = _near(nearest_supply, near_atr)
    if at_supply and not _demand_blocking_short():
        kind = "FVG" if nearest_supply.origin == "FVG" else "SUPPLY"
        return PolarityVerdict(
            "SHORT", True, "AT_SUPPLY",
            f"پین نزولی در عرضهٔ کلیدی (فاصله {nearest_supply.dist_atr:.1f} ATR) رخ داده است؛ "
            "قطبیت ناحیه با جهت پین هم‌خوان است.",
            zone_kind=kind, nearest_supply=nearest_supply, nearest_demand=nearest_demand,
            active_zone=nearest_supply,
            details={"zone_dist_atr": round(nearest_supply.dist_atr, 2)},
        )
    if _demand_blocking_short():
        return PolarityVerdict(
            "SHORT", False, "ABOVE_DEMAND",
            f"پین نزولی دقیقاً بالای یک تقاضای کلیدیِ دست‌نخورده (فاصله {nearest_demand.dist_atr:.1f} ATR) "
            "شکل گرفته است؛ بدون شکست معتبرِ تقاضا، سیگنال نزولی تأیید نمی‌شود و باید دنبال سناریوی صعودی بود.",
            zone_kind="DEMAND", nearest_supply=nearest_supply, nearest_demand=nearest_demand,
            active_zone=nearest_demand,
            details={"zone_dist_atr": round(nearest_demand.dist_atr, 2)},
        )
    if at_supply:
        kind = "FVG" if nearest_supply.origin == "FVG" else "SUPPLY"
        return PolarityVerdict(
            "SHORT", True, "AT_SUPPLY",
            f"پین نزولی در عرضهٔ کلیدی (فاصله {nearest_supply.dist_atr:.1f} ATR) رخ داده است و "
            "هیچ تقاضای نزدیکی زیر پا وجود ندارد.",
            zone_kind=kind, nearest_supply=nearest_supply, nearest_demand=nearest_demand,
            active_zone=nearest_supply,
            details={"zone_dist_atr": round(nearest_supply.dist_atr, 2)},
        )
    return PolarityVerdict(
        "SHORT", False, "NO_ZONE",
        "پین نزولی در هیچ عرضهٔ کلیدی یا فلیپِ ناشی از شکست معتبر قرار ندارد.",
        zone_kind="NONE", nearest_supply=nearest_supply, nearest_demand=nearest_demand,
        details={},
    )
