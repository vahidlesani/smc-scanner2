"""R99q40e — «چرا هشدار نمیاد» half two: a card born behind the market.

Measured (production DB, 2026-10-21):

    ZEC  viva-ZEC-SW-TLBREAK-10210301-18AF  minted 03:01:46Z
         LONG  entry 1147.6914  TP1 1159.168  TP2 1205.076
         tape close at mint 1260.58  → the FIRST target sat 101 points BEHIND
         the market; the card could never become a trade.
    RENDER viva-RENDER-SW-TLBREAK-10210305-949A  minted 03:05:20Z
         LONG  entry 1.845  TP1 1.8625127  tape close 1.851
         → plan ahead of price; it confirmed at 03:30 and published.

The mint-time twin of ENTRY_AFTER_TARGET: never publish a chain whose first
target is already on the wrong side of the live close.
"""
import os

import pytest


def test_zec_shape_is_refused():
    from analysis.setups_experimental import plan_already_past_target
    assert plan_already_past_target("LONG", 1260.58, 1159.1682968085106) is True


def test_render_shape_is_allowed():
    from analysis.setups_experimental import plan_already_past_target
    assert plan_already_past_target("LONG", 1.851, 1.8625127697841726) is False


def test_short_mirror():
    from analysis.setups_experimental import plan_already_past_target
    assert plan_already_past_target("SHORT", 1138.0, 1150.0) is True
    assert plan_already_past_target("SHORT", 1160.0, 1140.0) is False


def test_bad_numbers_never_block_a_mint():
    from analysis.setups_experimental import plan_already_past_target
    assert plan_already_past_target("LONG", 0.0, 10.0) is False
    assert plan_already_past_target("LONG", 10.0, 0.0) is False
    assert plan_already_past_target("LONG", None, 10.0) is False


def test_the_guard_is_wired_into_the_tlbreak_mint():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "analysis", "setups_experimental.py"),
               encoding="utf-8").read()
    body = src[src.find("def detect_viva_tlbreak"):]
    body = body[:body.find("\ndef _parent_countertrend_1009")]
    assert "plan_already_past_target(" in body
    assert "TLBREAK mint skipped" in body
