# Implementation sequence

1. Parse config and expose an isolated `VivaTLBreakConfig`.
2. Build confirmed-pivot regression line validation.
3. Classify trend/channel/wedge/triangle/horizontal SR.
4. Build closed breakout → retest/base → 5M BOS state machine.
5. Add TLBREAK-only score components and chart overlays.
6. Add per-setup Railway env toggle and Telegram setup-management controls.
7. Replay each pattern class separately before enabling.
