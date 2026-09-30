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

from typing import Any, Dict

# Every metadata key that paints structure on the chart. The trade-geometry
# keys (viva_*_points, pattern_geo, break_line_geo …) are frozen at the
# candidate store (absorb keep-set) — these are the RENDER-side keys.
SNAPSHOT_KEYS = (
    "render_patterns", "render_zones", "render_htf_pattern", "pattern_band",
    "base_watch", "base_gate", "render_line_watch", "tool_anchor_ts",
    "htf_zones", "render_patterns_trade",
)

_PREFIX = "render_identity:"


def snapshot_key(signal_id: str) -> str:
    return f"{_PREFIX}{signal_id}"


def _has_trade_lines(md: Dict[str, Any]) -> bool:
    up = md.get("viva_upper_points") or []
    lo = md.get("viva_lower_points") or []
    return (isinstance(up, list) and len(up) >= 2) or (isinstance(lo, list) and len(lo) >= 2)


def unify_trade_geometry(md: Dict[str, Any]) -> bool:
    """G1: one geometry. Returns True when render-fitter lines were removed."""
    if not isinstance(md, dict):
        return False
    if str(md.get("strategy_variant") or "").upper() != "VIVA_TLBREAK":
        return False
    if not _has_trade_lines(md):
        return False
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
        else:
            removed = True
    if removed or md.get("render_geometry_source") != "TRADE":
        md["render_patterns"] = kept
        md["render_geometry_source"] = "TRADE"
    return removed


def lock_render_geometry(candidate, kv_get=None, kv_set=None) -> str:
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
        md["snapshot_locked"] = True
        return "RESTORED"
    if not (md.get("render_patterns") or md.get("render_zones")):
        return ""
    unify_trade_geometry(md)
    snap = {k: md.get(k) for k in SNAPSHOT_KEYS if k in md}
    snap.setdefault("render_patterns", md.get("render_patterns") or [])
    snap.setdefault("render_zones", md.get("render_zones") or [])
    try:
        kv_set(snapshot_key(sid), snap)
    except Exception:
        return ""
    md["snapshot_locked"] = True
    return "STAMPED"
