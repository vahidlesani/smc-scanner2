from analysis.viva_tlbreak_state import VivaTLState, advance


def test_viva_state_full_sequence_and_roundtrip():
    s=VivaTLState()
    for e in ("VALID_PATTERN","BREAKOUT","RETEST","REJECTION","MICRO_BOS","CONFIRM"):
        s=advance(s,e,max_retest_bars=16)
    assert s.stage == "S6_CONFIRMED"
    restored=VivaTLState.from_payload(s.payload())
    assert restored.stage == "S6_CONFIRMED"


def test_viva_state_retest_window_expires_only_by_profile_window():
    s=advance(VivaTLState(),"BREAKOUT",max_retest_bars=2)
    s=advance(s,"BAR",max_retest_bars=2)
    s=advance(s,"BAR",max_retest_bars=2)
    assert s.stage == "S2_BREAKOUT"
    s=advance(s,"BAR",max_retest_bars=2)
    assert s.stage == "CANCELLED"
    assert s.cancel_reason == "RETEST_WINDOW_EXPIRED"
