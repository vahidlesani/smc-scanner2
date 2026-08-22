# VIVA-TLBREAK v1 — isolated personal strategy

**Scope:** Only dynamic trendline, channel, wedge, triangle, and horizontal S/R breakouts. This module must not change PINVAL, RBR/DBD, FVG/IFVG, LSR, SDR, P1234 or any other strategy.

## Source files
- `breakout_strategy_config.json`: submitted breakout specification.
- This README: Viva overrides and implementation decisions.

## Viva decisions (override generic config)
1. **Profiles**
   - Swing: `1D → 4H → 1H`, confirmation `5M`.
   - Daytrade: `4H → 1H → 15M`, confirmation `5M`.
   - No standalone `1M` confirmation for this strategy.
2. **Pattern maturity**
   - 2 pivots = WATCH only, no executable signal.
   - >=3 confirmed pivots + fit residual validation = valid pattern.
3. **Touch model**
   - In-sample validating touches are separate from forward touches.
   - Forward touches are evidence, not fabricated validation.
4. **Entry**
   - Default: breakout + base/retest + rejection + closed 5M micro BOS/MSS.
   - No chase after extension beyond configured ATR cap.
5. **Counter-trend breakouts**
   - Allowed only with full retest and confirmation quality; not hard-rejected solely due to HTF opposition.
6. **Volume**
   - Quality score/confluence, not a hard veto if venue volume data is incomplete.
7. **Stop**
   - Behind the pattern/base pivot plus ATR/spread/5 tick buffer.
8. **Targets / exits**
   - Structural/measured final target feeds the existing 5-part exit ladder.
   - Current global TP/trailing lifecycle remains unchanged.
9. **Lifecycle**
   - New material candidate may coexist before confirmation.
   - Once one signal confirms on the same trigger, it protects that trigger until TP1 or close.
   - No blind 3-candle timeout.

## Activation policy
This module will be controlled separately from all other setups:

```text
VIVA_TLBREAK_ENABLED=true|false
```

It must only be enabled after targeted replay and demo validation. Other setup toggles remain independent.
