"""R99q31e — each engine names the structure it trades.

His 10-20: «نام‌گذاری پترن در موتورهای زون و آلبروکس». ALBROX and the zone
lane never draw a classic pattern, so `engine_stamp` left `law_slug` empty and
the caption block stayed silent. The engines now name their OWN structure —
without ever overriding a law slug a real classic pattern produced.
"""
from analysis.pattern_law import ENGINE_STRUCTURE, engine_stamp, engine_structure


def test_albrox_names_its_spike_and_base():
    md = {}
    out = engine_structure("ALBROX", md)
    assert out["structure_slug"] == "ALBROX_SPIKE_BASE"
    assert out["structure_name_fa"] == "اسپایک و بیس"
    assert md["structure_name_fa"] == "اسپایک و بیس"
    assert md["pattern_label_fa"] == "اسپایک و بیس"


def test_zone_lanes_all_share_one_zone_name():
    for code in ("PINVAL", "PINWALL", "ZONE", "RANGE"):
        assert engine_structure(code, {})["structure_slug"] == "ZONE_REACTION"


def test_a_real_law_slug_is_never_overwritten():
    md = {"law_slug": "WEDGE_FALLING"}
    out = engine_structure("ALBROX", md)
    assert out == {"structure_slug": "", "structure_name_fa": ""}
    assert "structure_name_fa" not in md
    assert "pattern_label_fa" not in md


def test_engine_stamp_sets_the_structure_when_no_pattern_was_drawn():
    md = {}
    info = engine_stamp(md, None, "ALBROX")
    assert info["law_slug"] == ""
    assert info["structure_slug"] == "ALBROX_SPIKE_BASE"
    assert md["structure_name_fa"] == "اسپایک و بیس"


def test_engine_stamp_keeps_silence_for_an_unknown_engine():
    md = {}
    info = engine_stamp(md, None, "WHATEVER")
    assert info["structure_slug"] == ""
    assert "structure_name_fa" not in md


def test_the_caption_prints_structure_only_when_there_is_no_slug():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    i_slug = src.index('if slug:\n            from analysis.pattern_law import label_fa')
    i_struct = src.index('🧩 ساختار')
    assert i_struct > i_slug, "the structure line must live in the else-branch"
    assert "structure_name_fa" in src


def test_every_table_entry_is_a_slug_and_a_fa_name():
    for code, (slug, fa) in ENGINE_STRUCTURE.items():
        assert slug and slug == slug.upper()
        assert fa and any("\u0600" <= ch <= "\u06ff" for ch in fa)
