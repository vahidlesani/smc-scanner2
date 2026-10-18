"""R99q25 — setup-scoped black/white candles and line hierarchy helpers."""


def test_techclassic_market_colors_are_black_white_and_scoped(monkeypatch):
    import bot.messages_v7 as messages

    class FakeMpf:
        @staticmethod
        def make_marketcolors(**kwargs):
            return kwargs

    tc = messages._make_market_colors(FakeMpf, "TECHCLASSIC")
    assert tc["up"] == "#FFFFFF" and tc["down"] == "#111111"
    assert tc["volume"]["up"] == "#AEB4BC"
    # The styling request is intentionally not a global futures palette swap.
    monkeypatch.setattr(messages, "_CANDLE_STYLE", "cryptocove")
    other = messages._make_market_colors(FakeMpf, "TLBREAK")
    assert other["up"] == "#089981" and other["down"] == "#F23645"


def test_spot_candle_colors_are_monochrome():
    from tools.render_spot_cryptocove import spot_candle_colors
    assert spot_candle_colors(True) == ("#FFFFFF", "#111111")
    assert spot_candle_colors(False) == ("#111111", "#111111")
