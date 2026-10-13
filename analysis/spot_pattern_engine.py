"""
Dedicated Pattern & Trendline Engine for SPOT and Macro Charts.
Calibrated 100% to Authentic VIVA SIGNALS PRO Standards:
1. Strict G1 Law (Chart = Trade):
   Renders the EXACT geometry, pattern type, and pivot anchors detected by the trading engine
   (TRIANGLE_ASCENDING, TRIANGLE_SYMMETRICAL, FLAG_BULL, FLAG_BEAR, WEDGE, TRENDLINE, etc.).
   Zero disconnected OLS hallucinations.
2. Live Market Centric Zoom:
   Frames from the actual pattern origin (first anchor point), eliminating stale months-old candles.
   The active live structure fills the full width of the canvas.
3. Maximum Canvas Utilization (Tight Margins):
   Left & Right borders minimized via subplots_adjust, dedicating >92% of space to candles.
4. Crisp High-Resolution Rendering:
   DPI increased to 180 for razor-sharp TradingView aesthetics.
5. Exact Tehran Clock & Single Clean Price Tag:
   Displays precise Tehran date and time under youngest candle.
   Clean, single-value live price pill on the price axis without colliding labels.
6. Honest Directional Measured Move:
   Bullish breakouts show upward green target box.
   Bearish breakdowns show downward breakdown guide (never a fantasy long box on a breakdown alert!).
"""
from __future__ import annotations
import os
import io
import math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.image as mpimg
from matplotlib.ticker import FuncFormatter, LogLocator, MaxNLocator, FixedLocator


def _map_pattern_title(pat_type: str, pat_name_fa: str = "") -> str:
    pat_upper = str(pat_type or "").upper()
    mapping = {
        "TRIANGLE_ASCENDING": "Ascending Triangle",
        "TRIANGLE_DESCENDING": "Descending Triangle",
        "TRIANGLE_SYMMETRICAL": "Symmetrical Triangle",
        "FLAG_BULL": "Bull Flag",
        "FLAG_BEAR": "Bear Flag",
        "WEDGE_FALLING": "Falling Wedge",
        "WEDGE_RISING": "Rising Wedge",
        "CHANNEL_ASCENDING": "Ascending Channel",
        "CHANNEL_DESCENDING": "Descending Channel",
        "CHANNEL": "Parallel Channel",
        "TRENDLINE": "Major Trendline",
        "HEAD_AND_SHOULDERS": "Head & Shoulders",
        "INVERSE_H_AND_S": "Inverse H&S",
        "DOUBLE_TOP": "Double Top",
        "DOUBLE_BOTTOM": "Double Bottom"
    }
    for k, v in mapping.items():
        if k in pat_upper:
            return v
    if pat_name_fa:
        fa_map = {
            "مثلث صعودی": "Ascending Triangle",
            "مثلث متقارن": "Symmetrical Triangle",
            "مثلث نزولی": "Descending Triangle",
            "پرچم صعودی": "Bull Flag",
            "پرچم نزولی": "Bear Flag",
            "گوه صعودی": "Rising Wedge",
            "گوه نزولی": "Falling Wedge",
            "خط روند اصلی": "Major Trendline",
            "کانال صعودی": "Ascending Channel",
            "کانال نزولی": "Descending Channel"
        }
        for fk, fv in fa_map.items():
            if fk in pat_name_fa:
                return fv
    return pat_upper.replace("_", " ").title() or "Macro Structure"


_SPOT_BOX_TF_MULT = {"4h": 1.25, "8h": 1.35, "12h": 1.50,
                     "1d": 1.75, "3d": 2.50, "1w": 3.00}


def _spot_box_target(upper_level: float, tf: str, ceiling=None) -> float:
    """10-10 (his spot-box law): the green box rides to the NEXT STRUCTURAL
    ceiling; only in virgin ATH air (no ceiling) does the TF-sized fallback
    apply — never a flat 25% for every timeframe. Pure (unit-tested)."""
    try:
        up = float(upper_level)
    except Exception:
        up = 0.0
    try:
        ce = float(ceiling or 0.0)
    except Exception:
        ce = 0.0
    if ce > up * 1.005:
        return ce
    mult = _SPOT_BOX_TF_MULT.get(str(tf or "").lower(), 1.25)
    return up * mult


