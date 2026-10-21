"""R63 SNAPSHOT-LOCK + ONE-GEOMETRY law (Viva 10-01).

Verbatim rulings this module enforces:

* «وقتی یک ترند یا الگو در یک نقطه شناسایی شد و هشدار اولیه صادر شد، اون کد
  یکتا باید اسنپ‌شات بگیره از الگو و ترندش و تا پایان اون پوزیشن دیگه نباید
  نواحی جدید رسم بشه یا ترندلاین روی پیوت‌های جدید امتداد پیدا کنه و الگو
  ادامه پیدا کنه. فقط برای همون کد یکتا.»
* «ترند و الگوها در چارت و ترید متفاوته — باید یکی بشه» (audit G1: the chart
  painted the render fitter's lines while the trade used the TC/TLBREAK
  fitter's lines).

Contract
--------
``lock_render_geometry(candidate)`` is called by the renderer on EVERY chart
of a chain. The first call (the initial alert) stamps the drawn geometry into
``bot_kv['render_identity:<signal_id>']``; every later call (updates, confirm,
TP/stop receipts, zoom) restores exactly that snapshot over whatever a later
scan wrote into the metadata. The key is per signal id, so a NEW chain (new
unique code) is free to draw its own fresh structure — the lock never leaks
across codes.

``unify_trade_geometry(md)`` removes the render-fitter's own trend/pattern
lines from a chain that carries TRADE lines (``viva_upper_points`` /
``viva_lower_points`` — the very edges the confirmation projects), so the
chart shows ONE geometry: the traded one. Pivot patterns minted by the trade
lane carry ``trade_geometry=True`` and are kept (they ARE the trade geometry).
"""
from __future__ import annotations

import os

from typing import Any, Dict

# Every metadata key that paints structure on the chart. The trade-geometry
# keys (viva_*_points, pattern_geo, break_line_geo …) are frozen at the
# candidate store (absorb keep-set) — these are the RENDER-side keys.
SNAPSHOT_KEYS = (
    "render_patterns", "render_zones", "render_htf_pattern", "pattern_band",
    "base_watch", "base_gate", "render_line_watch", "tool_anchor_ts",
    "htf_zones", "render_patterns_trade",
    # R64.1 (his 10-03: «تکنوکلاسیک اسنپ‌شات نمیشه»): the TC/TLBREAK TRADE
    # lines are drawn from these metadata keys on every chart — they were
    # never snapshotted, so every update re-fitted them from the fresh scan
    # and the chain's geometry drifted (HYPE T318773: two different charts).
    "viva_upper_points", "viva_lower_points", "viva_retest_zone",
    "tc_projection", "tc_base", "tl_line", "tl_touches",
    # Viva 10-10 Hole-3 (his «تأیید باید روی چارت باشه»): the CONFIRM edges
    # (pattern_geo / break_line_geo — read by quality_engine containment +
    # veto and by the live-edge core) freeze with the render. Before this the
    # chart stayed locked while the confirmation kept re-reading fresh edges.
    "pattern_geo", "break_line_geo",
)

_PREFIX = "render_identity:"


def snapshot_key(signal_id: str) -> str:
    return f"{_PREFIX}{signal_id}"


def _has_trade_lines(md: Dict[str, Any]) -> bool:
    up = md.get("viva_upper_points") or []
    lo = md.get("viva_lower_points") or []
    return (isinstance(up, list) and len(up) >= 2) or (isinstance(lo, list) and len(lo) >= 2)


def _cited_pattern_family(md: Dict[str, Any]) -> str:
    """Family (TRIANGLE/WEDGE/CHANNEL/TRENDLINE/...) of the pattern the chain
    CITES as its justification (the PAT pill reads these keys)."""
    for k in ("tl_pattern", "viva_pattern", "pattern_type"):
        v = str(md.get(k) or "").upper().strip()
        if v and v != "NONE":
            return v.split("_")[0]
    return ""


