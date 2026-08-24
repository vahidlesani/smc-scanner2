"""Contract tests for exact final-result Telegram linking."""
from unittest.mock import patch

from bot.messages_v7 import _final_lifecycle_anchor


def test_initial_stop_loss_links_only_to_its_confirmed_message():
    event = {"signal_id": "position-old", "result": "LOSS", "hit_index": 0, "pro_message_id": 901}
    with patch("bot.messages_v7._exact_event_message_id", side_effect=lambda sid, key, fallback=0: 901 if key == "CONFIRMED" else 0) as lookup:
        assert _final_lifecycle_anchor(event) == 901
    lookup.assert_called_once_with("position-old", "CONFIRMED", 901)


def test_protected_exit_after_tp2_links_to_that_positions_tp2_not_same_symbol_new_trade():
    event = {"signal_id": "position-10pm", "result": "WIN", "hit_index": 2, "pro_message_id": 999}
    with patch("bot.messages_v7._exact_event_message_id", side_effect=lambda sid, key, fallback=0: 444 if (sid, key) == ("position-10pm", "TP2") else 0) as lookup:
        assert _final_lifecycle_anchor(event) == 444
    lookup.assert_called_once_with("position-10pm", "TP2")


def test_full_ladder_win_links_to_tp5():
    event = {"signal_id": "position-a", "result": "WIN", "hit_index": 5, "pro_message_id": 100}
    with patch("bot.messages_v7._exact_event_message_id", return_value=505) as lookup:
        assert _final_lifecycle_anchor(event) == 505
    lookup.assert_called_once_with("position-a", "TP5")