def _spot_future_bars(n: int) -> int:
    """10-11 (geometry pass): the projection tail scales with the visible
    frame so candles always fill the panel — small frames stop drowning in
    empty future, big frames keep the refs' ~10% tail. Pure (unit-tested)."""
    try:
        n = int(n)
    except Exception:
        n = 0
    return max(8, min(24, max(n, 0) // 6))


def _spot_engine_line_frame(line_info: dict, start_idx: int):
    """10-11 (G1): the ENGINE's calibrated line re-expressed in render-frame
    coordinates. Detection fits live in GLOBAL x (the full df); the chart
    draws a TRIMMED frame starting at start_idx, so y(xf) = f(xf + start_idx).
    Returns (log_slope, log_intercept_frame, x0_frame) or None when the line
    carries no usable fit (caller falls back to the legacy pivot polyfit).
    Pure (unit-tested)."""
    try:
        li = line_info or {}
        s_idx = int(start_idx)
        x0f = int(li.get("x0", 0)) - s_idx
        if (li.get("log_fit") and li.get("log_slope") is not None
                and li.get("log_intercept") is not None):
            s = float(li.get("log_slope"))
            c = float(li.get("log_intercept"))
            return (s, c + s * s_idx, x0f)
        if li.get("slope") is not None and li.get("intercept") is not None:
            s = float(li.get("slope"))
            c = float(li.get("intercept"))
            # linear-space engine line, log-linearized at the frame start
            # (the chart axis is log; downstream box math is log-convention).
            y0 = s * float(s_idx) + c
            y1 = s * float(s_idx + 1) + c
            if y0 > 0 and y1 > 0 and y1 != y0:
                sl = math.log10(y1) - math.log10(y0)
                return (sl, math.log10(y0), x0f)
            if y0 > 0:
                return (0.0, math.log10(y0), x0f)
        return None
    except Exception:
        return None


def _spot_map_pivots(points, frame_ts):
    """10-11 (G2): pivot ts → frame x. Out-of-frame pivots are SKIPPED
    (never snapped to an edge). Pure (unit-tested)."""
    out_x, out_y = [], []
    try:
        ts = list(frame_ts or [])
        n = len(ts)
        if n < 2 or not points:
            return out_x, out_y
        t0 = pd.to_datetime(ts[0])
        t1 = pd.to_datetime(ts[-1])
        bar_sec = abs((t1 - t0).total_seconds()) / max(1, n - 1)
        bar_sec = bar_sec if bar_sec > 0 else 1.0
        for pt in points:
            try:
                pt_dt = pd.to_datetime((pt or {}).get("ts"))
                price = float((pt or {}).get("price"))
            except Exception:
                continue
            diffs = [abs((pd.to_datetime(t) - pt_dt).total_seconds())
                     for t in ts]
            j = int(np.argmin(diffs))
            if diffs[j] > 1.5 * bar_sec:
                continue
            out_x.append(j)
            out_y.append(price)
        return out_x, out_y
    except Exception:
        return out_x, out_y


def _spot_earliest_inframe(point_tses, frame_start, frame_end, bar_sec: float):
    """10-11 (G6): earliest pivot ts inside the frame (+-2 bars tolerance);
    stale/unparsable pivots are ignored so the zoom follows the VISIBLE
    pattern. None when nothing qualifies. Pure (unit-tested)."""
    try:
        t0 = pd.to_datetime(frame_start)
        t1 = pd.to_datetime(frame_end)
        tol = pd.Timedelta(seconds=2 * (float(bar_sec) if float(bar_sec) > 0 else 1.0))
        good = []
        for p in point_tses or []:
            try:
                pt = pd.to_datetime(p.get("ts") if isinstance(p, dict) else p)
            except Exception:
                continue
            if t0 - tol <= pt <= t1 + tol:
                good.append(pt)
        return min(good) if good else None
    except Exception:
        return None


def _spot_is_breakdown(stage: str, direction: str = "LONG") -> bool:
    """10-12 (his ONDO chart: the target box MUST be drawn): a bearish-NAMED
    shape (descending channel, falling wedge) still breaks UP for a LONG —
    the box is skipped ONLY on a real BREAK_DOWN stage (or a SHORT
    direction). Pure (unit-tested)."""
    try:
        if "BREAK_DOWN" in str(stage or "").upper():
            return True
        return str(direction or "LONG").upper() == "SHORT"
    except Exception:
        return False


def render_cryptocove_spot_chart(df: pd.DataFrame, candidate, confirmed: bool = False) -> bytes:
    """
    Render the definitive VIVA SIGNALS PRO Spot Chart obedient to Law G1:
    - Renders the exact pattern and lines from candidate metadata (never disconnected hallucinated lines).
    - Intelligent framing anchored at the pattern's true start date.
    - Minimal left and right borders giving maximum canvas to candles.
    - Precise live price pill and Tehran timestamp.
    """
    symbol = str(getattr(candidate, 'symbol', '') or 'UNKNOWN').upper()
    tf = str((getattr(candidate, 'metadata', None) or {}).get('chart_view_tf')
             or getattr(candidate, 'trigger_timeframe', '8h') or '8h').lower()

    if len(df) < 25:
        return b''

    md = getattr(candidate, 'metadata', {}) or {}
    rp_list = md.get('render_patterns') or []
    stage = str(md.get('spot_alert_stage') or getattr(candidate, 'status', '') or '').upper()
    side = str(md.get('spot_alert_side') or getattr(candidate, 'direction', 'LONG') or 'LONG').upper()
    raw_pat_type = str(md.get('pattern_type') or '')

    # 1. Identify active pattern from candidate
    primary_pat = rp_list[0] if rp_list else None
    pat_name_fa = str(primary_pat.get('name_fa') or '') if primary_pat else ''
    pat_type_str = (primary_pat or {}).get('type') or raw_pat_type or 'SPOTBREAK'
    pat_title = _map_pattern_title(pat_type_str, pat_name_fa)

    # 2. Determine frame start based on pattern anchor points (Live Market Focus)
    all_points = []
    if primary_pat and 'lines' in primary_pat:
        for l in primary_pat['lines']:
            all_points.extend(l.get('points', []))

    df_clean = df.copy().reset_index(drop=True)
    df_clean['ts_dt'] = pd.to_datetime(df_clean['timestamp'])

    # ── Viva 10-13 («هندسه/زوم/تعداد کندل از انجین جدید»): the R73 smart-zoom
    # core picks the window — pattern-anchor-driven candle count, width ≥75%,
    # height ≤65-70%, needle guard, box-top-inside law. V1 heuristics below
    # remain ONLY the fallback when the core declines (None).
    _plan75 = None
    try:
        from analysis.smart_zoom import solve_zoom as _sz75
        _plan75 = _sz75(df_clean, candidate,
                        patterns=[primary_pat] if primary_pat else None,
                        confirmed=confirmed, is_spot=True, chart_tf=tf,
                        det_n=len(df_clean))
    except Exception:
        _plan75 = None

    start_idx = 0
    if all_points:
        # 10-11 (G6): only IN-FRAME pivots anchor the zoom — a stale pivot
        # (e.g. a snapshot-locked ts the frame has moved past) must not
        # stretch the window; the zoom follows the visible pattern.
        try:
            _t0s = pd.to_datetime(df_clean['ts_dt'].iloc[0])
            _t1s = pd.to_datetime(df_clean['ts_dt'].iloc[-1])
            _bar73 = abs((_t1s - _t0s).total_seconds()) / max(1, len(df_clean) - 1)
            earliest_pts = _spot_earliest_inframe(all_points, _t0s, _t1s, _bar73)
        except Exception:
            earliest_pts = None
        if earliest_pts is not None:
            matches = df_clean.index[df_clean['ts_dt'] <= earliest_pts]
            if len(matches) > 0:
                first_pt_idx = matches[-1]
                # Viva 10-13 (his ruling 18): ~20 candles of context BEFORE
                # the pattern's first edge — never a squashed tape.
                start_idx = max(0, first_pt_idx - 20)

    # If start_idx leaves too few bars, ensure at least 45 bars; if too many, clamp to 180 max
    n_total = len(df_clean)
    if (n_total - start_idx) < 45:
        start_idx = max(0, n_total - 65)
    elif (n_total - start_idx) > 220:
        start_idx = max(0, n_total - 200)

    if _plan75 is not None:
        # pattern-driven count wins over every fixed/heuristic window
        start_idx = max(0, n_total - int(_plan75["n"]))
    else:
        # Viva 10-13 (his «تعداد کندل با توجه به پترن»): when the zoom core
        # declines (short tapes like 3d/1w), the window still follows the
        # pattern: anchor = earliest pivot ts, else the engine fit's x0.
        _a75 = None
        try:
            _ts75 = pd.to_datetime(df_clean['ts_dt'])
            for _l75 in (primary_pat or {}).get('lines', []) or []:
                for _pt75 in _l75.get('points', []) or []:
                    try:
                        _t75 = pd.to_datetime(_pt75.get('ts'))
                        _m75 = df_clean.index[_ts75 <= _t75]
                        if len(_m75):
                            _a75 = int(_m75[-1]) if _a75 is None else min(_a75, int(_m75[-1]))
                    except Exception:
                        continue
                _x075 = _l75.get('x0')
                if _a75 is None and _x075 is not None:
                    _a75 = max(0, min(n_total - 1, int(_x075)))
        except Exception:
            _a75 = None
        if _a75 is not None:
            _span75 = max(8, n_total - _a75)
            _nw75 = min(n_total, int(_span75 * 1.35) + 15)
            _nw75 = max(_nw75, 45)
            start_idx = max(0, n_total - _nw75)
    frame = df_clean.iloc[start_idx:].copy().reset_index(drop=True)
    n = len(frame)
    if n < 20:
        frame = df_clean.tail(min(n_total, 60)).copy().reset_index(drop=True)
        n = len(frame)

    highs = frame['high'].astype(float).values
    lows = frame['low'].astype(float).values
    opens = frame['open'].astype(float).values
    closes = frame['close'].astype(float).values
    timestamps = frame['ts_dt'].values
    live_price = float(closes[-1])

    # 3. Canvas setup with maximum width (Tight left/right margins)
    fig, ax = plt.subplots(figsize=(16, 9), dpi=180)
    plt.subplots_adjust(left=0.030, right=0.935, top=0.925, bottom=0.065)

    # Authentic Lemon-to-Sky Vertical Gradient
    top_rgb = np.array([253, 244, 159]) / 255.0  # #FDF49F
    bot_rgb = np.array([145, 203, 248]) / 255.0  # #91CBF8
    gradient = np.linspace(top_rgb, bot_rgb, 256).reshape(256, 1, 3)
    ax.imshow(gradient, aspect='auto', extent=[0, 1, 0, 1], origin='upper', zorder=0, transform=ax.transAxes)

    ax.set_yscale('log')
    # Viva 10-13 (his law #1): NO vertical/horizontal gridlines in the candle
    # background — not even faint ones. Clean gradient only.
    ax.grid(False, which='both')

    # 4. Draw Official Viva Signals Watermark in Center
    logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'vivasignals-logo.png')
    if os.path.isfile(logo_path):
        try:
            mark_ax = ax.inset_axes([0.38, 0.28, 0.24, 0.44], transform=ax.transAxes, zorder=1)
            mark_ax.imshow(mpimg.imread(logo_path), alpha=0.080)
            mark_ax.set_axis_off()
            mark_ax.patch.set_alpha(0)
        except Exception:
            pass

    # 5. Candlesticks (Emerald & Coral with substantial width)
    c_up = '#26A69A'
    c_dn = '#EF5350'
    width = 0.66
    for i in range(n):
        o, c, h, l = opens[i], closes[i], highs[i], lows[i]
        col = c_up if c >= o else c_dn
        ax.plot([i, i], [l, h], color=col, linewidth=1.2, zorder=3)
        rect = patches.Rectangle((i - width/2, min(o, c)), width, max(abs(c - o), 1e-6),
                                 facecolor=col, edgecolor=col, linewidth=0.8, zorder=4)
        ax.add_patch(rect)

    # 6. Draw EXACT pattern lines from candidate (Honest Geometry)
    # Viva 10-13 fault-fix («از هندسه خارج»): every drawn segment is CLIPPED
    # at the data window — a steep fit can never fly off the canvas again.
    _ymin_d73 = float(np.min(lows))
    _ymax_d73 = float(np.max(highs))
    # the WIDEST window section 7 can produce (cap branch = 1.07*1.28,
    # breakdown = 1.05 / 0.95-0.96) — clipping here means a line can never
    # cross the canvas edge on ANY branch.
    _plo = _ymin_d73 * 0.95
    _phi = _ymax_d73 * 1.45

    def _clipx(_sl, _ic, xa, xb):
        if _sl == 0:
            return xa, xb
        _x_hi = (math.log10(_phi) - _ic) / _sl
        _x_lo = (math.log10(_plo) - _ic) / _sl
        lo_x, hi_x = min(xa, xb), max(xa, xb)
        if _sl > 0:
            lo_x, hi_x = max(lo_x, _x_lo), min(hi_x, _x_hi)
        else:
            lo_x, hi_x = max(lo_x, _x_hi), min(hi_x, _x_lo)
        return lo_x, hi_x
    # 10-11 (G1): the ENGINE's calibrated line (log_fit keys, global x) is
    # drawn re-expressed in frame coords — the renderer never refits what
    # the engine validated. Legacy lines without fit keys keep the polyfit.
    future = _spot_future_bars(n)
    if _plan75 is not None:
        future = int(max(16, min(40, round(0.11 * n))))
    drawn_lines = []
    if primary_pat and 'lines' in primary_pat:
        for line_info in primary_pat['lines']:
            pts = line_info.get('points', []) or []
            # G2: pivots map by ts; out-of-frame ones are skipped (no snap).
            x_pts, y_pts = _spot_map_pivots(pts, list(frame['ts_dt']))
            slope_l = ic_l = None
            x_start = None
            _eng73 = _spot_engine_line_frame(line_info, start_idx)
            if _eng73 is not None:
                slope_l, ic_l, _x0f73 = _eng73
                x_start = max(0, min([_x0f73] + x_pts)) if x_pts else max(0, _x0f73)
            elif len(x_pts) >= 2 and max(x_pts) > min(x_pts):
                # Legacy metadata without fit keys: fit in log10 space.
                log_ys = np.log10(np.clip(y_pts, 1e-12, None))
                slope_l, ic_l = np.polyfit(x_pts, log_ys, 1)
                slope_l, ic_l = float(slope_l), float(ic_l)
                x_start = max(0, min(x_pts))
            if slope_l is None or x_start is None:
                continue
            # ── Viva 10-13 fault-fix («یک خط له شده ته چارت»): SOLID paint
            # stops at the line's OWN last pivot unless the line is still
            # alive at the live price (within 15%); beyond that only the
            # dashed projection. A stale steep leg can no longer be
            # extrapolated through the tape to the live bar.
            _y_live73 = 10.0 ** (slope_l * (n - 1) + ic_l)
            # 8%: a leg extrapolated far from the live price is STALE, not
            # alive (14%-below-live flag poles were passing at 15%).
            _alive73 = abs(_y_live73 - live_price) / max(1e-12, live_price) <= 0.08
            _x1_73 = float(max(x_pts)) if x_pts else float(n - 1)
            _x_solid73 = float(n - 1) if _alive73 else min(_x1_73, float(n - 1))
            # 10-13: a solid leg may never dive out of the visible window —
            # stop it where it crosses the window edge; beyond = dashed only.
            try:
                _lo75 = float(_plan75["y_lo"]) if _plan75 is not None else float(np.min(lows)) * 0.99
                _hi75 = float(_plan75["y_hi"]) if _plan75 is not None else float(np.max(highs)) * 1.01
                if slope_l < 0:
                    _xex75 = (math.log10(_lo75) - ic_l) / slope_l
                elif slope_l > 0:
                    _xex75 = (math.log10(_hi75) - ic_l) / slope_l
                else:
                    _xex75 = float(n - 1)
                _x_solid73 = min(_x_solid73, max(0.0, _xex75))
            except Exception:
                pass
            # Solid segment across pattern span (clipped to the window)
            _sa, _sb = _clipx(slope_l, ic_l, x_start, _x_solid73)
            if _sb > _sa:
                xs_solid = np.linspace(_sa, _sb, 100)
                ys_solid = 10.0 ** (slope_l * xs_solid + ic_l)
                ax.plot(xs_solid, ys_solid, color='#1F2328', linewidth=2.0, zorder=5)

            # Projection dashed segment beyond the solid end (clipped too)
            _da, _db = _clipx(slope_l, ic_l, _x_solid73, n + future - 4)
            if _db > _da + 0.5:
                xs_proj = np.linspace(_da, _db, 40)
                ys_proj = 10.0 ** (slope_l * xs_proj + ic_l)
                ax.plot(xs_proj, ys_proj, color='#1F2328', linewidth=1.4, linestyle=(0, (5, 3)), alpha=0.75, zorder=5)

            # Scatter pivot touch points
            for px, py in zip(x_pts, y_pts):
                ax.scatter(px, py, s=36, facecolor='#FDF49F', edgecolor='#1F2328', linewidth=1.3, zorder=6)

            drawn_lines.append({'slope': float(slope_l), 'intercept': float(ic_l),
                                'side': line_info.get('side'),
                                'x1': float(max(x_pts)) if x_pts else float(n - 1)})

    # If no lines in metadata (fallback to adaptive fit)
    if not drawn_lines:
        pk_idx = int(np.argmax(highs[:max(5, n//3)]))
        lo_idx = int(np.argmin(lows[:max(5, n//3)]))
        slope_u = (np.log10(highs[-2]) - np.log10(highs[pk_idx])) / max(1, (n - 2 - pk_idx))
        ic_u = np.log10(highs[pk_idx]) - slope_u * pk_idx
        _ua, _ub = _clipx(slope_u, ic_u, pk_idx, n + future - 4)
        if _ub > _ua:
            xs_u = np.linspace(_ua, _ub, 100)
            ax.plot(xs_u, 10.0 ** (slope_u * xs_u + ic_u), color='#1F2328', linewidth=1.8, zorder=5)

    # 7. Measured Move Box or Breakdown Marker
    # Only draw bullish target box if it is actually a bullish setup or confirmation!
    is_breakdown = _spot_is_breakdown(stage, getattr(candidate, "direction", "LONG"))
    
    y_min_data = float(np.min(lows))
    y_max_data = float(np.max(highs))
    
    if not is_breakdown and (confirmed or 'BREAK_UP' in stage or 'TOUCH' in stage or 'NEAR_BREAK' in stage):
        # Calculate target from upper line or pattern height
        # Viva 10-13 fault-fix: the box sits on the shape's UPPER EDGE at the
        # edge's own last pivot (or live, whichever is higher) — NEVER on a
        # steep leg extrapolated to the live bar (that minted the giant
        # +66% box over a bull-flag pole).
        upper_level = live_price * 1.02
        if drawn_lines:
            up_cand = [ln for ln in drawn_lines if ln.get('side') == 'HIGH']
            if up_cand:
                _u73 = up_cand[0]
                _xe73 = min(float(n - 1), float(_u73.get('x1', n - 1)))
                upper_level = max(live_price * 0.999,
                                  float(10.0 ** (_u73['slope'] * _xe73 + _u73['intercept'])))
        
        # 10-10: ceiling-first box (the alert builder's md value wins;
        # confirms recompute from the visible frame; virgin air → TF size).
        try:
            _ceil73s = float(md.get("spot_box_top") or 0.0)
        except Exception:
            _ceil73s = 0.0
        if not (_ceil73s > upper_level * 1.005):
            try:
                from analysis.spot_engine import _structural_high_above as _sha73
                _rc73s = _sha73(frame, float(frame["close"].iloc[-1])) or 0.0
                if float(_rc73s) > upper_level * 1.005:
                    _ceil73s = float(_rc73s) * 1.01  # «کمی بالاترش»
            except Exception:
                pass
        target_price = _spot_box_target(upper_level, tf, _ceil73s)
        delta_p = target_price - upper_level
        pct_gain = (delta_p / max(1e-6, upper_level)) * 100.0

        # Viva 10-13 (refs): the green box RISES FROM THE LIVE PRICE — bottom
        # edge on the live line, top edge at the target; it never floats.
        _blo75 = float(live_price)
        if target_price <= _blo75 * 1.001:
            target_price = _blo75 * 1.05
        # Viva 10-13: the box top (and its % label) NEVER leaves the canvas —
        # cap at the window top the smart-zoom core reserved for it.
        _cap75 = (float(_plan75["y_hi"]) * 0.985) if _plan75 is not None \
            else y_max_data * 1.30
        if target_price > _cap75:
            target_price = _cap75
        delta_p = target_price - _blo75
        pct_gain = (delta_p / max(1e-6, _blo75)) * 100.0
        bx0 = n - 1
        bx1 = n + future - 4   # 10-11: box spans the future tail (24→n+20, as before)
        bw = bx1 - bx0
        ax.hlines(_blo75, bx0, bx1, colors='#1F2328', linewidth=1.4, zorder=6)
        rect_box = patches.Rectangle((bx0, _blo75), bw, target_price - _blo75,
                                     facecolor='#A8D49B', edgecolor='#388E3C',
                                     linewidth=1.2, alpha=0.60, zorder=5)
        ax.add_patch(rect_box)
        arrow_x = bx0 + bw * 0.5
        ax.annotate('', xy=(arrow_x, target_price), xytext=(arrow_x, _blo75),
                    arrowprops=dict(arrowstyle='->', color='#1F2328', lw=1.5, mutation_scale=12), zorder=7)
        # R72 cosmetic law: thousands-separated decimals, never scientific
        _dtxt73 = (f'{delta_p:,.4f}'.rstrip('0').rstrip('.')
                   if delta_p < 10 else f'{delta_p:,.0f}')
        label_text = f'{_dtxt73} (+{pct_gain:.2f}%)'
        # 10-12 (his GEO rule: candles must NEVER squash): near boxes
        # (top within 1.35x data top) still fit whole (refs unchanged);
        # far boxes run off-canvas (auto-clipped) with the % label pinned
        # at the top edge.
        _clip73b = bool(target_price > y_max_data * 1.35)
        _cap73b = y_max_data * 1.07 * 1.28
        _ly73b = _cap73b * 0.995 if _clip73b else target_price * 1.018
        ax.text(arrow_x, _ly73b, label_text,
                color='#1F2328', fontsize=9.2, fontweight='bold', ha='center',
                va='top' if _clip73b else 'bottom', zorder=8)
        y_max = _cap73b if _clip73b else max(y_max_data, target_price) * 1.07
        y_min = y_min_data * 0.96
    else:
        # For breakdowns or warning: no fake long target box!
        y_max = y_max_data * 1.05
        y_min = y_min_data * 0.95

    if _plan75 is not None:
        y_min = float(_plan75["y_lo"])
        y_max = float(_plan75["y_hi"])
    ax.set_ylim(y_min, y_max)
    ax.set_xlim(-1.0, n + future)
    # ── Viva 10-13 fault-fix, exact pass: AFTER the final window is known,
    # no ink segment may cross the canvas — trim every pattern line to the
    # visible band (the provisional clip in section 6 only guards the wild
    # cases; this one is pixel-exact against the real ylim).
    for _ln73 in list(ax.lines):
        try:
            if str(_ln73.get_color()).lower() != '#1f2328':
                continue
            _xd73, _yd73 = _ln73.get_data()
            _xd73 = np.asarray(_xd73, float)
            _yd73 = np.asarray(_yd73, float)
            _m73 = (_yd73 >= y_min) & (_yd73 <= y_max)
            if _m73.all():
                continue
            if not _m73.any():
                _ln73.remove()
                continue
            _ln73.set_data(_xd73[_m73], _yd73[_m73])
        except Exception:
            pass

    # 8. Live Price Guide & Single Distinct Live Price Pill on Axis
    ax.axhline(live_price, color='#1F2328', linestyle=':', linewidth=1.1, alpha=0.60, zorder=6)
    fmt_live = f'{live_price:,.4g}' if live_price < 10 else f'{live_price:,.2f}'
    ax.text(n + future - 0.2, live_price, f' {fmt_live} ',
            color='#FFFFFF', fontsize=9.5, fontweight='bold', va='center', ha='left',
            bbox=dict(boxstyle='square,pad=0.25', facecolor='#1F2328', edgecolor='#D5D0C5', lw=0.9),
            zorder=9)

    # 9. Tehran Live Clock & Time Axis
    try:
        tehran_now = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%d %b %Y • %H:%M")
        ax.text(n - 1, y_min * 1.012, f'LIVE: {tehran_now} (Tehran)',
                color='#1F2328', fontsize=8.5, fontweight='bold', ha='right', va='bottom',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#FDF49F', edgecolor='#8A857D', alpha=0.85),
                zorder=9)
    except Exception:
        pass

    # 10. Clean Header Information matching Telegram Alert
    sub_title = f'{stage.replace("_", " ")} • {pat_title} • Log Scale'
    fig.text(0.038, 0.955, f'{symbol}  •  {tf.upper()}  •  SPOTBREAK', fontsize=15, fontweight='bold', color='#1F2328')
    fig.text(0.038, 0.932, f'VIVA SIGNALS PRO  •  {sub_title}', fontsize=10.5, color='#4A4640')

    # 11. Bottom-Right Official Brand & Golden Badge
    brand_name = 'VIVA SIGNALS PRO'
    if os.path.isfile(logo_path):
        try:
            b_ax = fig.add_axes([0.895, 0.022, 0.032, 0.038], zorder=10)
            b_ax.imshow(mpimg.imread(logo_path), alpha=0.90)
            b_ax.axis('off')
            fig.text(0.890, 0.038, brand_name, fontsize=12, fontweight='bold', color='#1F2328', ha='right', va='center')
        except Exception:
            fig.text(0.93, 0.038, brand_name, fontsize=12, fontweight='bold', color='#1F2328', ha='right', va='center')
    else:
        fig.text(0.93, 0.038, brand_name, fontsize=12, fontweight='bold', color='#1F2328', ha='right', va='center')

    # 12. Axis Formatting (No Colliding Numbers)
    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_color('#8A857D')
    ax.spines['bottom'].set_color('#8A857D')
    ax.tick_params(colors='#4A4640', labelsize=9.5)
    ax.yaxis.tick_right()

    step = max(15, n // 6)
    pos_list = list(range(5, n, step))
    labels = [pd.to_datetime(timestamps[p]).strftime('%b %d') for p in pos_list]
    ax.set_xticks(pos_list)
    ax.set_xticklabels(labels, fontsize=9.5, color='#4A4640')

    # 10-12 (his axis law: MORE price labels on EVERY spot chart, every TF):
    # LogLocator(subs) density depends on the matplotlib VERSION (proven:
    # sparse {10} on old-mpl, dense on new-mpl for the SAME code) — so
    # sub-1.5-decade views now take EXPLICIT linear-nice ticks (his beloved
    # ONDO density; FixedLocator = identical on every mpl); wider views
    # keep log subs='all'.
    try:
        _lo73a = float(ax.get_ylim()[0])
        _hi73a = float(ax.get_ylim()[1])
        _dec73a = math.log10(_hi73a) - math.log10(_lo73a)
        # version-proof subs census (tick_values itself delegates on
        # new-mpl): pure arithmetic over subs x decades inside the view.
        _in73a = []
        _e073a = int(math.floor(math.log10(_lo73a)))
        _e173a = int(math.ceil(math.log10(_hi73a)))
        for _e73a in range(_e073a - 1, _e173a + 2):
            for _s73a in (1.0, 1.5, 2.0, 3.0, 5.0, 7.0):
                _t73a = _s73a * (10.0 ** _e73a)
                if _lo73a <= _t73a <= _hi73a:
                    _in73a.append(_t73a)
    except Exception:
        _dec73a, _in73a = 99.0, []
    if _dec73a >= 1.5 or len(_in73a) >= 7:
        ax.yaxis.set_major_locator(LogLocator(base=10.0, subs="all", numticks=20))
    else:
        try:
            _lin73a = [t for t in MaxNLocator(nbins=9, min_n_ticks=7).tick_values(_lo73a, _hi73a)
                       if _lo73a <= t <= _hi73a]
        except Exception:
            _lin73a = []
        if len(_lin73a) >= 2:
            ax.yaxis.set_major_locator(FixedLocator(_lin73a))
        elif _in73a:
            ax.yaxis.set_major_locator(FixedLocator(_in73a))
        else:
            ax.yaxis.set_major_locator(LogLocator(base=10.0, subs="all", numticks=20))
    def price_fmt(x, _):
        if x <= 0: return ''
        if abs(x - live_price) / live_price < 0.035:
            return ''  # Hide tick label if too close to live price pill to avoid collision!
        if x >= 1000: return f'{x:,.0f}'
        elif x >= 10: return f'{x:,.1f}'
        elif x >= 1: return f'{x:.2f}'
        elif x >= 0.01: return f'{x:.4f}'
        else: return f'{x:.6f}'
    ax.yaxis.set_major_formatter(FuncFormatter(price_fmt))
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda x, _: ''))

    buf = io.BytesIO()
    # Viva 10-13 law #1, belt-and-braces: NO gridline on ANY axis (price,
    # volume, anything a future pane adds), regardless of rcParams state.
    for _ax75g in fig.axes:
        _ax75g.grid(False, which='both')
    plt.savefig(buf, format='png', facecolor='#FDF49F', edgecolor='none')
    plt.close()
    buf.seek(0)
    return buf.read()
