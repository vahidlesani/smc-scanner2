"""R99a — per-setup engine registry (DATA ONLY; zero behavior change).

قانون کاربر (۲۰۲۶-۱۰-۱۳): هر ستاپ باید انجینِ اختصاصی خودش را داشته باشد
(زوم هوشمند، تشخیص TL/پترن، شمارش کندل، سیم‌کشی زون‌ها)؛ دیباگِ یک ستاپ
نباید ستاپ دیگر را تکان بدهد. انجین‌های مشترک، مشترک می‌مانند.

وضعیت امروز (حسابرسی ۱۰-۱۳): همهٔ ستاپ‌ها خط‌هایشان را از یک قیف مشترک
می‌گیرند: analysis/render_kit.py سطر ~987 (md["render_patterns"]) + دیکتهٔ
pattern_geo + کلیدهای tl_*‎ و viva_*‎. اسلایس‌های بعدی رندر را طوری سیم‌کشی
می‌کنند که هر ستاپ فقط کلیدهای خودش را بخواند.

This module only DECLARES ownership. Routing slices (R99b+) will enforce it.
"""

SETUP_ENGINES = {
    # setup_code: {detectors, line_keys, zones, notes}
    "TECHCLASSIC": {
        "detectors": ["analysis.pattern_engine.detect_technoclassic"],
        "line_keys": ["pattern_geo", "render_patterns",
                      "tl_a_ts", "tl_b_ts", "tl_anchor_ts", "tl_stage", "tl_pattern"],
        "zones": False,  # قانون: زون فقط ALBROX/PINWALL
        "notes": "shared-funnel-today",
    },
    "TLBREAK": {
        "detectors": ["analysis.setups_experimental.detect_viva_tlbreak"],
        "line_keys": ["pattern_geo", "render_patterns",
                      "tl_a_ts", "tl_b_ts", "tl_anchor_ts", "tl_stage", "tl_pattern"],
        "zones": False,
        "notes": "inner-ceiling-floor-law; shared-funnel-today",
    },
    "PINVAL": {
        "detectors": ["analysis.setups_experimental.PINVAL_DETECTORS"],
        "line_keys": ["pattern_geo", "render_patterns",
                      "pin_high", "pin_low", "pin_tf", "pin_ctx_tf", "pin_has_doji"],
        "zones": False,
        "notes": "multi-gate-list; single-engine-routing-pending",
    },
    "ALBROX": {
        "detectors": ["analysis.setups_experimental.detect_albrox"],
        "line_keys": ["pattern_geo", "render_patterns",
                      "viva_upper_points", "viva_lower_points"],
        "zones": True,  # قانون: زون فقط ALBROX/PINWALL
        "notes": "box-to-same-tf-ceiling; shared-funnel-today",
    },
    # R99j (r40 09-26): PINWALLQ is not emitted -- the surviving setup is
    # PINWALL LEGACY, which IS the PINVAL lane above (display name PINWALL).
    # No separate PINWALL lane exists; nothing may reference one.
}

# انجین‌های مشترک (دست نمی‌خورند مگر با دلیل مشترک):
SHARED_ENGINES = [
    "analysis.quality_engine.ENGINES",   # GRAND/SWING/DAYTRADE/SCALP (استایل‌ها)
    "analysis.render_kit",               # قیف رندر (تا سیم‌کشی R99b)
    "analysis.snapshot_lock",            # قفل اسنپ‌شات (اسپات+پرپ)
    "analysis.stage2_wiring",            # سیم‌کشی اسپات مرحله ۲
]


def get_setup_engine(setup_code: str):
    """Return the registry entry for a setup, or None if unknown."""
    return SETUP_ENGINES.get(str(setup_code or "").upper())


def setup_line_keys(setup_code: str):
    """Metadata keys a setup is allowed to paint (routing target)."""
    entry = get_setup_engine(setup_code)
    return list(entry["line_keys"]) if entry else []


def setup_has_zones(setup_code: str) -> bool:
    """Only ALBROX/PINWALL may paint zones (user law)."""
    entry = get_setup_engine(setup_code)
    return bool(entry and entry["zones"])
