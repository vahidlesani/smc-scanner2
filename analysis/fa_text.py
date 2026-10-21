"""Persian/Arabic text for images — shaping + RTL, with the bundled font.

Viva 09-21: «موتور تولید زبان فارسی در چارت خرابه من نفهمیدم چی نوشتی» — Persian
strings drawn into a matplotlib figure came out mirrored and with disconnected
letters, because drawing engines lay out glyphs left-to-right and never join
Arabic script. Two things were missing:

  1. a FONT with Persian coverage — the container shipped none (DejaVu has no
     Arabic glyphs at all), so any Persian word became a row of boxes;
  2. SHAPING + BIDI — joining letters into their contextual forms and putting
     the run in visual (right-to-left) order.

Both are provided here. `fa()` is the single entry point every renderer must use
for Persian text; `use_persian_font()` returns the family name to pass to
matplotlib. Missing libraries or a missing font degrade gracefully (the raw
string is returned), so a render can never crash because of this module.
"""
from __future__ import annotations

import os
from typing import Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(_REPO, "assets", "fonts")
FONT_REGULAR = os.path.join(FONT_DIR, "Vazirmatn-Regular.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "Vazirmatn-Bold.ttf")
FA_FAMILY = "Vazirmatn"

_registered = False


def _register() -> str:
    """Register the bundled Persian font with matplotlib once."""
    global _registered
    if _registered:
        return FA_FAMILY
    try:
        import matplotlib.font_manager as fm

        for path in (FONT_REGULAR, FONT_BOLD):
            if os.path.isfile(path):
                try:
                    fm.fontManager.addfont(path)
                except Exception:
                    pass
        if any(f.name == FA_FAMILY for f in fm.fontManager.ttflist):
            _registered = True
            return FA_FAMILY
    except Exception:
        pass
    return ""


def use_persian_font() -> Optional[str]:
    """Family name to hand to matplotlib for Persian text ('' when unavailable)."""
    return _register() or None


def fa(text) -> str:
    """Shape + reorder a Persian string so a LTR renderer draws it correctly.

    Latin words, digits and punctuation pass through unchanged; only Arabic
    script runs are joined and reversed. Safe on any input, never raises.
    """
    raw = str(text if text is not None else "")
    if not raw:
        return raw
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(raw))
    except Exception:
        # no shaper installed (e.g. a stripped environment): return as-is rather
        # than dropping the label entirely
        return raw


def fa_rtl(text) -> str:
    """Alias kept for readability at call sites."""
    return fa(text)


def fonts_ready() -> bool:
    """True when both the font and the shaper are usable — used by tests."""
    try:
        import arabic_reshaper  # noqa: F401
        from bidi.algorithm import get_display  # noqa: F401
    except Exception:
        return False
    return bool(_register())
