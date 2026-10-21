# VivaSignals Pro chart assets

`vivasignals-logo.png` is the approved transparent geometric gold monogram used on every generated chart. The legacy embedded wordmark was intentionally removed; the renderer adds the current brand name `VivaSignals Pro` separately so it remains sharp and configurable.

Asset requirements for future replacements:

- PNG with alpha transparency
- At least 512×512 (1024×1024 preferred)
- Tight crop with safe padding
- No baked-in obsolete channel name

A different file can be configured with `CHART_LOGO_PATH`; the visible name and optional handle use `CHART_BRAND_NAME` and `CHART_BRAND_HANDLE`.
