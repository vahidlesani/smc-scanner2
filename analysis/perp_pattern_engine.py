"""
Dedicated Pattern & Trade-Tool Engine for PERP (پرپچوآل) Charts — V2 (10-13).
Viva 10-13: «الان ساختی واسه اسپات و باید برای پرپچوآل هم بسازی» — the same
new-engine geometry core the spot V2 renderer got, now for perpetual charts
in HIS white/cream VIVA style:

  * window + y-band from the R73 smart-zoom solver WITH the trade tool
    (entry/sl/tp ladder) inside the budget — fill ≤ 0.70, right gap ≤ 0.20;
  * locked geometry ONLY (candidate metadata, snapshot-locked — never a
    re-fit), pivot-faithful: solid to the last pivot unless the line is
    alive at live price, dashed projection beyond, converging pairs END AT
    THEIR APEX, EVERY segment CLIPPED at the y-window (no off-canvas flight);
  * trade tools: POI/ENTRY band, FIRST STOP, numbered TP pills 1/2/3 in the
    right margin (never over candles), faint zone fills with edge names;
  * chrome batch: 3-line TradingView header with OHLC, 34-tick geometric
    ladder, slim 0.11·n band, pink live cell + Tehran HH:MM:SS, dark LIVE
    stamp under the youngest candle, his center watermark + footer gold
    logo, candle-body edges, volume panel, 240 dpi.
Exception-only fallback to the unified mplfinance pass stays in messages_v7.
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
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.image as mpimg
from matplotlib.ticker import FuncFormatter, FixedLocator, NullFormatter

def _price_fmt(x, _pos=None):
    if x is None or not np.isfinite(x) or x <= 0:
        return ""
    if x >= 1000:
        return f"{x:,.0f}"
    if x >= 10:
        return f"{x:,.1f}"
    if x >= 1:
        return f"{x:,.2f}"
    if x >= 0.01:
        return f"{x:,.4f}"
    return f"{x:,.6f}"

LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "assets", "vivasignals-logo.png")
BG = "#F6F1E7"
INK = "#26221C"
RED, GREEN = "#C43B4B", "#177E6C"
PINK_BG, PINK_FG = "#F6A9C4", "#7E1030"
ZONE_FA = {"above": "#E8A9A9", "below": "#A9CDB0"}


def _edge_of(col: str) -> str:
    rgb = matplotlib.colors.to_rgb(col)
    return "#" + "".join(f"{int(max(0, ch * 0.68) * 255):02x}" for ch in rgb)


def render_viva_perp_chart(df: pd.DataFrame, candidate, confirmed: bool = False) -> bytes:
    symbol = str(getattr(candidate, "symbol", "") or "UNKNOWN").upper()
    md = getattr(candidate, "metadata", None) or {}
    tf = str(md.get("chart_view_tf") or getattr(candidate, "trigger_timeframe", "1h") or "1h").lower()
    if df is None or len(df) < 25:
        return b""
    work = df.copy()
    if "timestamp" not in work.columns:
        work = work.reset_index()
    work["ts_dt"] = pd.to_datetime(work["timestamp"])

    # ── 0) Viva 10-13: «تعداد کندل‌ها در پرپچوآل باید نزدیک‌ترین پترن باشه به
    # قیمت» — when several locked patterns ride the metadata, the ONE nearest
    # to the live price is the chart's subject; the window then covers it
    # plus ~20 candles of context before its first edge.
    _LEV_BY_TF = {"15m": 5, "30m": 5, "1h": 5, "2h": 4, "4h": 3,
                  "8h": 3, "12h": 2, "1d": 2}
    _tr75 = float(md.get("trailing_stop") or md.get("trail_stop") or 0)
    rp_all = md.get("render_patterns") or []
    if len(rp_all) > 1:
        def _last_ts75(pat):
            mx = 0
            for ln in (pat.get("lines") or []):
                for pt in (ln.get("points") or []):
                    try:
                        mx = max(mx, pd.Timestamp(str(pt.get("ts"))).value)
                    except Exception:
                        pass
            return mx
        rp_all = sorted(rp_all, key=_last_ts75, reverse=True)
    _near_pat = rp_all[0] if rp_all else None
    _need_n = 0
    if _near_pat is not None:
        try:
            _wts = pd.to_datetime(work["ts_dt"]).to_numpy()
            _xs75 = []
            for ln in (_near_pat.get("lines") or []):
                for pt in (ln.get("points") or []):
                    xv = float(np.searchsorted(_wts, np.datetime64(pd.Timestamp(str(pt.get("ts"))))))
                    _xs75.append(xv)
            if _xs75:
                _first75, _last75 = min(_xs75), max(_xs75)
                _need_n = int(max(len(work) - 1 - _first75 + 20,
                                  len(work) - 1 - _last75 + 25))
        except Exception:
            _need_n = 0

    # ── 1) R73 window with the trade tool inside the budget ────────────────
    n = y_lo = y_hi = None
    try:
        from analysis.smart_zoom import solve_zoom
        from analysis.candle_counts import candle_count
        plan = solve_zoom(work, candidate, confirmed=bool(confirmed),
                          is_spot=False, chart_tf=tf,
                          det_n=int(candle_count(tf, 300)))
        if plan:
            n = int(max(40, min(int(plan["n"]), len(work))))
            y_lo, y_hi = float(plan["y_lo"]), float(plan["y_hi"])
    except Exception as exc:
        print(f"perp v2 zoom fallback: {exc}")
    if n is None:
        n = int(max(60, min(320, len(work))))
    if _need_n:
        _cap75 = 320 if tf in ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h") else 400
        n = int(max(n, min(_need_n, _cap75, len(work))))
    frame = work.tail(n).reset_index(drop=True)
    fts = pd.to_datetime(frame["ts_dt"]).to_numpy()
    o = frame["open"].astype(float).to_numpy()
    h = frame["high"].astype(float).to_numpy()
    l = frame["low"].astype(float).to_numpy()
    c = frame["close"].astype(float).to_numpy()
    vol = frame["volume"].astype(float).to_numpy() if "volume" in frame.columns else np.zeros(n)
    live = float(c[-1])
    if y_lo is None or y_hi is None or not (y_hi > y_lo > 0):
        y_lo, y_hi = float(l.min()) * 0.94, float(h.max()) * 1.06
    # ── Viva 10-13 band law (25-30% clean tool band, candles ≈66%): clamp
    # any post-solver padding back to the smart-zoom core's exact window —
    # a SHORT sheet was showing a ~37% dead band under the candles.
    try:
        from analysis.smart_zoom import _tool_levels as _tl75
        _cr75 = math.log10(float(h.max()) / float(l.min()))
        _S75 = _cr75 / 0.66
        if str(getattr(candidate, "direction", "") or "LONG").upper() != "SHORT":
            _lg_lo75 = math.log10(float(l.min())) - 0.06 * _S75
            _lg_hi75 = _lg_lo75 + _S75
        else:
            _lg_hi75 = math.log10(float(h.max())) + 0.06 * _S75
            _lg_lo75 = _lg_hi75 - _S75
        _tl75s = _tl75(candidate)
        if _tl75s:
            if math.log10(max(_tl75s)) > _lg_hi75:
                _lg_hi75 = math.log10(max(_tl75s)) + 0.02 * _S75
            if math.log10(min(_tl75s)) < _lg_lo75:
                _lg_lo75 = math.log10(min(_tl75s)) - 0.02 * _S75
        y_lo = max(y_lo, 10.0 ** _lg_lo75)
        y_hi = min(y_hi, 10.0 ** _lg_hi75)
    except Exception:
        pass
    # Viva 10-13: «حاشیه پشت قیمت رو کم کن و به چارت اضافه کن» — 8% band.
    # Viva 10-14: the LIVE candle sits ~15% of the width away from the price
    # axis (right gap = future / (n + future) = 0.15).
    future = int(max(12, min(60, round(0.176 * n))))

    # ── 2) canvas: cream VIVA, price panel + volume panel ─────────────────
    fig, (ax, av) = plt.subplots(
        2, 1, figsize=(15, 8.5), dpi=240,   # frozen frame (R73)
        gridspec_kw={"height_ratios": [4.6, 0.72], "hspace": 0.045})
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=0.115, right=0.938, top=0.895, bottom=0.075)
    for a_ in (ax, av):
        a_.set_facecolor(BG)
    ax.set_yscale("log")
    for a_ in (ax, av):
        a_.set_xlim(-1, n + future)
    ax.set_ylim(y_lo, y_hi)

    width = 0.62
    for i in range(n):
        up = c[i] >= o[i]
        col = GREEN if up else RED
        ax.vlines(i, l[i], h[i], color=col, linewidth=0.9, zorder=3, alpha=0.95)
        ax.add_patch(patches.Rectangle(
            (i - width / 2, min(o[i], c[i])), width, max(abs(c[i] - o[i]), 1e-9),
            facecolor=col, edgecolor=_edge_of(col), linewidth=0.7,
            alpha=0.93, zorder=4))
    av.bar(np.arange(n), vol, width=0.66, color="#C8A886", alpha=0.75)
    av.set_yticks([])
    av.set_ylim(0, float(vol.max()) * 1.15 if vol.max() > 0 else 1.0)

    # ── 3) locked geometry: clipped, pivot-faithful, apex-bounded ─────────
    def _x_of(ts_val):
        try:
            return float(np.searchsorted(fts, np.datetime64(pd.Timestamp(str(ts_val)))))
        except Exception:
            return None

    def _clip(slope, ic, xa, xb):
        if slope == 0:
            y0 = 10.0 ** ic
            return (xa, xb) if y_lo <= y0 <= y_hi else (xb, xa)
        x_hi = (math.log10(y_hi) - ic) / slope
        x_lo = (math.log10(y_lo) - ic) / slope
        lo_x, hi_x = min(xa, xb), max(xa, xb)
        if slope > 0:
            lo_x, hi_x = max(lo_x, x_lo), min(hi_x, x_hi)
        else:
            lo_x, hi_x = max(lo_x, x_hi), min(hi_x, x_lo)
        return lo_x, hi_x

    rp_list = md.get("render_patterns") or []
    primary = rp_list[0] if rp_list else None
    lines = (primary or {}).get("lines") or []
    fits = []
    for ln in lines:
        pts = ln.get("points") or []
        xs, ys = [], []
        for p in pts:
            x = _x_of(p.get("ts"))
            if x is None or x > n + 1:
                continue
            xs.append(x)
            ys.append(float(p.get("price") or 0.0))
        if len(xs) < 2:
            # ── G1 law (Viva 10-13): the ENGINE's calibrated fit still
            # paints when a family ships fit keys WITHOUT pivot points
            # (pennants/flags) — those patterns were rendering EMPTY.
            sl_l = ln.get("log_slope")
            ic_l = ln.get("log_intercept")
            if sl_l is None and ln.get("slope") is not None \
                    and ln.get("intercept") is not None:
                _s75 = float(ln["slope"]); _c75 = float(ln["intercept"])
                _x0k = float(ln.get("x0") or 0)
                y0 = _s75 * _x0k + _c75
                y1 = _s75 * (_x0k + 1) + _c75
                if y0 > 0 and y1 > 0 and y0 != y1:
                    sl_l = math.log10(y1) - math.log10(y0)
                    ic_l = math.log10(y0)
            if sl_l is not None and ic_l is not None:
                _x0k = float(ln.get("x0") or 0)
                _x1k = float(ln.get("x1") or (n - 1))
                fits.append({
                    "slope": float(sl_l), "ic": float(ic_l),
                    "x0": _x0k, "x1": _x1k,
                    "xs": [_x0k, _x1k],
                    "ys": [10.0 ** (float(sl_l) * _x0k + float(ic_l)),
                           10.0 ** (float(sl_l) * _x1k + float(ic_l))],
                    "side": str(ln.get("side") or "").upper(),
                    "break_ts": ln.get("break_ts"),
                    "break_x": ln.get("break_x")})
            continue
        slope, ic = np.polyfit(xs, np.log10(np.clip(ys, 1e-12, None)), 1)
        fits.append({"slope": slope, "ic": ic, "x0": min(xs), "x1": max(xs),
                     "xs": xs, "ys": ys,
                     "side": str(ln.get("side") or "").upper(),
                     "break_ts": ln.get("break_ts"), "break_x": ln.get("break_x")})
    # converging pairs end at their apex (his wedge/triangle law)
    apex = n + future
    if len(fits) >= 2:
        s1, s2 = fits[0], fits[1]
        # converging pair (ANY distinct slopes on the log axis — a rising
        # wedge has two positive slopes) END AT THEIR APEX, his law
        if abs(s1["slope"] - s2["slope"]) > 1e-9:
            xa = (s2["ic"] - s1["ic"]) / (s1["slope"] - s2["slope"])
            if max(s1["x0"], s2["x0"]) < xa <= n + future:
                apex = float(xa)
    for f in fits:
        col = RED if f["side"] == "HIGH" else (GREEN if f["side"] == "LOW" else INK)
        y_live = 10.0 ** (f["slope"] * (n - 1) + f["ic"])
        alive = abs(y_live - live) / live <= 0.08   # stale-leg guard (10-13)
        x_solid = min(n - 1, apex) if alive else min(f["x1"], apex)
        # r59.2 broken-leg law (same as the unified path): a leg price has
        # CLOSED beyond paints solid ONLY to its break bar, faint dash after
        bx = f.get("break_ts")
        bx = _x_of(bx) if bx else f.get("break_x")
        if bx is not None and 0 < float(bx) < x_solid:
            x_solid = float(bx)
        xa, xb = _clip(f["slope"], f["ic"], f["x0"], x_solid)
        if xb > xa:
            xx = np.linspace(xa, xb, 90)
            ax.plot(xx, 10.0 ** (f["slope"] * xx + f["ic"]), color=col,
                    linewidth=1.9, zorder=5, solid_capstyle="round")
        xd_a, xd_b = _clip(f["slope"], f["ic"], max(x_solid, f["x0"]),
                           min(apex, n + future - 1))
        if xd_b > xd_a + 0.5:
            xx = np.linspace(xd_a, xd_b, 50)
            ax.plot(xx, 10.0 ** (f["slope"] * xx + f["ic"]), color=col,
                    linewidth=1.3, linestyle=(0, (5, 3)), alpha=0.8, zorder=5)
        for px, py in zip(f["xs"], f["ys"]):
            if 0 <= px <= n and y_lo <= py <= y_hi:
                ax.scatter(px, py, s=26, facecolor="#FDF49F", edgecolor=INK,
                           linewidth=1.1, zorder=6)

    # ── 4) faint zone fills, names in the right margin ────────────────────
    for zi, z in enumerate((md.get("render_zones") or [])[:6]):
        try:
            zlo, zhi = float(z.get("price_lo") or z.get("lo")), float(z.get("price_hi") or z.get("hi"))
        except Exception:
            continue
        zx0 = _x_of(z.get("ts_start") or z.get("start_ts")) or 0.0
        zx1 = _x_of(z.get("ts_end") or z.get("end_ts"))
        zx1 = min(n + future - 1, zx1 if zx1 is not None else n + future - 1)
        shade = ZONE_FA["above" if (zlo + zhi) / 2 > live else "below"]
        ax.add_patch(patches.Rectangle((zx0, zlo), max(1.0, zx1 - zx0), zhi - zlo,
                                       facecolor=shade, edgecolor="none",
                                       alpha=0.30, zorder=2))

    # ── 5) trade tool: POI/ENTRY band, FIRST STOP, TP pills 1/2/3 ─────────
    def _pill(yval, txt, fc, tc="white", fs=7.4):
        try:
            _yy = fig.transFigure.inverted().transform(ax.transData.transform((0.0, yval)))[1]
            fig.text(ax.get_position().x1 + 0.004, _yy, f" {txt} ", ha="left",
                     va="center", fontsize=fs, fontweight="bold", color=tc,
                     zorder=45, bbox=dict(boxstyle="square,pad=0.20",
                                          facecolor=fc, edgecolor="none"))
        except Exception:
            pass

    side = str(getattr(candidate, "direction", "LONG") or "LONG").upper()
    e_lo = float(getattr(candidate, "entry_zone_bottom", 0) or 0)
    e_hi = float(getattr(candidate, "entry_zone_top", 0) or 0)
    sl = float(getattr(candidate, "sl", 0) or 0)
    ladder = ((md.get("target_ladder") or {}).get("targets")) or []
    tps = [float(t) for t in ladder[:3]] or [
        float(v) for v in (getattr(candidate, "tp1", 0), getattr(candidate, "tp2", 0)) if v]
    if e_lo and e_hi and e_hi > e_lo:
        ax.add_patch(patches.Rectangle((n - 1, e_lo), future * 0.9, e_hi - e_lo,
                                       facecolor="#B9F6CA" if side == "LONG" else "#F3C1C6",
                                       edgecolor="none", alpha=0.55, zorder=2))

    if sl:
        ax.hlines(sl, n - 1, n + future - 1, colors=RED, linestyles="--", lw=1.0, zorder=5)
        _pill(sl, "FIRST STOP", RED)
        if _tr75 > 0:
            _pill(_tr75, "TRAIL", "#7A4A00")
    for i, t in enumerate(tps, 1):
        if t:
            ax.hlines(t, n - 1, n + future - 1, colors=GREEN, linestyles="--", lw=0.9,
                      alpha=0.85, zorder=5)
            _pill(t, str(i), GREEN)

    # ── 6) axes chrome ─────────────────────────────────────────────────────
    ax.yaxis.set_major_locator(FixedLocator(list(np.geomspace(y_lo, y_hi, 34))))
    ax.yaxis.set_major_formatter(FuncFormatter(_price_fmt))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.tick_params(axis="y", which="both", labelsize=7.2, colors="#4A4640",
                   length=4, width=0.8, pad=8, labelright=True, right=True,
                   labelleft=False, left=False)
    _step = max(1, n // 10)
    _xt = list(range(0, n, _step))
    av.set_xticks(_xt)
    av.set_xticklabels([pd.Timestamp(fts[i]).strftime("%m-%d %H:%M") for i in _xt],
                       fontsize=7.4, color="#4A4640")
    ax.set_xticklabels([])
    ax.tick_params(axis="x", labelleft=False, left=False)
    av.tick_params(axis="x", labelsize=7.4, colors="#4A4640")
    for a_ in (ax, av):
        # Viva 10-14: the frame reads as a FRAME — all four spines, darker.
        for s in ("top", "left", "right", "bottom"):
            a_.spines[s].set_visible(True)
            a_.spines[s].set_color("#3B372F")
            a_.spines[s].set_linewidth(1.4)
    # Viva 10-13 (his law #1): NO gridlines in the candle background.
    ax.grid(False, which="both")

    # ── 7) watermark / header / live cells / footer ───────────────────────
    if os.path.isfile(LOGO):
        try:
            mk = ax.inset_axes([0.395, 0.315, 0.21, 0.37], transform=ax.transAxes, zorder=1)
            mk.imshow(mpimg.imread(LOGO), alpha=0.050)
            mk.set_axis_off()
            mk.patch.set_alpha(0)
        except Exception:
            pass
    ax.text(0.50, 0.52, f"{symbol}, {tf.upper()}", transform=ax.transAxes,
            ha="center", va="center", fontsize=40, fontweight="bold",
            color="#8B8578", alpha=0.30, zorder=1)
    _style = str(getattr(candidate, "style", "") or "DAYTRADE").upper()
    fig.text(0.030, 0.965, f"{symbol}  •  {tf.upper()}  •  {_style}  •  {side}",
             fontsize=15, fontweight="bold", color=INK, va="center")
    fig.text(0.030, 0.940,
             f"VIVA SIGNALS PRO  •  {getattr(candidate, 'setup_code', '')}  •  "
             f"{'CONFIRMED' if confirmed else 'ANALYSIS'}  •  Log Scale",
             fontsize=10, color="#4A4640", va="center")
    chg = float(c[-1] - o[-1])
    pctd = 100.0 * chg / float(o[-1]) if o[-1] else 0.0
    fig.text(0.030, 0.917,
             f"O {_price_fmt(o[-1])}   H {_price_fmt(h[-1])}   L {_price_fmt(l[-1])}   "
             f"C {_price_fmt(c[-1])}   {chg:+,.6g} ({pctd:+.2f}%)   ·   BINANCE FUTURES",
             fontsize=8.5, fontweight="bold", va="center",
             color=("#06705E" if chg >= 0 else "#B81B29"))
    # ── 7b) ONE info panel, left of the chart, never over the candles ─────
    _panel = [f"{getattr(candidate, 'setup_code', '')} · {side}",
              "CONFIRMED" if confirmed else "ANALYSIS"]
    if e_lo and e_hi:
        _panel.append(f"ENTRY {_price_fmt(e_lo)}-{_price_fmt(e_hi)}")
    if sl:
        _panel.append(f"FIRST STOP {_price_fmt(sl)}")
    for i, t in enumerate(tps, 1):
        if t:
            _panel.append(f"TP{i} {_price_fmt(t)}")
    # Viva 10-14: margin + leverage ride the same block; trailing stop joins
    # the tool when the chain carries one.
    _lev75 = int(md.get("leverage") or _LEV_BY_TF.get(tf, 3))
    _marg75 = str(md.get("margin_mode") or "ISOLATED").upper()
    _panel.append(f"LEV {_lev75}x · MARGIN {_marg75}")
    if _tr75 > 0:
        _panel.append(f"TRAIL {_price_fmt(_tr75)}")
    # Viva 10-14: the data block lives INSIDE the frame (3% margin), one
    # unbroken column, parked in the empty left space above/below the candles.
    _occ75 = (math.log10(max(live, 1e-12)) - math.log10(y_lo)) / max(
        1e-9, math.log10(y_hi) - math.log10(y_lo))
    _va75, _ya75 = ("top", 0.97) if _occ75 < 0.55 else ("bottom", 0.03)
    ax.text(0.03, _ya75, "\n".join(_panel), transform=ax.transAxes,
            fontsize=7.6, color="#4A4640", va=_va75, ha="left",
            linespacing=1.9, fontweight="bold", zorder=30)
    fig.canvas.draw()
    try:
        _ly = fig.transFigure.inverted().transform(ax.transData.transform((n - 1, live)))[1]
        _hms = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%H:%M:%S")
        fig.text(ax.get_position().x1 + 0.004, _ly, f" {_price_fmt(live)} \n {_hms} ",
                 ha="left", va="center", fontsize=7.0, fontweight="bold",
                 color="#FFFFFF", linespacing=1.15, zorder=46,
                 bbox=dict(boxstyle="square,pad=0.22", facecolor="#141414",
                           edgecolor="none"))
    except Exception as exc:
        print(f"perp v2 live cell warning: {exc}")
    try:
        _xd = fig.transFigure.inverted().transform(av.transData.transform((n - 1, 0.0)))[0]
        _stamp = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%m-%d %H:%M")
        fig.text(_xd, av.get_position().y0 - 0.020, f" {_stamp} ", ha="center", va="top",
                 fontsize=7.6, fontweight="bold", color="white", zorder=40,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="#2b2f3a", edgecolor="none"))
    except Exception as exc:
        print(f"perp v2 live stamp warning: {exc}")
    fig.patches.append(patches.Rectangle((0, 0), 1, 0.045, transform=fig.transFigure,
                                         facecolor=BG, edgecolor="#8A857D",
                                         linewidth=0.8, zorder=20))
    fig.text(0.030, 0.022, f"{symbol}  •  VIVA ✦ {getattr(candidate, 'setup_code', 'PERP')}  •  BINANCE FUTURES",
             color="#4A4640", fontsize=7.5, va="center", zorder=22)
    bx = 0.955
    if os.path.isfile(LOGO):
        try:
            la = fig.add_axes([0.918, 0.004, 0.032, 0.038], zorder=23)
            la.imshow(mpimg.imread(LOGO), alpha=0.52)
            la.axis("off")
            bx = 0.912
        except Exception:
            pass
    fig.text(bx, 0.022, "VIVA SIGNALS PRO", color=INK, fontsize=10.5,
             fontweight="bold", ha="right", va="center", alpha=0.85, zorder=22)
    try:  # setup sticker (his badge law) — shared with the unified path
        import bot.messages_v7 as _M75
        _M75._add_setup_sticker(fig, candidate)
    except Exception:
        pass

    buf = io.BytesIO()
    # Viva 10-13 law #1: NO gridline on ANY axis (price + volume).
    for _ax75g in fig.axes:
        _ax75g.grid(False, which='both')
    fig.savefig(buf, format="png", facecolor=BG, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
