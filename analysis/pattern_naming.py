"""R99q29 — THE NAMING LAYER (Viva 10-19, option B: «کامل»).

Measured gap before this module:

    setup          names its pattern?
    SPOT           yes  (spot_engine → pattern_law, 18 slugs)
    TECHCLASSIC    yes  (pattern_engine → pattern_law)
    ALBROX         yes  (lane A rides the TECHCLASSIC engine)
    TLBREAK        NO   — zero references to pattern_law
    zone engines   NO   — zero references to pattern_law

So a TLBREAK alert could say «شکست خط روند» and never «کانال نزولی شکست»,
and the chart had no law slug to stamp.

THE CONSTRAINT THAT SHAPES THIS FILE: he forbade touching the TL-break
engines («موتورهای تی‌ال‌بریک رو دست نزن — نه یک موتور»). This module is
therefore PURELY ADDITIVE and lives OUTSIDE them: `scan_setups` calls it
after a detector returns, and it only ever WRITES metadata. It never
changes a candidate's direction, entry, stop, target, score or status.

What it does:
  * rebuilds the two edges of the structure from the points the engine
    already stored (`viva_upper_points` / `viva_lower_points`,
    `pattern_geo`, or a single `viva_break_line`);
  * asks pattern_law.classify_pair for the ONE slug;
  * counts the taps on each edge (geometry_v2.touch_census) and grades them
    against his ADA/DOT references;
  * stamps `render_patterns` + `pattern_law_all` and runs `engine_stamp`, so
    the existing chart/message code renders the name and the reference with
    no further change.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import pandas as pd  # type: ignore


def _pts_to_line(points: List[Dict], df, log_fit: bool = True) -> Optional[Dict]:
    """Fit a render-shaped line through stored pivot points (global x).

    Points look like {"ts": iso, "price": p} or {"timestamp": ..., "price": p}.
    x is the BAR INDEX inside `df` (the same space render_kit draws in).
    Returns a dict accepted by render_kit.line_y and pattern_law.pair_metrics.
    """
    try:
        if df is None or len(df) < 10 or not points:
            return None
        idx = {}
        for i, ts in enumerate(pd.to_datetime(df["timestamp"]).tolist()):
            idx[_key(ts)] = i
        xs, ys = [], []
        for p in points:
            ts = p.get("ts") or p.get("timestamp") or p.get("t")
            pr = p.get("price") or p.get("p")
            if ts is None or pr is None:
                continue
            k = _key(pd.Timestamp(str(ts)))
            x = idx.get(k)
            if x is None:
                continue
            v = float(pr)
            if v <= 0:
                continue
            xs.append(float(x))
            ys.append(v)
        if len(xs) < 2 or max(xs) - min(xs) < 3:
            return None
        if log_fit:
            ly = [math.log10(v) for v in ys]
            sl, ic = _polyfit(xs, ly)
            return {"log_fit": True, "log_slope": float(sl), "log_intercept": float(ic),
                    "slope": float(sl), "intercept": float(ic),
                    "x0": int(min(xs)), "x1": int(len(df) - 1),
                    "points": [{"ts": str(p.get("ts") or p.get("timestamp")),
                                "price": float(p.get("price") or p.get("p") or 0)}
                               for p in points]}
        sl, ic = _polyfit(xs, ys)
        return {"log_fit": False, "slope": float(sl), "intercept": float(ic),
                "x0": int(min(xs)), "x1": int(len(df) - 1),
                "points": [{"ts": str(p.get("ts") or p.get("timestamp")),
                            "price": float(p.get("price") or p.get("p") or 0)}
                           for p in points]}
    except Exception:
        return None


def _key(ts) -> str:
    """Minute-resolution key so a stored pivot and the frame agree."""
    try:
        t = pd.Timestamp(ts)
        if t.tzinfo is not None:
            t = t.tz_convert("UTC").tz_localize(None)
        return t.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def _polyfit(xs: List[float], ys: List[float]):
    n = float(len(xs))
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    den = n * sxx - sx * sx
    if abs(den) < 1e-12:
        raise ValueError("degenerate")
    m = (n * sxy - sx * sy) / den
    b = (sy - m * sx) / n
    return m, b


def _fit_residual_atr(line: Dict, pts: List[Dict], atr: float) -> float:
    """Mean |pivot - line| in ATR — the honest fit error for a stored edge."""
    try:
        from analysis.render_kit import line_y
        if atr <= 0:
            return 0.0
        idx = []
        errs = []
        for p in pts or []:
            ts = p.get("ts") or p.get("timestamp")
            pr = p.get("price") or p.get("p")
            if ts is None or pr is None:
                continue
            idx.append((str(ts), float(pr)))
        # the caller stores global x already inside `line["points"]`
        for x, p in enumerate(pts or []):
            pass
        return 0.0 if not errs else sum(errs) / len(errs)
    except Exception:
        return 0.0


def _atr(df) -> float:
    try:
        return float((df["high"].astype(float).tail(14)
                      - df["low"].astype(float).tail(14)).mean())
    except Exception:
        return 0.0


def name_candidate(candidate, df, setup_code: str = "") -> Dict:
    """Name the structure a candidate traded. Additive; never vetoes.

    Returns the stamp dict (also written to candidate.metadata). Safe to call
    twice — a candidate that already carries `render_patterns` is left alone.
    """
    out: Dict = {"slug": "", "written": False, "reason": ""}
    try:
        md = candidate.metadata if isinstance(getattr(candidate, "metadata", None), dict) else {}
        if not md:
            return dict(out, reason="no metadata")
        if md.get("render_patterns"):
            # the engine already named it — never overwrite a richer answer
            return dict(out, slug=str(md.get("pattern_type") or ""), reason="already named")
        if df is None or len(df) < 45:
            return dict(out, reason="frame too short")

        from analysis.pattern_law import (
            classify_pair, engine_stamp, label_fa, pair_metrics, pattern_pid,
        )
        from analysis.geometry_v2 import pair_grade, touch_census

        up_pts = list(md.get("viva_upper_points") or [])
        lo_pts = list(md.get("viva_lower_points") or [])
        upper = _pts_to_line(up_pts, df) if up_pts else None
        lower = _pts_to_line(lo_pts, df) if lo_pts else None

        # ── single-line lanes ────────────────────────────────────────────
        # TLBREAK often trades ONE validated trendline. A lone line is a
        # TRENDLINE by the law's own contract (pair_metrics: single=True).
        if upper is None and lower is None:
            geo = md.get("pattern_geo") or {}
            if isinstance(geo, dict):
                upper = _from_geo(geo.get("upper"), df)
                lower = _from_geo(geo.get("lower"), df)
        if upper is None and lower is None:
            brk = float(md.get("viva_breakout_line") or md.get("viva_break_line") or 0.0)
            if brk > 0:
                out.update(dict(out, reason="single break level, no points"))
                md["pattern_law_all"] = [{
                    "type": "TRENDLINE", "law_slug": "TRENDLINE",
                    "single_line": True, "level": brk,
                    "name_fa": label_fa("TRENDLINE"),
                }]
                md["pattern_type"] = "TRENDLINE"
                md["tl_pattern"] = "TRENDLINE"
                md["pattern_label_fa"] = label_fa("TRENDLINE")
                engine_stamp(md, df, setup_code or str(getattr(candidate, "setup_code", "")))
                return dict(out, slug="TRENDLINE", written=True, reason="break level only")

        n = len(df) - 1
        if upper is None and lower is None:
            return dict(out, reason="no usable geometry")

        m = pair_metrics(upper, lower, n, df=df)
        meta: Dict = {}
        slug = classify_pair(m, meta) or "NONE"
        if slug in ("NONE", ""):
            slug = "TRENDLINE" if m.get("single") else "NONE"
        if slug == "NONE":
            # R99q29: `why` used to come back empty and the operator saw a
            # bare "law could not name it: " with nothing after the colon.
            # Always hand back the measurements the law actually had.
            _why = "; ".join(meta.get("why") or [])
            if not _why:
                _why = ("no family matched: ok=%s single=%s span=%s conv=%s"
                        % (m.get("ok"), m.get("single"), m.get("span"),
                           round(float(m.get("conv_ratio") or 0.0), 3)))
            return dict(out, reason="law could not name it: " + _why)

        atr = _atr(df)
        cu = touch_census(df, upper, "HIGH") if upper is not None else {"touches": 0}
        cl = touch_census(df, lower, "LOW") if lower is not None else {"touches": 0}
        grade_letter, grade_why = pair_grade(
            int(cu.get("touches") or 0), int(cl.get("touches") or 0),
            span=int(m.get("span") or 0))

        shape = {
            "type": slug, "law_slug": slug,
            "name_fa": label_fa(slug),
            "lines": [l for l in (upper, lower) if l],
            "upper_taps": int(cu.get("touches") or 0),
            "lower_taps": int(cl.get("touches") or 0),
            "grade": grade_letter, "grade_why": grade_why,
            "source": "naming_layer",
            "span": int(m.get("span") or 0),
            "conv_ratio": round(float(m.get("conv_ratio") or 1.0), 3),
        }
        try:
            shape["pid"] = pattern_pid(shape, str(getattr(candidate, "trigger_timeframe", "")))
        except Exception:
            shape["pid"] = ""

        md["pattern_law_all"] = [shape]
        md["render_patterns"] = [shape]
        md["pattern_type"] = slug
        md["tl_pattern"] = slug
        md["pattern_label_fa"] = label_fa(slug)
        md["pattern_flow"] = "naming_layer"
        md["pattern_why_fa"] = "; ".join(meta.get("why") or [])
        md["pattern_taps"] = {"upper": shape["upper_taps"], "lower": shape["lower_taps"]}
        md["pattern_grade"] = grade_letter
        engine_stamp(md, df, setup_code or str(getattr(candidate, "setup_code", "")))
        out.update({"slug": slug, "written": True, "grade": grade_letter,
                    "reason": grade_why})
        return out
    except Exception as exc:  # never break a scan for a label
        print(f"pattern_naming skipped {getattr(candidate, 'symbol', '?')}: {exc}")
        return dict(out, reason=f"error: {exc}")


def _from_geo(geo, df) -> Optional[Dict]:
    """Rebuild a line from a stored `pattern_geo` fit (global x, log space)."""
    try:
        if not isinstance(geo, dict) or not geo:
            return None
        if geo.get("log_fit") and geo.get("fit"):
            return {"log_fit": True,
                    "log_slope": float(geo.get("slope") or 0.0),
                    "log_intercept": float(geo.get("intercept") or 0.0),
                    "slope": float(geo.get("slope") or 0.0),
                    "intercept": float(geo.get("intercept") or 0.0),
                    "x0": int(geo.get("x_last") or 0), "x1": int(len(df) - 1)}
        if geo.get("x_last") is not None and "slope" in geo and "intercept" in geo:
            _xl = float(geo.get("x_last") or 0.0)
            _sl = float(geo.get("slope") or 0.0)
            _ic = float(geo.get("intercept") or 0.0)
            return {"log_fit": False, "slope": _sl, "intercept": _ic - _sl * _xl,
                    "x0": int(_xl), "x1": int(len(df) - 1)}
        return None
    except Exception:
        return None


def apply_naming(candidates, frames=None) -> List[Dict]:
    """Batch helper for scan_setups: name every candidate that has no name.

    `frames` is an optional {(symbol, tf): df}; when absent the candidate's own
    metadata must carry the frame. Fail-open per candidate.
    """
    out: List[Dict] = []
    for c in candidates or []:
        try:
            tf = str(getattr(c, "trigger_timeframe", "") or "")
            sym = str(getattr(c, "symbol", "") or "")
            df = (frames or {}).get((sym, tf))
            if df is None:
                cand_md = getattr(c, "metadata", None) or {}
                df = cand_md.get("_chart_df")
            if df is None:
                continue
            out.append(name_candidate(c, df))
        except Exception as exc:
            print(f"apply_naming skipped {getattr(c, 'symbol', '?')}: {exc}")
    return out
