# Detected Pattern Debug Charts Design

**Date:** 2026-04-19

## Goal

Add an opt-in debug output mode to `main.py` that saves one combined Plotly `.html` chart per ticker showing all detected chart patterns relevant to setup debugging, including non-actionable detections.

The purpose is detector debugging, not trade review. The charts should make it easy to see whether each detector found the expected structure and where its named pivots landed on the price series.

## Scope

In scope:
- a dedicated `main.py` CLI flag to opt in to saving detected-pattern debug charts
- one combined `.html` debug chart per ticker under the current run directory
- inclusion of non-actionable detected patterns
- combined overlays for:
  - `cup_handle`
  - `double_bottom`
  - `flat_base`
  - `vcp`
  - `high2`
- pivot markers, pivot labels, and pattern-connecting lines
- compact per-pattern status text on the chart
- test coverage for the new save path and renderer behavior

Out of scope:
- changing ticket generation behavior
- changing actionability policy behavior
- adding `.png` or static image export
- saving separate files per detected pattern
- including `support_resistance` or `channel` in the debug-save mode

## Why This Fits The Repo

The repo already has:
- `patterns.detect_all()` for detector output
- `charts.py` for Plotly rendering
- `main.py` run directories and chart saving

This feature should extend those existing flows rather than introduce a second charting system or a separate debug script. The minimal design is:
- keep ticket-backed charts unchanged
- add a second, opt-in save path for detector-debug charts
- reuse the existing Plotly renderer with richer pattern overlays

## CLI Behavior

Add a new flag to `main.py`:

- `--save-detected-pattern-charts`

Behavior:
- default is off
- when enabled, `run()` saves one combined `.html` chart per ticker under:
  - `run_dir / "detected_patterns"`
- the ticker set for this debug-save pass is exactly the final screened ticker set:
  - `filtered["Ticker"]`
- only allowed pattern types are included:
  - `cup_handle`
  - `double_bottom`
  - `flat_base`
  - `vcp`
  - `high2`
- explicitly exclude:
  - `support_resistance`
  - `channel`
- include detected results even if they are non-actionable and never become candidates or tickets

The existing ticket chart path remains unchanged:
- ticket-backed actionable charts continue to save under `run_dir / "charts"`

## Output Granularity

Save one debug chart per ticker, not one chart per pattern.

Reasoning:
- the debugging value comes from seeing overlap and conflicts between detectors on the same price series
- one chart per pattern would create redundant files and make it harder to compare detections on a ticker

File naming:
- `run_dir/detected_patterns/<ticker>.html`

If a ticker has no allowed detected patterns, no file is written.

Reference tickers or any other symbols not present in the final screened `filtered` dataframe are out of scope for this debug-save mode.

## Chart Overlay Behavior

Keep the existing chart layout:
- top row: candlestick chart
- bottom row: volume bars

For each included detected pattern on the ticker chart:
- draw pivot markers at each pivot with both price and date available
- draw text annotations for pivot names
- prefix labels with the pattern name to reduce collisions, for example:
  - `cup_handle:left_high`
  - `double_bottom:middle_high`
  - `flat_base:base_low`
- draw connecting line segments between pivots in pattern-specific order

Use a distinct color per pattern type so combined overlays stay readable.

Use readability controls:
- small annotation font
- semi-transparent markers and lines
- skip pivots that do not have both a pivot price and a pivot date
- avoid guessing x-coordinates for undated pivots

## Pattern-Specific Drawing Order

### Cup With Handle

Connect pivots in this order when present:
- `left_high`
- `cup_low`
- `right_high`
- `handle_low`
- `handle_high`
- `breakout`

Only connect the pivots that exist and have dates.

### Double Bottom

Connect pivots in this order when present:
- `left_high`
- `first_trough`
- `middle_high`
- `second_trough`
- `breakout`

### Flat Base

Connect pivots in this order when present:
- `base_high`
- `base_low`

### VCP

Connect pivots in chronological order using the dated numbered pivots returned by the detector, such as:
- `high_1`
- `low_1`
- `high_2`
- `low_2`
- ...

Sorting should use pivot date first, not string key order alone.

### High 2

Connect pivots in this order when present:
- `prior_swing_high`
- `pullback_low`
- `h1_high`
- `h2_low`
- `h2_high`

## Actionability Status Display

Each combined ticker chart should include a compact status block listing each included detected pattern and whether it is actionable.

Recommended content per row:
- pattern name
- `actionable` or `non_actionable`

Use the existing actionability policy to classify status for display.

Current price for status classification comes from the matching ticker row in the final screened `filtered` summary dataframe, using the same `current_price` field already used by candidate building.

This status block is informational only. It must not change ticket generation or detector output.

## Strategy Levels

Do not draw entry, stop, or target levels on the detected-pattern debug charts by default.

Reasoning:
- the primary debugging need is detector geometry
- strategy overlays would add clutter and compete with the pattern structure
- ticket-backed actionable charts already cover the trade-review surface

The existing ticket chart flow should continue to render strategy and ticket annotations exactly as it does now.

## Main-Flow Integration

`main.py` should gain a new save helper separate from `_save_ticket_charts()`.

Expected behavior:
1. iterate the exact ticker set from `filtered["Ticker"]`
2. slice each ticker dataframe using the existing pattern-history slice helper
3. call `detect_all(df, ticker)`
4. filter results to the allowed pattern set
5. if any allowed results remain, render one combined chart and save it to `detected_patterns/<ticker>.html`

This helper should not depend on whether a ticker produced a candidate or ticket.

This helper should not apply `_is_recent_pattern_result()` gating. If `detect_all()` returns an allowed pattern for a screened ticker, that pattern should appear on the debug chart even if it would be skipped later for candidate or ticket purposes.

## Test Plan

### `tests/test_charts.py`

Add coverage for:
- pattern-prefixed annotation text appears on chart
- connecting geometry is drawn for pattern overlays
- multiple included patterns can render together on one chart
- excluded pattern types are not required for this mode

### `tests/test_main.py`

Add coverage for:
- `--save-detected-pattern-charts` creates `run_dir/detected_patterns/<ticker>.html`
- non-actionable allowed patterns are still saved
- stale-but-detected allowed patterns are still saved in this debug mode
- `support_resistance` and `channel` are excluded from this save path
- multiple allowed patterns for the same ticker produce one combined chart file
- existing ticket chart saving remains unchanged

### Verification Commands

Run targeted tests first:

```bash
rtk pytest tests/test_charts.py tests/test_main.py -q
```

Then run the full suite:

```bash
rtk pytest -q
```

## Assumptions

- This feature applies to the `main.py` decision-ticket flow.
- Plotly `.html` output is sufficient for v1.
- Combined per-ticker debug charts are more useful than one file per pattern.
- The ticker scope is intentionally limited to the final screened `filtered` set for the current run.
- `support_resistance` and `channel` add noise for this debugging use case and are intentionally excluded.
- Existing dirty worktree files not related to this spec remain untouched.
