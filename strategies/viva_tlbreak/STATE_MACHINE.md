# VIVA-TLBREAK v1 state machine — implementation contract

This is the binding implementation order. No partial live activation is allowed.

```text
S0_PATTERN_WATCH (2 pivot only)
S1_PATTERN_VALID (>=3 validated pivots per required line)
S2_BREAKOUT_CLOSED (trigger close outside line + score)
S3_RETEST_WINDOW (not extended; within profile window)
S4_REJECTION (pin / engulf / rejection close at line or base)
S5_MICRO_BOS (5m closed confirmation)
S6_CONFIRMED
S7_RUNNER_MANAGEMENT
S8_FAILED_BREAKOUT / CANCELLED
```

## Timeframes

| profile | structure | refine | trigger | confirmation |
|---|---|---|---|---|
| SWING | 1D | 4H | 1H | 5M |
| DAYTRADE | 4H | 1H | 15M | 5M |

## Non-negotiables

- 2 pivot is a WATCH only; never entry.
- >=3 confirmed pivots plus fit residual/touch tolerance are required for a valid line.
- One unresolved candidate never blocks a better structural identity before confirmation.
- Once one identity confirms on a trigger, that trigger is protected until TP1 or close.
- Counter-trend breakouts require full retest + volume + 5m confirmation; no blind veto.
- No blind 3-candle expiry. Pattern/retest windows are profile-specific.
- Existing global TP/trailing lifecycle is used; final target comes from measured move or next structure.
