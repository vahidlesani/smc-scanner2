from types import SimpleNamespace

from analysis.market_intelligence import intelligence_note


def test_intelligence_note_is_additive_and_persian_first():
    c = SimpleNamespace(metadata={
        "market_intelligence": {
            "status": "OK",
            "orderbook": {"imbalance_1_pct": 0.25},
            "derivatives": {"oi_change_2h_pct": 1.4, "funding_rate": 0.0},
            "positioning": {"status": "OK", "long_short_delta": 0.0},
        }
    })
    lines = intelligence_note(c)
    assert lines
    assert all(not line[:1].isascii() or not line[0].isalpha() or line[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" for line in lines)
    assert "دفتر سفارشات" in lines[0]


def test_intelligence_note_does_not_claim_onchain_when_unavailable():
    c = SimpleNamespace(metadata={
        "market_intelligence": {"status": "OK", "orderbook": {}, "derivatives": {}, "positioning": {}}
    })
    lines = intelligence_note(c)
    assert any("پایهٔ ستاپ" in line for line in lines)
