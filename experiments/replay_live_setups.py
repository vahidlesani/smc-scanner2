"""R31.5 — walk-forward replay of the LIVE pipeline (review suggestion B1).

What is replayed (production code is CALLED, not re-implemented):
  detection     quality_engine.scan_bundle(bundle)       every 15m close
  funnel        main.run_discovery_scan gates (approximated, see FUNNEL)
  confirmation  quality_engine.evaluate_confirmation      on confirm-TF closes
                + late-bound frame, expiry, SL invalidation, OUT_OF_REACH
  execution     trade_management.build_ladder / advance_ladder,
                execution_integrity_r29.trailing_from_ladder, band_trailing
                + smart_exit_scan after TP1 (repository_v7 loop), entry-fill
                gate with the ambiguous entry/stop NO-TRADE rule.

Look-ahead control:
  * every frame handed to the engine contains ONLY candles whose close time
    is <= sim-time t (Tape.closed);
  * data.fetcher.get_klines is replaced by the same tape (the counter-trend
    gate, TechnoClassic and the TLBREAK parent frame call it directly);
  * wall-clock is frozen at t with time-machine (datetime / time / pandas),
    so candidate expiry, PINVAL age and every cache TTL follow sim time;
  * network layers (market intelligence, on-chain, bot_kv) are stubbed/local.

Known simplifications (documented in the report):
  * chain absorb keeps the holder unchanged (production may move its zone);
  * the fast-frame (3m) reverse-pin exit is not simulated;
  * the ticker is synthesised from the tape (24h turnover, spread 0.02%).

Usage (one symbol × one arm per process; arms are env toggles):
  PYTHONPATH=. python experiments/replay_live_setups.py --symbol BTCUSDT \
      --days 120 --end 2026-09-24 --arm base --out replay_out
  PYTHONPATH=. python experiments/replay_live_setups.py --synthetic --days 20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time as _wall
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

# isolate every side effect BEFORE project modules import settings/db
_TMP = tempfile.mkdtemp(prefix="replay_")
os.environ.setdefault("DB_PATH", os.path.join(_TMP, "signals.db"))
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("GEMINI_API_KEY", "")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Research arms (env applied before any project module reads settings).
_FLOOR = "15m:1.2,30m:1.4,1h:1.6,4h:2.5,1d:4.0"
ARMS: Dict[str, Dict[str, str]] = {
    "base": {},
    "legacy": {"CONFIRM_TL_EXTRAPOLATE": "0", "REPLAY_BUNDLE_30M": "0"},
    "pin30": {"PINVAL_30M_ENABLED": "1"},
    "stopfloor": {"REPLAY_STOP_FLOOR": _FLOOR},
    "oor4": {"SCENARIO_OUT_OF_REACH_ATR": "4"},
    "trend4h": {"REPLAY_TREND_GATE": "4h"},
    "combo": {"REPLAY_STOP_FLOOR": _FLOOR, "REPLAY_TREND_GATE": "4h"},
    # the production implementation of the two recommended filters
    # (analysis/quality_filters.py): trend = mandatory gate, stop floor = reject
    "prodfilters": {"HTF_TREND_GATE": "4h", "MIN_STOP_FLOOR": "1"},
    # round 3: review B4 (strong confirmation bar) in-engine, alone and on
    # top of the production trend gate
    "b4": {"MIN_CONFIRM_BAR": "1"},
    "trendb4": {"HTF_TREND_GATE": "4h", "MIN_CONFIRM_BAR": "1"},
    # round 4 (R31.6): soft trend gate — neutral band around the 4h EMA50
    "prodsoft05": {"HTF_TREND_GATE": "4h", "HTF_TREND_BAND": "0.5", "MIN_STOP_FLOOR": "1"},
    "prodsoft10": {"HTF_TREND_GATE": "4h", "HTF_TREND_BAND": "1.0", "MIN_STOP_FLOOR": "1"},
    "oorentry": {"OOR_REF": "entry"},
}

TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
# production get_market_bundle limits (main.py default call) — 30m is added by
# the R31.5 fix; with REPLAY_BUNDLE_30M=0 the bundle mirrors the old live bug.
BUNDLE_LIMITS = {"5m": 300, "15m": 800, "30m": 400, "1h": 200, "4h": 170, "1d": 120}


# ─────────────────────────────── tape ────────────────────────────────────
class Tape:
    """Full history per TF with O(log n) 'closed up to t' slicing."""

    def __init__(self, symbol: str, base: Dict[str, pd.DataFrame]):
        from data.fetcher import _resample_ohlcv
        self.symbol = symbol
        self.df: Dict[str, pd.DataFrame] = {}
        for tf in ("5m", "15m", "4h", "1d"):
            d = base[tf].copy()
            d["timestamp"] = pd.to_datetime(d["timestamp"])
            if "turnover" not in d:
                d["turnover"] = d["close"] * d["volume"]
            self.df[tf] = d.sort_values("timestamp").reset_index(drop=True)
        self.df["1h"] = _resample_ohlcv(self.df["15m"], "1h", 4)
        self.df["30m"] = _resample_ohlcv(self.df["15m"], "30min", 2)
        self.close_ns: Dict[str, np.ndarray] = {}
        for tf, d in self.df.items():
            ts = pd.to_datetime(d["timestamp"]).values.astype("datetime64[ns]").astype(np.int64)
            self.close_ns[tf] = ts + TF_MIN[tf] * 60 * 10**9
        self._h5 = self.df["5m"]["high"].astype(float).values
        self._l5 = self.df["5m"]["low"].astype(float).values
        t15 = self.df["15m"]
        self._turn_cum = np.cumsum(t15["turnover"].fillna(t15["close"] * t15["volume"]).values)

    def _idx(self, tf: str, t: pd.Timestamp) -> int:
        return int(np.searchsorted(self.close_ns[tf], t.value, side="right"))

    def closed(self, tf: str, t: pd.Timestamp, n: int) -> Optional[pd.DataFrame]:
        if tf not in self.df:
            return None
        i = self._idx(tf, t)
        if i <= 0:
            return None
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        if tf in ("5m", "15m", "4h", "1d"):
            cols = cols + ["turnover"]
        return self.df[tf].iloc[max(0, i - int(n)):i][cols].reset_index(drop=True)

    def first_hit(self, t: pd.Timestamp, direction: str, entry: float, sl: float, tp: float,
                  hours: float) -> Dict:
        """DIAGNOSTIC ONLY (looks ahead, never feeds a decision): after t, is
        the entry touched inside `hours`, and does TP1 or the stop print first
        (same 5m bar = stop, conservative)?"""
        out = {"touched": False, "outcome": 0, "hours": None}
        try:
            i0 = self._idx("5m", t)
            i1 = self._idx("5m", t + pd.Timedelta(hours=float(hours)))
            hi, lo = self._h5[i0:i1], self._l5[i0:i1]
            if len(hi) == 0 or not (entry > 0 and sl > 0 and tp > 0):
                return out
            touch = np.nonzero((lo <= entry) & (hi >= entry))[0]
            if len(touch) == 0:
                return out
            k = int(touch[0])
            hi, lo = hi[k:], lo[k:]
            if str(direction).upper() == "LONG":
                s_hit, t_hit = np.nonzero(lo <= sl)[0], np.nonzero(hi >= tp)[0]
            else:
                s_hit, t_hit = np.nonzero(hi >= sl)[0], np.nonzero(lo <= tp)[0]
            si = int(s_hit[0]) if len(s_hit) else 10**9
            ti = int(t_hit[0]) if len(t_hit) else 10**9
            out["touched"] = True
            if si == ti == 10**9:
                return out
            out["outcome"] = 1 if ti < si else -1
            out["hours"] = round((k + min(si, ti)) * 5 / 60.0, 2)
        except Exception:
            pass
        return out

    def forming(self, tf: str, t: pd.Timestamp) -> Optional[pd.DataFrame]:
        """The live (forming) candle at t, built from closed 5m bars."""
        m = TF_MIN.get(tf)
        if not m:
            return None
        start = t.floor(f"{m}min")
        f5 = self.closed("5m", t, max(1, m // 5 + 1))
        if f5 is None:
            return None
        part = f5[f5["timestamp"] >= start]
        if part.empty:
            return None
        return pd.DataFrame([{
            "timestamp": start, "open": float(part["open"].iloc[0]),
            "high": float(part["high"].max()), "low": float(part["low"].min()),
            "close": float(part["close"].iloc[-1]), "volume": float(part["volume"].sum()),
            "turnover": float(part.get("turnover", part["volume"] * part["close"]).sum()),
        }])

    def is_close(self, tf: str, t: pd.Timestamp) -> bool:
        m = TF_MIN[tf]
        return (t.value // 60_000_000_000) % m == 0 if tf != "1d" else (t.hour == 0 and t.minute == 0)

    def price(self, t: pd.Timestamp) -> Optional[float]:
        i = self._idx("5m", t)
        return float(self.df["5m"]["close"].iloc[i - 1]) if i > 0 else None

    def ticker(self, t: pd.Timestamp) -> Dict:
        i = self._idx("15m", t)
        if i < 96 * 8:
            turn = float(self._turn_cum[i - 1]) if i > 0 else 0.0
            return {"turnover24h": turn, "spread_pct": 0.02, "relative_volume": 1.0}
        day = self._turn_cum[i - 1] - self._turn_cum[i - 97]
        prev = [self._turn_cum[i - 1 - 96 * k] - self._turn_cum[i - 97 - 96 * k] for k in range(1, 8)]
        med = float(np.median(prev)) or 1.0
        return {"turnover24h": float(day), "trading_day_turnover": float(day),
                "spread_pct": 0.02, "relative_volume": float(day) / med,
                "lastPrice": self.price(t)}

    def bundle(self, t: pd.Timestamp):
        from data.fetcher import MarketBundle
        tfs = ["1d", "4h", "1h", "15m", "5m"]
        if os.getenv("REPLAY_BUNDLE_30M", "1") != "0":
            tfs.append("30m")
        frames = {tf: self.closed(tf, t, BUNDLE_LIMITS[tf]) for tf in tfs}
        return MarketBundle(symbol=self.symbol, frames=frames, ticker=self.ticker(t))


# ────────────────────────── environment patches ──────────────────────────
class Sim:
    tape: Optional[Tape] = None
    t: Optional[pd.Timestamp] = None


def _fake_get_klines(symbol, interval, limit=200, closed_only=True, use_cache=True, end_ms=None, **_):
    tape, t = Sim.tape, Sim.t
    if tape is None or t is None or str(symbol).upper() != tape.symbol:
        return None
    tf = str(interval).lower()
    if tf not in tape.df:
        return None
    if closed_only:
        return tape.closed(tf, t, int(limit))
    closed = tape.closed(tf, t, max(1, int(limit) - 1))
    live = tape.forming(tf, t)
    if closed is None:
        return live
    if live is None or (len(closed) and live["timestamp"].iloc[0] <= closed["timestamp"].iloc[-1]):
        return closed
    return pd.concat([closed, live], ignore_index=True)


def install_patches() -> None:
    import data.fetcher as fetcher
    fetcher.get_klines = _fake_get_klines
    fetcher.get_klines_paginated = lambda s, tf, n, closed_only=True, **k: _fake_get_klines(s, tf, n, closed_only)
    for modname in ("analysis.mtf", "database.repository_v7"):
        try:
            mod = __import__(modname, fromlist=["x"])
            if hasattr(mod, "get_klines"):
                mod.get_klines = _fake_get_klines
        except Exception:
            pass
    try:
        import analysis.market_intelligence as mi
        mi.build_market_intelligence = lambda bundle: {"status": "UNAVAILABLE", "version": "MI-1"}
        for name in ("_depth_snapshot", "_oi_and_funding", "_positioning", "_onchain_context"):
            if hasattr(mi, name):
                setattr(mi, name, lambda *a, **k: {})
    except Exception:
        pass
    try:
        import analysis.onchain_free as oc
        for name in dir(oc):
            if name.startswith(("get_", "fetch_", "_fetch", "_get")) and callable(getattr(oc, name)):
                setattr(oc, name, lambda *a, **k: None)
    except Exception:
        pass


# ───────────────────────────── helpers ───────────────────────────────────
def out_of_reach(c, price, atr_mult) -> bool:
    try:
        atr = float((c.metadata or {}).get("atr") or 0)
        if atr <= 0 or price is None:
            return False
        from analysis.quality_filters import oor_reference
        mid = oor_reference(c)          # production reference (zone mid unless OOR_REF=entry)
        if c.direction == "LONG" and price < mid:
            return False
        if c.direction == "SHORT" and price > mid:
            return False
        return abs(price - mid) / atr > atr_mult
    except Exception:
        return False


def _near(a, b, rel):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return True
    return abs(a - b) <= max(abs(b) * rel, 1e-9)


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _adx(df: pd.DataFrame, n: int = 14) -> float:
    try:
        h, l, c = df["high"], df["low"], df["close"]
        up, dn = h.diff(), -l.diff()
        pdm = up.where((up > dn) & (up > 0), 0.0)
        ndm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / n, adjust=False).mean()
        pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / atr
        ndi = 100 * ndm.ewm(alpha=1 / n, adjust=False).mean() / atr
        dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
        return float(dx.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])
    except Exception:
        return float("nan")


def _vr(df: Optional[pd.DataFrame], k: int = 20) -> float:
    try:
        v = df["volume"].astype(float)
        med = float(v.iloc[-k - 1:-1].median())
        return round(float(v.iloc[-1]) / med, 3) if med > 0 else float("nan")
    except Exception:
        return float("nan")


def detection_features(c, tape: "Tape", t: pd.Timestamp) -> Dict:
    trig = str(c.trigger_timeframe or "").lower()
    tdf = tape.closed(trig, t, 120) if trig in TF_MIN else None
    md = c.metadata or {}
    out = {"det_t": str(t), "det_vr": _vr(tdf), "det_adx": round(_adx(tdf), 2) if tdf is not None else None,
           "variant": str(md.get("strategy_variant") or md.get("variant") or ""),
           "kind": str(md.get("pattern_kind") or md.get("pattern") or md.get("kind") or "")[:40]}
    bt = md.get("brooks_tiers")
    if isinstance(bt, dict):
        out["p1_signal_bar"] = bool(bt.get("p1_signal_bar"))
    return out


def confirmation_features(c, tape: "Tape", t: pd.Timestamp, ctf: str) -> Dict:
    md = c.metadata or {}
    sign = 1 if c.direction == "LONG" else -1
    out = {"entry_type": str(md.get("viva_entry_type") or ""),
           "fast_break": bool(md.get("tl_fast_break")),
           "stop_clamped": bool(md.get("stop_clamped")),
           "alt_trigger": str(md.get("alt_trigger_kind") or "")}
    cdf = tape.closed(ctf, t, 60)
    try:
        last, prev = cdf.iloc[-1], cdf.iloc[-2]
        rng = (cdf["high"] - cdf["low"]).tail(14).mean()
        out["conf_body_atr"] = round(abs(float(last.close) - float(last.open)) / float(rng), 3)
        out["conf_beyond_prev"] = bool((float(last.close) > float(prev.high)) if sign > 0
                                       else (float(last.close) < float(prev.low)))
        out["conf_vr"] = _vr(cdf)
    except Exception:
        pass
    for tf, n in (("4h", 50), ("1d", 20)):
        d = tape.closed(tf, t, n * 3)
        try:
            e = _ema(d["close"].astype(float), n)
            out[f"trend_{tf}"] = int(np.sign(float(d["close"].iloc[-1]) - float(e.iloc[-1])) * sign)
        except Exception:
            out[f"trend_{tf}"] = 0
    return out


class Trade:
    __slots__ = ("feats", "c", "setup", "tf", "style", "direction", "entry", "sl0", "ladder",
                 "confirmed_at", "filled_at", "cursor", "closed_at", "state", "reason",
                 "monitor_tf", "atr_n", "score", "risk_pct", "max_fav_r", "max_adv_r",
                 "fill_deadline", "lane")

    def as_row(self, fee_pct, slip_pct):
        r_gross = float(self.ladder.get("realized_r") or 0.0) if self.ladder else 0.0
        fee_r = (2 * fee_pct) / self.risk_pct if self.risk_pct else 0.0
        slip_r = (2 * slip_pct) / self.risk_pct if self.risk_pct else 0.0
        tg = list(self.ladder.get("targets") or []) if self.ladder else []
        return {
            "symbol": Sim.tape.symbol, "setup": self.setup, "tf": self.tf, "style": self.style,
            "dir": self.direction, "lane": self.lane, "score": self.score,
            "confirmed_at": str(self.confirmed_at), "filled_at": str(self.filled_at or ""),
            "closed_at": str(self.closed_at or ""), "state": self.state, "reason": self.reason,
            "entry": self.entry, "sl": self.sl0, "risk_pct": round(self.risk_pct, 4),
            "tp1_pct": round(abs(tg[0] - self.entry) / self.entry * 100, 4) if tg else None,
            "tp1_r": round(abs(tg[0] - self.entry) / abs(self.entry - self.sl0), 3) if tg else None,
            "hit": int(self.ladder.get("hit_index") or 0) if self.ladder else 0,
            "r_gross": round(r_gross, 4), "r_net": round(r_gross - fee_r, 4),
            "r_net_slip": round(r_gross - fee_r - slip_r, 4),
            "mfe_r": round(self.max_fav_r, 3), "mae_r": round(self.max_adv_r, 3),
            **(self.feats or {}),
        }


# ───────────────────────────── replay ────────────────────────────────────
def run(tape: Tape, start: pd.Timestamp, end: pd.Timestamp, arm: str, out_dir: Path,
        verbose: bool = False) -> Dict:
    import time_machine
    install_patches()
    from config import get_settings
    from analysis import quality_engine as qe
    from analysis.setups_v7 import confirm_late_tf, expiry_hours_for
    from analysis.trade_management import (build_ladder, advance_ladder, entry_touched,
                                           band_trailing, smart_exit_scan)
    from analysis.execution_integrity_r29 import trailing_from_ladder
    from database.repository_v7 import monitor_tf_for, vol_atr_n_for

    S = get_settings()
    fee_pct = float(S.fee_rate_percent)
    slip_pct = float(S.slippage_percent)
    ladder_fee = (S.fee_rate_percent + S.slippage_percent) * 2.0 / 100.0
    oor_atr = float(getattr(S, "scenario_out_of_reach_atr", 2.0))
    lic_cap = max(1, int(getattr(S, "chains_per_symbol_setup_24h", 3) or 3))
    lic_sep = float(getattr(S, "license_min_sep_pct", 0.02) or 0.0)
    quality_lanes = {"ALBROX", "TLBREAK", "TECHCLASSIC"}
    stop_floor = {k: float(v) for k, v in (x.split(":") for x in
                  os.getenv("REPLAY_STOP_FLOOR", "").split(",") if ":" in x)}
    trend_gate = os.getenv("REPLAY_TREND_GATE", "").strip()

    Sim.tape = tape
    traveller = time_machine.travel(start.to_pydatetime().replace(tzinfo=timezone.utc), tick=False)
    clock = traveller.start()

    funnel: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    active: Dict[str, object] = {}          # signal_id -> candidate (unconfirmed, tracked)
    history: List[Dict] = []                # licence/lineage memory
    last_conf_entry: Dict[tuple, float] = {}
    trades: List[Trade] = []
    confirmed_geo: List[tuple] = []         # (time, direction, entry, sl, tp1)
    scan_time = 0.0
    n_scans = 0

    def F(c, key, n=1):
        funnel[f"{c.setup_code}|{str(c.trigger_timeframe).lower()}"][key] += n

    # ── candidate-fate diagnostics (R31.6): why do tracked scenarios die, and
    # would the unconfirmed plan have worked? Pure bookkeeping — the shadow
    # outcome looks ahead and never feeds any decision.
    fates: List[Dict] = []
    rej: Dict[str, Dict[str, int]] = {}
    snap: Dict[str, Dict] = {}

    def note_eval(c):
        code = str((c.metadata or {}).get("last_reject_code") or "NONE")
        d = rej.setdefault(c.signal_id, {})
        d[code] = d.get(code, 0) + 1

    def fate(c, how: str, extra: Optional[Dict] = None):
        sid = c.signal_id
        sn = snap.pop(sid, None)
        codes = rej.pop(sid, {})
        if sn is None:
            return
        md = c.metadata or {}
        tc = md.get("technoclassic") or {}
        risk = abs(sn["entry"] - sn["sl"])
        row = {"setup": c.setup_code, "tf": str(c.trigger_timeframe).lower(), "dir": c.direction,
               "kind": str(tc.get("kind") or md.get("viva_entry_type") or ""),
               "pattern": str(md.get("viva_pattern") or md.get("pattern_type") or "")[:24],
               "fate": how, "t_det": str(sn["t"]), "alive_h": round((t - sn["t"]).total_seconds() / 3600, 2),
               "n_eval": int(sum(codes.values())),
               "rej": dict(sorted(codes.items(), key=lambda x: -x[1])[:4]),
               "risk_pct": round(risk / sn["entry"] * 100, 3) if sn["entry"] else None,
               "tp1_r": round(abs(sn["tp1"] - sn["entry"]) / risk, 3) if risk else None,
               "edge_src": str(md.get("confirm_edge_source") or ""),
               "major_tf": str(md.get("viva_major_break_line_tf") or "")}
        sh = tape.first_hit(sn["t"], c.direction, sn["entry"], sn["sl"], sn["tp1"], sn["hours"])
        fee_r = (2 * fee_pct / row["risk_pct"]) if row["risk_pct"] else 0.0
        row.update({"sh_touched": sh["touched"], "sh_outcome": sh["outcome"], "sh_hours": sh["hours"],
                    "sh_r": round((row["tp1_r"] or 0.0) - fee_r if sh["outcome"] > 0
                                  else (-1.0 - fee_r if sh["outcome"] < 0 else 0.0), 4)})
        try:
            if price is not None and float((c.metadata or {}).get("atr") or 0) > 0:
                mid = (float(c.entry_zone_bottom) + float(c.entry_zone_top)) / 2.0
                row["dist_atr"] = round(abs(price - mid) / float(c.metadata["atr"]), 2)
        except Exception:
            pass
        if extra:
            row.update(extra)
        fates.append(row)

    t = start
    step = pd.Timedelta(minutes=5)
    while t <= end:
        Sim.t = t
        clock.move_to((t + pd.Timedelta(seconds=40)).to_pydatetime().replace(tzinfo=timezone.utc))
        price = tape.price(t)

        # ── 1) open trades: one step per closed monitor candle ────────────
        for tr in trades:
            if tr.state in ("CLOSED", "NO_FILL", "AMBIGUOUS"):
                continue
            if not tape.is_close(tr.monitor_tf, t):
                continue
            frame = tape.closed(tr.monitor_tf, t, 40)
            if frame is None or frame.empty:
                continue
            candle = frame.iloc[-1]
            if pd.Timestamp(candle["timestamp"]) <= tr.cursor:
                continue
            tr.cursor = pd.Timestamp(candle["timestamp"])
            hi, lo, cl = float(candle["high"]), float(candle["low"]), float(candle["close"])
            if tr.state == "AWAIT_FILL":
                if entry_touched(tr.entry, hi, lo):
                    crossed = lo <= tr.sl0 if tr.direction == "LONG" else hi >= tr.sl0
                    if crossed:
                        tr.state, tr.reason, tr.closed_at = "AMBIGUOUS", "AMBIGUOUS_ENTRY_STOP", t
                    else:
                        tr.state, tr.filled_at = "OPEN", t
                elif t >= tr.fill_deadline:
                    tr.state, tr.reason, tr.closed_at = "NO_FILL", "EXPIRED_UNFILLED", t
                continue
            risk = abs(tr.entry - tr.sl0)
            fav = (hi - tr.entry) if tr.direction == "LONG" else (tr.entry - lo)
            adv = (tr.entry - lo) if tr.direction == "LONG" else (hi - tr.entry)
            tr.max_fav_r = max(tr.max_fav_r, fav / risk)
            tr.max_adv_r = max(tr.max_adv_r, adv / risk)
            lad = advance_ladder(tr.ladder, hi, lo)["state"]
            wc = [{"open": float(r.open), "high": float(r.high), "low": float(r.low),
                   "close": float(r.close), "volume": float(r.volume or 0.0)}
                  for r in frame.tail(31).itertuples()]
            try:
                lad = trailing_from_ladder(lad, wc, tr.direction).get("state", lad)
            except Exception:
                pass
            if (not lad.get("closed") and int(lad.get("version") or 1) >= 2
                    and int(lad.get("hit_index") or 0) >= 1 and len(wc) >= 21):
                lad = band_trailing(lad, wc, atr_n=tr.atr_n)["state"]
                scan = smart_exit_scan(tr.direction, wc, lad)
                pin = any("پین‌بار" in str(x) for x in (scan.get("reasons") or []))
                if int(scan.get("score") or 0) >= 2 or pin:
                    hit = int(lad.get("hit_index") or 0)
                    wts = [float(w) for w in (lad.get("weights") or [])]
                    rem = 100.0 - sum(wts[:hit])
                    ex_r = ((cl - tr.entry) if tr.direction == "LONG" else (tr.entry - cl)) / risk
                    lad["realized_r"] = float(lad.get("realized_r") or 0.0) + ex_r * rem / 100.0
                    lad["closed"], lad["close_reason"] = True, "SMART_EXIT"
            tr.ladder = lad
            if lad.get("closed"):
                tr.state, tr.closed_at = "CLOSED", t
                tr.reason = str(lad.get("close_reason") or ("STOP" if int(lad.get("hit_index") or 0) == 0
                                                             else "TRAIL/LADDER"))

        # ── 2) unconfirmed candidates: expiry / invalidation / confirmation ─
        for sid in list(active):
            c = active[sid]
            if qe.is_expired(c):
                F(c, "expired"); fate(c, "expired"); del active[sid]; continue
            if price is not None and qe.is_invalidated(c, price):
                F(c, "invalidated"); fate(c, "invalidated"); del active[sid]; continue
            trig = str(c.trigger_timeframe or "").lower()
            ctf = str((c.metadata or {}).get("confirm_tf") or trig).lower()
            if ctf not in TF_MIN:
                ctf = trig
            late = confirm_late_tf(trig)
            confirmed = False
            pat = tape.closed(trig, t, 139) if ctf != trig else None
            if tape.is_close(ctf, t):
                confirmed, c, _ = qe.evaluate_confirmation(c, tape.closed(ctf, t, 139), htf_closed_df=pat)
                if not confirmed:
                    note_eval(c)
            if not confirmed and late and late != ctf and late in TF_MIN and tape.is_close(late, t):
                confirmed, c, _ = qe.evaluate_confirmation(c, tape.closed(late, t, 139), htf_closed_df=pat)
                if not confirmed:
                    note_eval(c)
            active[sid] = c
            if not confirmed:
                if out_of_reach(c, price, oor_atr):
                    F(c, "out_of_reach"); fate(c, "out_of_reach"); del active[sid]
                continue
            del active[sid]
            try:
                qe.freeze_confirmed_snapshot(c)
            except Exception:
                pass
            entry = float(c.planned_entry or 0)
            widened = False
            if stop_floor.get(trig) and entry > 0:
                need = entry * stop_floor[trig] / 100.0
                if abs(entry - float(c.sl)) < need:
                    c.sl = entry - need if c.direction == "LONG" else entry + need
                    widened = True
            cut = t - pd.Timedelta(hours=24)
            if any(g[0] >= cut and g[1] == c.direction and _near(entry, g[2], 0.0045)
                   and _near(c.sl, g[3], 0.0045) and _near(c.tp1, g[4], 0.012) for g in confirmed_geo):
                F(c, "geo_dup"); fate(c, "geo_dup"); continue
            try:
                lad = build_ladder(entry, c.sl, c.direction, c.market, c.tp2, structural_tp1=c.tp1,
                                   fee_pct=ladder_fee, trigger_tf=trig,
                                   wall_level=float((c.metadata or {}).get("internal_wall") or 0.0))
            except Exception:
                F(c, "ladder_error"); fate(c, "ladder_error"); continue
            F(c, "confirmed")
            fate(c, "confirmed", {"conf_h": round((t - snap.get(c.signal_id, {}).get("t", t)).total_seconds() / 3600, 2)})
            confirmed_geo.append((t, c.direction, entry, float(c.sl), float(c.tp1 or 0)))
            last_conf_entry[(c.setup_code, trig)] = entry
            tr = Trade()
            tr.c, tr.setup, tr.tf, tr.style = None, c.setup_code, trig, c.style
            tr.direction, tr.entry, tr.sl0, tr.ladder = c.direction, entry, float(c.sl), lad
            tr.confirmed_at, tr.filled_at, tr.closed_at = t, None, None
            tr.monitor_tf = monitor_tf_for(trig) if monitor_tf_for(trig) in TF_MIN else trig
            # production: pending = monitor candles whose OPEN > confirmed_at
            # (wall-clock just after the confirming close)
            tr.cursor = t + pd.Timedelta(seconds=40)
            tr.atr_n = vol_atr_n_for(trig, tr.monitor_tf)
            tr.state, tr.reason, tr.score = "AWAIT_FILL", "", float(c.score)
            tr.risk_pct = abs(entry - float(c.sl)) / entry * 100.0
            tr.max_fav_r = tr.max_adv_r = 0.0
            tr.fill_deadline = t + pd.Timedelta(hours=float(expiry_hours_for(c.style, trig)))
            tr.feats = dict((c.metadata or {}).get("_rp_det") or {})
            tr.feats.update(confirmation_features(c, tape, t, ctf))
            tr.feats["stop_widened"] = widened
            tr.lane = tr.feats.get("entry_type") or ("FAST" if tr.feats.get("fast_break") else "")
            trades.append(tr)

        # ── 3) discovery scan at every 15m close ──────────────────────────
        if tape.is_close("15m", t) and t >= start:
            t0 = _wall.perf_counter()
            try:
                cands = qe.scan_bundle(tape.bundle(t))
            except Exception as exc:
                cands = []
                funnel["_errors"][type(exc).__name__] += 1
                if verbose:
                    import traceback; traceback.print_exc()
            scan_time += _wall.perf_counter() - t0
            n_scans += 1
            for c in cands:
                trig = str(c.trigger_timeframe or "").lower()
                F(c, "seen")
                if c.score < S.educational_min_score:
                    F(c, "low_score"); continue
                if trend_gate:
                    d = tape.closed(trend_gate, t, 150)
                    try:
                        e = float(_ema(d["close"].astype(float), 50).iloc[-1])
                        up = float(d["close"].iloc[-1]) > e
                        if (c.direction == "LONG") != up:
                            F(c, "trend_gate"); continue
                    except Exception:
                        pass
                lane_q = str(c.setup_code).upper() in quality_lanes
                if not lane_q:
                    holder = [a for a in active.values() if a.setup_code == c.setup_code
                              and str(a.trigger_timeframe).lower() == trig and a.direction == c.direction
                              and a.signal_id != c.signal_id]
                    if holder:
                        F(c, "chain_absorbed"); continue
                    used = sum(1 for h in history if h["setup"] == c.setup_code and h["tf"] == trig
                               and h["t"] >= t - pd.Timedelta(hours=24))
                    if used >= lic_cap:
                        F(c, "license_cap"); continue
                    atr = max(float((c.metadata or {}).get("atr", 0) or 0), 1e-9)
                    tol = max(atr * 0.20, abs(float(c.zone_mid)) * 1e-4)
                    if any(h["setup"] == c.setup_code and h["tf"] == trig and h["sid"] != c.signal_id
                           and h["t"] >= t - pd.Timedelta(hours=24) and abs(h["zone"] - float(c.zone_mid)) <= tol
                           for h in history):
                        F(c, "same_zone_quiet"); continue
                    lp = last_conf_entry.get((c.setup_code, trig))
                    px = float(c.planned_entry or c.entry_zone_bottom or 0)
                    if lic_sep > 0 and lp and px and abs(px - lp) < lic_sep * abs(lp):
                        F(c, "sep2pct"); continue
                if S.skip_dead_gate_candidates and not c.execution_ready:
                    F(c, "dead_gate")
                    for g, v in (c.mandatory_gates or {}).items():
                        if not v:
                            F(c, f"gate:{g}")
                    continue
                if any(tr.setup == c.setup_code and tr.tf == trig and tr.state in ("AWAIT_FILL", "OPEN")
                       and int((tr.ladder or {}).get("hit_index") or 0) == 0 for tr in trades):
                    F(c, "pre_tp1_open"); continue
                if c.signal_id in active:
                    F(c, "dup"); continue
                # supersede an earlier unconfirmed alert of the same lineage
                for sid in [s for s, a in active.items() if a.setup_code == c.setup_code
                            and str(a.trigger_timeframe).lower() == trig and a.direction == c.direction]:
                    F(active[sid], "superseded"); fate(active[sid], "superseded"); del active[sid]
                try:
                    c.metadata["_rp_det"] = detection_features(c, tape, t)
                except Exception:
                    pass
                active[c.signal_id] = c
                try:
                    snap[c.signal_id] = {"t": t, "entry": float(c.planned_entry or 0), "sl": float(c.sl or 0),
                                         "tp1": float(c.tp1 or 0),
                                         "hours": float(expiry_hours_for(c.style, trig))}
                except Exception:
                    pass
                history.append({"setup": c.setup_code, "tf": trig, "t": t, "sid": c.signal_id,
                                "zone": float(c.zone_mid)})
                F(c, "tracked")
        t += step

    traveller.stop()
    for c in list(active.values()):
        F(c, "open_at_end"); fate(c, "open_at_end")
    rows = [tr.as_row(fee_pct, slip_pct) for tr in trades]
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{tape.symbol}__{arm}"
    with open(out_dir / f"trades__{tag}.jsonl", "w") as fh:
        for r in rows:
            r["arm"] = arm
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"symbol": tape.symbol, "arm": arm, "start": str(start), "end": str(end),
               "scans": n_scans, "scan_sec": round(scan_time, 1),
               "funnel": {k: dict(v) for k, v in funnel.items()}, "trades": len(rows)}
    with open(out_dir / f"fates__{tag}.jsonl", "w") as fh:
        for r in fates:
            r["arm"], r["symbol"] = arm, tape.symbol
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / f"funnel__{tag}.json", "w") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    return summary


# ───────────────────────────── data ──────────────────────────────────────
def synthetic_base(days: int, seed: int = 7) -> Dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    n = days * 288
    ts = pd.date_range("2026-01-01", periods=n, freq="5min")
    # regime-switching drift so structure (trends, ranges, breaks) exists
    drift = np.repeat(rng.normal(0, 0.0006, n // 288 + 1), 288)[:n]
    ret = drift + rng.standard_t(4, n) * 0.0022
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1]]
    wig = np.abs(rng.normal(0, 0.0016, n)) * close
    high = np.maximum(open_, close) + wig
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.0016, n)) * close
    vol = rng.lognormal(10, 0.6, n) * (1 + 8 * np.abs(ret))
    d5 = pd.DataFrame({"timestamp": ts, "open": open_, "high": high, "low": low,
                       "close": close, "volume": vol})
    d5["turnover"] = d5["volume"] * d5["close"]

    def agg(rule):
        a = d5.set_index("timestamp").resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
             "turnover": "sum"}).dropna()
        return a.reset_index()
    return {"5m": d5, "15m": agg("15min"), "4h": agg("4h"), "1d": agg("1D")}


def real_base(symbol: str, start: date, end: date) -> Dict[str, pd.DataFrame]:
    from experiments.replay_data import load
    warm = {"5m": 4, "15m": 12, "4h": 40, "1d": 160}
    out = {}
    for tf in ("5m", "15m", "4h", "1d"):
        df = load(symbol, tf, start - timedelta(days=warm[tf]), end)
        if df is None or df.empty:
            raise SystemExit(f"no data for {symbol} {tf}")
        out[tf] = df
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--end", default="")
    ap.add_argument("--arm", default=os.getenv("REPLAY_ARM", "base"))
    ap.add_argument("--out", default="replay_out")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    for k, v in ARMS.get(a.arm, {}).items():
        os.environ[k] = v
    if a.synthetic:
        base = synthetic_base(a.days + 170)
        tape = Tape("SYNTHUSDT", base)
        end = pd.Timestamp(base["5m"]["timestamp"].iloc[-1]).floor("15min")
        start = end - pd.Timedelta(days=a.days)
    else:
        end_d = date.fromisoformat(a.end) if a.end else (datetime.utcnow().date() - timedelta(days=1))
        start_d = end_d - timedelta(days=a.days)
        tape = Tape(a.symbol.upper(), real_base(a.symbol.upper(), start_d, end_d))
        start = pd.Timestamp(start_d)
        end = pd.Timestamp(end_d) + pd.Timedelta(hours=23, minutes=55)
    w0 = _wall.time()
    s = run(tape, start, end, a.arm, Path(a.out), verbose=a.verbose)
    print(json.dumps({k: v for k, v in s.items() if k != "funnel"}, ensure_ascii=False))
    print(f"wall {(_wall.time() - w0):.0f}s")


if __name__ == "__main__":
    main()
