"""R99q33a — FIL 3D spot: the Tehran stamp lost the word LIVE and left the
panel («کلمه live رو از برچسب زمان حذف بکن تا روی هیستوگرام ولوم رو نپوشونه»)."""
SRC = open("tools/render_spot_cryptocove.py", encoding="utf-8").read()


# ── the Tehran stamp: no LIVE word, and OUT of the panel ──────────────────
def test_the_stamp_has_no_live_word():
    assert " LIVE: " not in SRC
    assert '" LIVE:' not in SRC


def test_the_stamp_lives_below_the_panel_not_on_the_volume_bars():
    i = SRC.index("استمپ زمان تهران")
    block = SRC[i:i + 1200]
    assert 'fig.text(0.826, 0.052,' in block        # figure coords, below the panel
    assert "transform=ax.transAxes" not in block   # never inside the axes


