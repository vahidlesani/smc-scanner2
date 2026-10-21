"""r49 — ONE uniform alert-chart caption for every setup (Viva 09-27 05:43:
«کپشن چارت پینوال رو برداری مثل بقیه بشه … همه شبیه هم باشن … هر ستاپ واسه
خودش»). The PINWAL special caption (zone/polarity/rules on the photo) is
dead; the zone info already lives in the message text."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_alert_chart_uses_the_uniform_caption():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    part = src.split("def send_educational_setup")[1].split("def ")[0]
    # the standard four-line template, applied unconditionally
    assert 'f"📚 {_e(candidate.symbol)} • {_e(candidate.style)} • {_e(candidate.setup_code)}\\n"' in part
    assert '⛔ تأیید ورود نیست' in part
    # the pin special caption is gone
    assert 'پین‌بار ' not in part.split("caption = (")[0]
    assert '🚨 {_e(candidate.symbol)} • {_e(candidate.trigger_timeframe)} • پین‌بار' not in part
    assert 'pin_zone_fa' not in part


def test_caption_helpers_still_exist():
    src = open(os.path.join(REPO, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_iran_time" in src and "_public_code" in src
