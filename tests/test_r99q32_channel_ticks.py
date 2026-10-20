"""R99q32b — every leg of the announce card links to its own hit and ticks.

His 10-20, verbatim: «هیت ۱ لینک میشه به هیت ۱ و هیت یک پیام باید تیک بخوره
هیت ۲ به هیت دو .. ۳ به هیت ۳ .. استاپ به استاپ .. و در نهایت به نتیجه نهایی
... قبلا فقط به نتیجه نهایی لینک میشد و بصورت زنده نمیشد بررسی کرد».

The card carried ONE link (latest result), so a member could never see which
legs had printed. Now each leg owns a link and a live tick.
"""
import bot.messages_v7 as M


def _card():
    return (
        "✅ <b>سیگنال تأییدشده</b>   🆔 <code>VIVA-PINWALL-K880136</code>\n\n"
        "🏦 <b>ZECUSDT</b> • 30m • SWING • 🟢 LONG\n"
        "🔰 ورود: <b>1,155.01</b>\n"
        "⛔️ استاپ: <b>1,129.02</b>\n\n"
        "🎯 <b>اهداف</b>\n"
        "• TP1: <b>1,170.41</b> · 1.33٪ فاصله · 40%\n"
        "• TP2: <b>1,185.81</b> · 2.67٪ فاصله · 30%\n"
        "• TP3: <b>1,201.21</b> · 4.00٪ فاصله · 30%\n\n"
        "🔗 آخرین نتیجه: <i>در انتظار نتیجه</i>\n\n"
        "📌 <b>VIVAMON-Labs-Pro</b>")


def test_tp1_hit_ticks_tp1_and_links_it():
    out = M._tf_channel_apply_mark(_card(), "tp1", "https://t.me/c/1/101")
    assert "• ✅ TP1:" in out
    assert '<a href="https://t.me/c/1/101"><b>1,170.41</b></a>' in out
    # the other legs stay untouched
    assert "• TP2: <b>1,185.81</b>" in out
    assert "• ✅ TP2" not in out


def test_each_leg_ticks_independently():
    out = _card()
    for i, url in ((1, "u1"), (2, "u2"), (3, "u3")):
        out = M._tf_channel_apply_mark(out, f"tp{i}", url)
    assert out.count("✅ TP") == 3
    assert "u1" in out and "u2" in out and "u3" in out


def test_a_second_hit_never_double_ticks():
    once = M._tf_channel_apply_mark(_card(), "tp1", "u1")
    twice = M._tf_channel_apply_mark(once, "tp1", "u2")
    assert twice == once


def test_stop_ticks_its_own_row():
    out = M._tf_channel_apply_mark(_card(), "stop", "https://t.me/c/1/109")
    assert "🛑 استاپ:" in out
    assert "⛔️ استاپ:" not in out
    assert '<a href="https://t.me/c/1/109"><b>1,129.02</b></a>' in out


def test_an_unknown_leg_is_a_no_op():
    assert M._tf_channel_apply_mark(_card(), "nonsense", "u") == _card()
    assert M._tf_channel_apply_mark(_card(), "final", "u") == _card()


def test_a_missing_row_never_corrupts_the_card():
    bare = "✅ <b>سیگنال تأییدشده</b>\n📌 <b>VIVAMON-Labs-Pro</b>"
    assert M._tf_channel_apply_mark(bare, "tp1", "u") == bare
    assert M._tf_channel_apply_mark(bare, "stop", "u") == bare


def test_the_three_hit_paths_call_the_tick_engine():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert src.count("tf_channel_mark_hit(") >= 4      # def + tp + stop + final
    assert 'tf_channel_mark_hit(str(signal.get("public_code") or ""),\n                            str(event_key).lower()' in src
    assert 'tf_channel_mark_hit(str(event.get("public_code") or ""), "stop"' in src


def test_techclassic_now_rides_the_mid_board(monkeypatch):
    monkeypatch.setattr(M, "CHAT_ID_SWING_SHORT", "-1001")
    monkeypatch.setattr(M, "CHAT_ID_SWING_MID", "-1002")
    monkeypatch.setattr(M, "CHAT_ID_SWING_LONG", "-1003")
    assert M._setup_announce_channel("TECHCLASSIC") == "-1002"
    assert M._setup_announce_channel("ALBROX") == "-1002"
    assert M._setup_announce_channel("TLBREAK") == "-1002"
    assert M._setup_announce_channel("PINVAL") == "-1001"


def test_a_missing_channel_is_named_in_the_log():
    src = open("bot/messages_v7.py", encoding="utf-8").read()
    assert "announce skipped" in src
    assert "CHAT_ID_TF_15M_1H / CHAT_ID_TF_2H_4H / CHAT_ID_TF_1D" in src