def unify_trade_geometry(md: Dict[str, Any]) -> bool:
    """G1: one geometry. Returns True when render-fitter lines were removed.

    Viva 10-11 (AERO class: the chart cited PAT 4H TRIANGLE but drew no
    pattern — the label Madd while the drawing was stripped): the JUSTIFYING
    pattern (the cited family) is NEVER removed — only FOREIGN render-fitter
    lines (a different family than the trade, the HYPE-T318773 second
    geometry G1 was built for) are dropped. Chains that cite nothing keep
    the legacy behavior (legacy r33 snapshots still clean on restore).
    """
    if not isinstance(md, dict):
        return False
    if str(md.get("strategy_variant") or "").upper() != "VIVA_TLBREAK":
        return False
    if not _has_trade_lines(md):
        return False
    _cited = _cited_pattern_family(md)
    pats = list(md.get("render_patterns") or [])
    kept = []
    removed = False
    # the trade lane's own pattern commands (P4 pivot family) join the set
    for tp in (md.get("render_patterns_trade") or []):
        if isinstance(tp, dict) and not any(
                isinstance(p, dict) and p.get("trade_geometry")
                and p.get("type") == tp.get("type") for p in pats):
            pats.append(dict(tp, trade_geometry=True))
            removed = True
    for p in pats:
        if not isinstance(p, dict):
            continue
        t = str(p.get("type") or "").upper()
        if p.get("trade_geometry") or t == "RANGE":
            kept.append(p)
        elif _cited and t.split("_")[0] == _cited:
            # the justifying pattern stays: the PAT pill cites it, so the
            # chart must draw it (geometry+message sync law).
            kept.append(p)
        else:
            removed = True
    if removed or md.get("render_geometry_source") != "TRADE":
        md["render_patterns"] = kept
        md["render_geometry_source"] = "TRADE"
        # the render fitter's band/line-watch describe lines that are no
        # longer drawn — the confirmation reads the traded edges
        # (pattern_geo / break_line_geo) instead. A RANGE band survives.
        _band = md.get("pattern_band") or {}
        if isinstance(_band, dict) and str(_band.get("kind") or "").upper() != "RECTANGLE":
            md["pattern_band"] = {}
        _pg = md.get("pattern_geo") or {}
        if isinstance(_pg, dict) and (_pg.get("upper") or _pg.get("lower")):
            md["render_line_watch"] = []
    return removed


# Geometry-law generation tag. Bump it (or set VIVA_GEOM_LAW) whenever the
# fitter laws change: every snapshot stamped under an older tag is healed ONCE
# with the current fitter on its chart's own frame, then re-frozen —
# immutability holds WITHIN a generation, his «ترندلاین روی پیوت‌های جدید
# امتداد پیدا نکنه» stays true, and pre-law chains stop painting dead pivots.
GEOM_LAW = os.getenv("VIVA_GEOM_LAW", "R64.3")


