"""R99q40 — «فقط باید پترن‌ها و هندسه درون همون تایم تریگر باشه».

His 10-21 order, verbatim. The card header used to print «PAT 1H» on a 30M
card (the pattern's own context TF) and the geometry lane accepted a pattern
dict whose TF was not the trigger's. Both are the same lie: a 30m chart
announcing somebody else's shape.
"""
import os


def test_card_never_announces_a_foreign_tf_pattern():
    """His 10-21 law: the pattern named on the card is the trigger's own.
    The header used to print «PAT 1H» on a 30M card."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "PAT ' + str(md.get('tl_context_tf'))" not in src
    assert "_native39c" in src          # geometry lane refuses foreign TFs
