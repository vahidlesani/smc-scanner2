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
from matplotlib.ticker import FuncFormatter, LogLocator


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
    pat_type_str = primary_pat.get('type') or raw_pat_type or 'SPOTBREAK'
    pat_title = _map_pattern_title(pat_type_str, pat_name_fa)

    # 2. Viva 10-09 NEED-FIRST window (shared analysis/chart_window ruler):
    # two-sided shapes show the FULL body; single lines show from the
    # second-to-last touch (fossil first touch projects). No cap, 45 floor.
    from analysis.chart_window import (need_start as _need_start,
                                       live_block_for_tf as _lbtf,
                                       ref_touch as _ref_touch,
                                       is_two_sided as _is_two)
    df_clean = df.copy().reset_index(drop=True)
    df_clean['ts_dt'] = pd.to_datetime(df_clean['timestamp'])
    n_total = len(df_clean)
    _two_spot = _is_two(str((primary_pat or {}).get('shape') or 'single'))
    _refs_spot = []
    if primary_pat and 'lines' in primary_pat:
        for _l in primary_pat['lines']:
            _pick = _ref_touch(list(_l.get('points', []) or []), _two_spot)
            if _pick is not None and str(_pick.get('ts') or ''):
                try:
                    _pt = pd.to_datetime(_pick['ts'])
                    _m = df_clean.index[df_clean['ts_dt'] <= _pt]
                    if len(_m) > 0:
                        _refs_spot.append(int(_m[-1]))
                except Exception:
                    pass
    start_idx = _need_start(n_total, _refs_spot, _lbtf(tf))
    # Viva 10-09 STABILITY: second-edge pivots are picked on the FULL frame
    # (never the window) so geometry cannot shift with the count; window
    # coords are derived by subtracting start_idx at draw time.
    _pre_pick = {}
    try:
        _N_c = len(df_clean)
        _H_c = df_clean['high'].astype(float).to_numpy()
        _L_c = df_clean['low'].astype(float).to_numpy()
        _O_c = df_clean['open'].astype(float).to_numpy()
        _C_c = df_clean['close'].astype(float).to_numpy()
        _med_base = np.maximum(np.maximum(_H_c - np.maximum(_O_c, _C_c), 0.0),
                               np.maximum(np.minimum(_O_c, _C_c) - _L_c, 0.0))
        _med_c = float(np.median(_med_base)) if _N_c else 0.0
        _atr_c = float(np.mean(_H_c - _L_c)) if _N_c else 0.0
        _cut_c = max(2.5 * _med_c, 0.8 * _atr_c)
        for _side_c, _targ_c in (('LOW', _L_c), ('HIGH', _H_c)):
            _bod_c = np.minimum(_O_c, _C_c) if _side_c == 'LOW' else np.maximum(_O_c, _C_c)
            _w_c = (_bod_c - _targ_c) if _side_c == 'LOW' else (_targ_c - _bod_c)
            _pk_c = np.where(_w_c > _cut_c, _bod_c, _targ_c)
            _h_c = max(1, _N_c // 2)
            if _side_c == 'LOW':
                _q1 = int(np.argmin(_pk_c[:_h_c])); _q2 = _h_c + int(np.argmin(_pk_c[_h_c:]))
            else:
                _q1 = int(np.argmax(_pk_c[:_h_c])); _q2 = _h_c + int(np.argmax(_pk_c[_h_c:]))
            _pre_pick[_side_c] = (_q1, _q2, _pk_c)
    except Exception as _pre_exc:
        print(f'Spot pre-window pivot pick warning: {_pre_exc}')
        _pre_pick = {}
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
    # Viva 10-09 quality law: 240 DPI like the spike renderer (his second
    # «کیفیت چارت» demand) — one resolution everywhere, no per-engine blur.
    fig, ax = plt.subplots(figsize=(16, 9), dpi=int(os.getenv("CHART_DPI", "240") or 240))
    try:  # 10-09 crash law: the figure ALWAYS closes (finally)
        plt.subplots_adjust(left=0.030, right=0.935, top=0.925, bottom=0.065)

        # Authentic Lemon-to-Sky Vertical Gradient
        top_rgb = np.array([253, 244, 159]) / 255.0  # #FDF49F
        bot_rgb = np.array([145, 203, 248]) / 255.0  # #91CBF8
        gradient = np.linspace(top_rgb, bot_rgb, 256).reshape(256, 1, 3)
        ax.imshow(gradient, aspect='auto', extent=[0, 1, 0, 1], origin='upper', zorder=0, transform=ax.transAxes)

        ax.set_yscale('log')
        ax.grid(True, which='both', color='#D5D0C5', linestyle='-', linewidth=0.5, alpha=0.35)

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
        future = 24
        drawn_lines = []
        if primary_pat and 'lines' in primary_pat:
            for line_info in primary_pat['lines']:
                pts = line_info.get('points', [])
                if len(pts) >= 2:
                    # Map timestamp points to current frame x-coordinates
                    x_pts = []
                    y_pts = []
                    for pt in pts:
                        pt_dt = pd.to_datetime(pt['ts'])
                        diffs = np.abs([(t - pt_dt).total_seconds() for t in frame['ts_dt']])
                        best_match_idx = int(np.argmin(diffs))
                        x_pts.append(best_match_idx)
                        y_pts.append(float(pt['price']))

                    # Fit line in log10 space
                    log_ys = np.log10(np.clip(y_pts, 1e-12, None))
                    if max(x_pts) > min(x_pts):
                        slope_l, ic_l = np.polyfit(x_pts, log_ys, 1)
                        x_start = max(0, min(x_pts))
                    
                        # Solid segment across pattern span
                        xs_solid = np.linspace(x_start, n - 1, 100)
                        ys_solid = 10.0 ** (slope_l * xs_solid + ic_l)
                        ax.plot(xs_solid, ys_solid, color='#1F2328', linewidth=2.0, zorder=5)

                        # Projection dashed segment into future
                        xs_proj = np.linspace(n - 1, n + future - 4, 40)
                        ys_proj = 10.0 ** (slope_l * xs_proj + ic_l)
                        ax.plot(xs_proj, ys_proj, color='#1F2328', linewidth=1.4, linestyle=(0, (5, 3)), alpha=0.75, zorder=5)
                    
                        # Scatter pivot touch points
                        for px, py in zip(x_pts, y_pts):
                            ax.scatter(px, py, s=36, facecolor='#FDF49F', edgecolor='#1F2328', linewidth=1.3, zorder=6)
                    
                        drawn_lines.append({'slope': slope_l, 'intercept': ic_l, 'side': line_info.get('side')})

        # Viva Both-Edges Law: If pattern is a triangle/channel/wedge and only 1 edge exists, fit the complementary edge!
        _two_side_pats = ('TRIANGLE', 'WEDGE', 'CHANNEL', 'مثلث', 'کانال', 'گوه')
        _is_two_sided = any(k in str(pat_title).upper() or k in str(pat_name_fa) for k in _two_side_pats)
        if drawn_lines and len(drawn_lines) == 1 and _is_two_sided:
            try:
                _existing_side = str(drawn_lines[0].get('side') or '').upper()
                _need_side = 'LOW' if _existing_side == 'HIGH' else 'HIGH'
                # Viva 10-09 STABILITY: pivots come from the FULL-frame
                # pre-pick (never the window) — same pivots at any count.
                _pre = _pre_pick.get(_need_side)
                if _pre is not None:
                    _q1, _q2, _pk_c = _pre
                    _p1, _p2 = _q1 - start_idx, _q2 - start_idx
                    _tv1, _tv2 = float(_pk_c[_q1]), float(_pk_c[_q2])
                else:
                    _p1, _p2, _tv1, _tv2 = 0, 0, 0.0, 0.0
                if _p2 > _p1 and _tv1 > 0 and _tv2 > 0:
                    _sl2 = (np.log10(_tv2) - np.log10(_tv1)) / (_p2 - _p1)
                    _ic2 = np.log10(_tv1) - _sl2 * _p1
                    _xs2 = np.linspace(_p1, n - 1, 80)
                    ax.plot(_xs2, 10.0 ** (_sl2 * _xs2 + _ic2), color='#1F2328', linewidth=2.0, zorder=5)
                    _xs2_p = np.linspace(n - 1, n + future - 4, 30)
                    ax.plot(_xs2_p, 10.0 ** (_sl2 * _xs2_p + _ic2), color='#1F2328', linewidth=1.4, linestyle=(0, (5, 3)), alpha=0.75, zorder=5)
                    ax.scatter([_p1, _p2], [_tv1, _tv2], s=36, facecolor='#FDF49F', edgecolor='#1F2328', linewidth=1.3, zorder=6)
                    drawn_lines.append({'slope': _sl2, 'intercept': _ic2, 'side': _need_side})
            except Exception as _e_both_spot:
                print(f'Spot both edges fit warning: {_e_both_spot}')

        # If no lines in metadata (fallback to adaptive fit)
        if not drawn_lines:
            pk_idx = int(np.argmax(highs[:max(5, n//3)]))
            lo_idx = int(np.argmin(lows[:max(5, n//3)]))
            slope_u = (np.log10(highs[-2]) - np.log10(highs[pk_idx])) / max(1, (n - 2 - pk_idx))
            ic_u = np.log10(highs[pk_idx]) - slope_u * pk_idx
            xs_u = np.linspace(pk_idx, n + future - 4, 100)
            ax.plot(xs_u, 10.0 ** (slope_u * xs_u + ic_u), color='#1F2328', linewidth=1.8, zorder=5)

        # 7. Measured Move Box or Breakdown Marker
        # Only draw bullish target box if it is actually a bullish setup or confirmation!
        is_breakdown = 'BREAK_DOWN' in stage or 'نزولی' in pat_name_fa or 'BEAR' in pat_type_str
    
        y_min_data = float(np.min(lows))
        y_max_data = float(np.max(highs))

        _box_top = 0.0
        _box_drawn = False
        if not is_breakdown and (confirmed or 'BREAK_UP' in stage or 'TOUCH' in stage or 'NEAR_BREAK' in stage):
            # Viva TP Law 2026-10-08 (his CryptoCove verdict): a CONFIRMED chart
            # draws the REAL ladder box — entry → path end (runner), with the
            # TP1/TP2/TP3 rungs at 40/50/60% inside. Alerts (no ladder yet) keep
            # the measured +25% projection box.
            _lad = (md.get('target_ladder') or {})
            try:
                _tps = [float(x) for x in (_lad.get('targets') or []) if float(x or 0) > 0][:3]
            except Exception:
                _tps = []
            try:
                _run = float(_lad.get('runner') or 0.0)
            except Exception:
                _run = 0.0
            try:
                _entry = float(getattr(candidate, 'planned_entry', 0.0) or 0.0) or live_price
            except Exception:
                _entry = live_price
            bx0 = n - 1
            bx1 = n + 20
            bw = bx1 - bx0
            if confirmed and len(_tps) == 3 and _run > _entry > 0:
                box_lo, box_hi = _entry, _run
                ax.hlines(box_lo, bx0, bx1, colors='#1F2328', linewidth=1.4, zorder=6)
                rect_box = patches.Rectangle((bx0, box_lo), bw, box_hi - box_lo,
                                             facecolor='#A8D49B', edgecolor='#388E3C',
                                             linewidth=1.2, alpha=0.60, zorder=5)
                ax.add_patch(rect_box)
                for _ti, _tv in enumerate(_tps, start=1):
                    ax.hlines(_tv, bx0, bx1, colors='#2E7D32', linewidth=1.1,
                              linestyle=(0, (4, 3)), zorder=6)
                    ax.text(bx1 + 0.3, _tv, f'TP{_ti}',
                            color='#1F2328', fontsize=8.2, fontweight='bold',
                            ha='left', va='center', zorder=8)
                ax.text(bx1 + 0.3, box_hi, 'HOLD 10%',
                        color='#1F2328', fontsize=8.2, fontweight='bold',
                        ha='left', va='center', zorder=8)
                arrow_x = bx0 + bw * 0.5
                ax.annotate('', xy=(arrow_x, box_hi), xytext=(arrow_x, box_lo),
                            arrowprops=dict(arrowstyle='->', color='#1F2328', lw=1.5, mutation_scale=12), zorder=7)
                _pct = (box_hi - box_lo) / max(1e-12, box_lo) * 100.0
                ax.text(arrow_x, box_hi * 1.018, f'+{_pct:.1f}%',
                        color='#1F2328', fontsize=9.2, fontweight='bold', ha='center', va='bottom', zorder=8)
                _box_top = box_hi
                _box_drawn = True
            else:
                # Alert projection: measured +25% above the live edge.
                upper_level = live_price * 1.05
                if drawn_lines:
                    up_cand = [ln for ln in drawn_lines if ln.get('side') == 'HIGH']
                    if up_cand:
                        upper_level = float(10.0 ** (up_cand[0]['slope'] * (n - 1) + up_cand[0]['intercept']))

                target_price = upper_level * 1.25
                delta_p = target_price - upper_level
                pct_gain = (delta_p / max(1e-6, upper_level)) * 100.0

                ax.hlines(upper_level, bx0, bx1, colors='#1F2328', linewidth=1.4, zorder=6)
                rect_box = patches.Rectangle((bx0, upper_level), bw, target_price - upper_level,
                                             facecolor='#A8D49B', edgecolor='#388E3C',
                                             linewidth=1.2, alpha=0.60, zorder=5)
                ax.add_patch(rect_box)
                arrow_x = bx0 + bw * 0.5
                ax.annotate('', xy=(arrow_x, target_price), xytext=(arrow_x, upper_level),
                            arrowprops=dict(arrowstyle='->', color='#1F2328', lw=1.5, mutation_scale=12), zorder=7)
                ax.text(arrow_x, target_price * 1.018, f'+{pct_gain:.1f}%',
                        color='#1F2328', fontsize=9.2, fontweight='bold', ha='center', va='bottom', zorder=8)
                _box_top = target_price
                _box_drawn = True

        # Viva Law 2026-10-08 (his «اسکرول کن روی محور قیمت» + 16-mehr «اونهایی
        # که اسپایک در چارت نیست رو هم کوتاه کردی»): the y-window frames the
        # LIVE region (recent block + live edge values + box) ONLY when fossil
        # extremes actually drag the axis (whole-frame log span ≥ 2× the live
        # log span). Clean charts keep the whole frame with tight pads — the
        # old ×1.20/×0.85 fat pads died here. Lines still project; candles stay
        # readable; nothing overlayed ever clips.
        # Viva 10-09 LIVE-FOCUS (the same law as _smart_y_window; his BTC 4h
        # squash + ADA/DOGE steep slopes die here): the y-window frames the
        # LIVE block — recent candles + live price + the trade box IN FULL, so
        # live candles fill ~2/3 of the panel. Drawn-line edge values are
        # EXCLUDED from the fit — projecting lines may run off-panel exactly
        # like his GoCharting refs; including fossil-anchored edges was the
        # drag that stretched the axis. Fossil candles get a SOFT reach
        # (1.0× the live log-span); the 10-08 drag-gate and the fat pads are
        # SUPERSEDED — no gate, no floor, no fossil veto.
        try:
            from analysis.chart_window import live_block_for_tf as _lbtf1009s
            _live_n = max(20, int(_lbtf1009s(tf)))
        except Exception:
            _live_n = 60
        _live_n = min(_live_n, n)
        _r_hi = float(np.max(highs[-_live_n:]))
        _r_lo = float(np.min(lows[-_live_n:]))
        _fit_hi, _fit_lo = _r_hi, _r_lo
        if live_price > 0:
            _fit_hi = max(_fit_hi, live_price)
            _fit_lo = min(_fit_lo, live_price)
        if _box_top > 0:  # the trade box is never clipped
            _fit_hi = max(_fit_hi, _box_top)
        _live_span = max(math.log10(max(_fit_hi, 1e-12) / max(_fit_lo, 1e-12)), 1e-9)
        _mid = math.sqrt(max(_fit_hi, 1e-12) * max(_fit_lo, 1e-12))
        _half = 0.5 * _live_span / 0.62
        y_max = _mid * (10.0 ** _half)
        y_min = _mid / (10.0 ** _half)
        _reach = 1.0 * _live_span
        _flo = min(max(y_min_data, _mid / (10.0 ** _reach)), _fit_lo)
        _fhi = max(min(y_max_data, _mid * (10.0 ** _reach)), _fit_hi)
        y_min = min(y_min, _flo)
        y_max = max(y_max, _fhi)
        if _box_top > 0:
            y_max = max(y_max, _box_top)

        ax.set_ylim(y_min, y_max)
        ax.set_xlim(-1.0, n + future)

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

        ax.yaxis.set_major_locator(LogLocator(base=10.0, subs=(1.0, 1.5, 2.0, 3.0, 5.0, 7.0)))
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
        plt.savefig(buf, format='png', facecolor='#FDF49F', edgecolor='none')
        plt.close()
        buf.seek(0)
        return buf.read()
    finally:
        try:  # exception-path figure leak plugged (each ~21MB toward OOM)
            plt.close(fig)
        except Exception:
            pass
