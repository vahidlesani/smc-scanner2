# Viva's GOOD references — 10-12 (today's excellent spot charts, his bar)

His verdicts, verbatim: DOT 8H «عالی و زیبا و تمیز», ETHFI 12H «عالی و
فوق‌العاده تمیز», ONDO 4H «بی نهایت عالی و زیبا و تمیز», DOT 12H «عالی عالی
عالی». JUP/ETC/ZEC trends correct with hand-drawn improvements (see below).

1. `spot_JUP_4H-ascending-channel-CONFIRMED.jpg` — ascending channel; his
   orange hand-line: the UPPER trend must extend to the new base (price
   crossed it) instead of cutting through Oct-06/08 candles.
2. `spot_DOT_8H-sym-triangle-BREAK_UP.jpg` — clean symmetrical triangle.
3. `spot_ETHFI_12H-sym-triangle-BREAK_DOWN.jpg` — clean breakdown, no long box.
4. `spot_ETC_4H-major-TL-BREAK_UP.jpg` — trend correct; he prefers the
   hand-drawn descending CHANNEL over the single TL. Axis shows ONE price
   (the sparse-axis bug: old-mpl LogLocator subs).
5. `spot_ONDO_4H-descending-channel-CONFIRMED.jpg` — the AXIS gold standard
   (9 linear-nice labels); lower trend should respect wick lows (his brown
   line); the target box was MISSING (fa-name breakdown bug) — must draw.
6. `spot_ZEC_4H-falling-wedge-BREAK_UP.jpg` — upper must extend to the new
   base (his pink line); lower is CORRECT (the dip was a daily fakeout).
7. `spot_DOT_12H-ascending-triangle-CONFIRMED.jpg` — ascending triangle.
8. `BADREF_geo_8H-skybox-TOUCH.png` — the BAD one: +65.8% sky box (ancient
   ceiling), lines through price middle. Box must end at the same-TF
   structural ceiling (~1.02, his blue line); lines refit to new bases
   (his blue/green lines); candles never squash.

Ops note (10-12 forensics): these 8 charts prove TWO live bots posting to
one channel — old-mpl renders (sparse subs axis: DOT/ETHFI/ETC/DOT12H) vs
new-mpl renders (dense auto axis: JUP/ZEC/ONDO/GEO). Same code line, two
behaviors. Consolidate to ONE deploy.