def lock_render_geometry(candidate, kv_get=None, kv_set=None, frame=None) -> str:
    """Stamp (first chart) or restore (every later chart) the per-code render
    snapshot. Returns "STAMPED", "RESTORED" or "" (nothing to do / KV down).
    Fail-open: any KV problem leaves the metadata as it is."""
    sid = str(getattr(candidate, "signal_id", "") or "")
    md = getattr(candidate, "metadata", None)
    if not sid or not isinstance(md, dict):
        return ""
    if kv_get is None or kv_set is None:
        try:
            from database.bot_kv import get_json as _g, set_json as _s
            kv_get = kv_get or _g
            kv_set = kv_set or _s
        except Exception:
            return ""
    try:
        stored = kv_get(snapshot_key(sid)) or None
    except Exception:
        stored = None
    if isinstance(stored, dict) and (stored.get("render_patterns") is not None
                                     or stored.get("render_zones") is not None):
        for k in SNAPSHOT_KEYS:
            if k in stored:
                md[k] = stored[k]
        # R64.1b (his 10-03, HYPE T318773 class): snapshots taken BEFORE the
        # trade-line keys existed carry no viva_upper/lower_points — the
        # restore then left the FRESH re-fit in place and every update
        # drifted again. A snapshot missing a key that the CURRENT chart
        # just fitted is upgraded ONCE: the fresh fit is frozen into the
        # stored snapshot (from this update on the chain is immutable).
        # ── R99q21 LAW RE-STAMP ON RESTORE (his 10-16, verbatim: «در برخی
        # شناسه‌های یکتا دقت کن هشدار ابتدایی بصورت صحیح پترن رسم شده بوده
        # الان در زمان تایید یه چیز دیگه میده یا اصلا پترنی وجود نداره»).
        # A snapshot frozen BEFORE the pattern law carries bare labels
        # (RANGE / TRENDLINE / old engine slugs) and NO verdict. On restore
        # every stored pattern is re-judged by the SAME law the live lane
        # uses — geometry untouched, only the verdict added — so the locked
        # chart speaks the law's language (slug · bias · break side ·
        # near-break) and can never contradict its own first alert.
        try:
            from analysis.render_kit import _law_stamp as _stamp21
            _fr21 = frame if frame is not None else None
            if _fr21 is not None and len(_fr21):
                _pats21 = []
                for _p21 in (md.get("render_patterns") or []):
                    if not isinstance(_p21, dict):
                        continue
                    try:
                        _ln21 = [x for x in (_p21.get("lines") or []) if isinstance(x, dict)]
                        if len(_ln21) >= 2:
                            _p21 = _stamp21(dict(_p21), _fr21, _ln21[0], _ln21[1])
                        elif len(_ln21) == 1:
                            _p21 = _stamp21(dict(_p21), _fr21, _ln21[0], None)
                        elif _p21.get("hi") and _p21.get("lo"):
                            _p21 = _stamp21(dict(_p21), _fr21,
                                            {"slope": 0.0, "intercept": float(_p21["hi"])},
                                            {"slope": 0.0, "intercept": float(_p21["lo"])})
                    except Exception:
                        pass
                    _pats21.append(_p21)
                if _pats21:
                    # ── R99q37e (his 10-20: «یک آیدی یکتا، دو هندسه») ──────
                    # The gate DROPS past-market patterns — correct at
                    # DETECTION time, fatal on RESTORE: the first card of the
                    # chain had already drawn them, so card #2 came out
                    # without the channel card #1 showed (and, through the
                    # zoom subject, with a different price window). The
                    # snapshot is immutable by law: on restore the patterns
                    # are re-JUDGED (verdict/near_break stamped) but never
                    # removed — the chain keeps the geometry it froze.
                    try:
                        from analysis.pattern_law import gate_patterns as _g21
                        _kept21 = _g21(list(_pats21), tag=f"{sid} restore")
                        if len(_kept21) < len(_pats21):
                            print(f"R99q37e snapshot {sid}: "
                                  f"{len(_pats21) - len(_kept21)} past-market "
                                  f"pattern(s) stay ON THE CHART (frozen "
                                  f"geometry is immutable)")
                    except Exception:
                        pass
                    md["render_patterns"] = _pats21
                    try:
                        from analysis.pattern_law import sync_labels as _s21
                        _s21(md, _pats21)
                    except Exception:
                        pass
        except Exception as _e21:
            print(f"R99q21 law re-stamp warning: {_e21}")
        for _k64 in ("viva_upper_points", "viva_lower_points",
                     "viva_retest_zone", "tc_projection", "tc_base",
                     "pattern_geo", "break_line_geo"):
            if _k64 not in stored and md.get(_k64):
                stored[_k64] = md[_k64]
        # R63.1 (Viva 10-01: «یه چیزایی قدیمی»): chains opened BEFORE the R63
        # deploy carry a legacy r33 snapshot (render-fitter lines, no marker)
        # — restoring it verbatim kept painting the OLD second geometry. The
        # one-geometry filter runs on every restore (it only REMOVES
        # non-traded lines, never adds new ones, so the lock law holds) and
        # a legacy snapshot is migrated once to the marked format.
        # ── R64.3 HEAL-ONCE (his 10-03: «چارت‌ها رو فکر کنم برگردوندی به زمان
        # ایرادات قبلی») — a snapshot stamped before the current geometry laws
        # re-paints its dead pivots FOREVER (the lock forbids re-fits). Once
        # per law generation: re-run the CURRENT fitter on this chart's own
        # frame; a side that no longer validates is DROPPED, a side that does
        # is re-frozen. The tag then locks it again until the next law bump.
        _healed = False
        if stored.get("geom_law") != GEOM_LAW and frame is not None:
            try:
                from analysis.viva_tlbreak import fit_validated_line as _fvl64, load_config as _lc64
                _f2 = frame
                if "timestamp" not in _f2.columns:
                    _f2 = _f2.copy()
                    _f2["timestamp"] = _f2.index
                _f2 = _f2.reset_index(drop=True)
                _cfg64 = _lc64()
                for _side64, _key64 in (("HIGH", "viva_upper_points"),
                                        ("LOW", "viva_lower_points")):
                    _ln64 = _fvl64(_f2, _side64, _cfg64)
                    if _ln64 is not None and getattr(_ln64, "points", None):
                        md[_key64] = [dict(_p64) for _p64 in _ln64.points]
                    else:
                        md.pop(_key64, None)
                md.pop("viva_retest_zone", None)   # derived from the old edges
                _healed = True
            except Exception as _heal:
                print(f"R64.3 heal warning: {_heal}")
        _changed = unify_trade_geometry(md)
        if _changed or _healed or stored.get("geom_law") != GEOM_LAW \
                or "render_geometry_source" not in stored:
            try:
                snap = {k: md.get(k) for k in SNAPSHOT_KEYS if k in md}
                snap.setdefault("render_patterns", md.get("render_patterns") or [])
                snap.setdefault("render_zones", md.get("render_zones") or [])
                snap["render_geometry_source"] = md.get("render_geometry_source") or "RENDER"
                snap["geom_law"] = GEOM_LAW
                kv_set(snapshot_key(sid), snap)
            except Exception:
                pass
        md["snapshot_locked"] = True
        return "RESTORED"
    if not (md.get("render_patterns") or md.get("render_zones")):
        return ""
    unify_trade_geometry(md)
    snap = {k: md.get(k) for k in SNAPSHOT_KEYS if k in md}
    snap.setdefault("render_patterns", md.get("render_patterns") or [])
    snap.setdefault("render_zones", md.get("render_zones") or [])
    snap["render_geometry_source"] = md.get("render_geometry_source") or "RENDER"
    try:
        kv_set(snapshot_key(sid), snap)
    except Exception:
        return ""
    md["snapshot_locked"] = True
    return "STAMPED"

