"""Round 70 (Viva 10-11, AERO class): the cited pattern must survive the
confirm strip, MTF slopes must rescale by pattern_tf/trigger_tf, and a chart
citing a sloped pattern it never drew must be vetoed (photo -> text-first)."""
from analysis.snapshot_lock import _cited_pattern_family, unify_trade_geometry


def _md_viva(pats, **extra):
    md = {"strategy_variant": "VIVA_TLBREAK",
          "viva_upper_points": [{"timestamp": "t1", "price": 2},
                                {"timestamp": "t2", "price": 1.9}],
          "render_patterns": pats}
    md.update(extra)
    return md


def test_cited_family_normalizes_variants():
    assert _cited_pattern_family({"tl_pattern": "TRIANGLE_ASCENDING"}) == "TRIANGLE"
    assert _cited_pattern_family({"viva_pattern": "wedge_falling"}) == "WEDGE"
    assert _cited_pattern_family({"pattern_type": "CHANNEL_DESCENDING"}) == "CHANNEL"
    assert _cited_pattern_family({"tl_pattern": "NONE"}) == ""
    assert _cited_pattern_family({}) == ""


def test_unify_keeps_cited_pattern_drops_foreign():
    md = _md_viva([{"type": "TRIANGLE", "lines": [{}]},
                   {"type": "WEDGE_RISING", "lines": [{}]},
                   {"type": "RANGE", "lo": 1, "hi": 2}],
                  tl_pattern="TRIANGLE_ASCENDING", tl_context_tf="4H")
    assert unify_trade_geometry(md) is True
    assert [p["type"] for p in md["render_patterns"]] == ["TRIANGLE", "RANGE"]
    assert md["render_geometry_source"] == "TRADE"


def test_unify_legacy_uncited_keeps_old_strip():
    """Chains citing nothing (legacy r33 snapshots) keep the G1 behavior."""
    md = _md_viva([{"type": "WEDGE_FALLING", "lines": [{}]},
                   {"type": "RANGE", "lo": 1, "hi": 2}])
    assert unify_trade_geometry(md) is True
    assert [p["type"] for p in md["render_patterns"]] == ["RANGE"]


def test_honesty_counter_counts_only_sloped_incanvas():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from bot.messages_v7 import _count_incanvas_sloped_lines
    fig, ax = plt.subplots()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.plot([1, 9], [1, 9])        # sloped + in-canvas -> counts
    ax.plot([1, 9], [5, 5])        # horizontal (tool) -> no
    ax.plot([2, 2], [1, 9])        # vertical (wick) -> no
    ax.plot([20, 30], [20, 30])    # sloped but off-canvas -> no
    try:
        assert _count_incanvas_sloped_lines(fig) == 1
    finally:
        plt.close(fig)


def test_honesty_counter_fail_open_on_garbage():
    from bot.messages_v7 import _count_incanvas_sloped_lines
    assert _count_incanvas_sloped_lines(object()) == 0
    assert _count_incanvas_sloped_lines(None) == 0
    # a figure that explodes mid-count -> -1 -> the veto never fires on doubt
    boom = type("Boom", (), {"axes": property(lambda s: 1 / 0)})()
    assert _count_incanvas_sloped_lines(boom) == -1