def restamp_render_geometry(candidate, kv_set=None) -> bool:
    """R99q37e — freeze what the FIRST card actually DREW.

    The lock stamps at the top of the render, before the painter has decided
    which shapes survive (native refit, far-major preserve, both-edges
    guarantee, dedupe). So a chain could freeze a set the alert never showed,
    and every later card painted something the alert did not — his «هشدار
    ابتدایی پترن درست اسنپ‌شات بشه». The painter now hands its final set
    back and the snapshot is re-written from it, once, on the card that
    stamped the chain.
    """
    sid = str(getattr(candidate, "signal_id", "") or "")
    md = getattr(candidate, "metadata", None)
    if not sid or not isinstance(md, dict):
        return False
    if kv_set is None:
        try:
            from database.bot_kv import set_json as _s
            kv_set = _s
        except Exception:
            return False
    try:
        snap = {k: md.get(k) for k in SNAPSHOT_KEYS if k in md}
        snap.setdefault("render_patterns", md.get("render_patterns") or [])
        snap.setdefault("render_zones", md.get("render_zones") or [])
        snap["render_geometry_source"] = md.get("render_geometry_source") or "RENDER"
        snap["geom_law"] = GEOM_LAW
        snap["drawn_set"] = True
        kv_set(snapshot_key(sid), snap)
        return True
    except Exception:
        return False
