# High 2 Long Detector Design

**Date:** 2026-04-14

## Goal

Add an active `high2` long-pattern detector to the existing screening pipeline so High 2 setups can be detected, scored, ranked, and converted into decision-ticket trade plans using the same pattern-result interfaces as the current pattern modules.

## Scope

In scope:
- new `patterns.high2.High2Detector`
- registry integration through `patterns.detect_all()`
- deterministic `strategies.py` support for `high2`
- test coverage for detection, strategy geometry, registry inclusion, and pipeline flow

Out of scope:
- reviving disabled `channel` or `support_resistance`
- standalone signal-only CLI
- broker execution
- optional EMA20, ATR, or multi-timeframe filters as default gates

## Why This Fits The Repo

This repo already treats chart setups as `PatternResult` producers that flow through:
- `patterns.detect_all()`
- `strategies.strategy()`
- `main.py` candidate building
- decision-ticket ranking and sizing

`high2` should follow that contract rather than introducing a parallel signal engine. It remains a normal detector in the registry and candidate pipeline, but it requires a custom target branch in `strategies.strategy()` because its canonical target is not the default `entry + R * risk_reward` formula.

Detector responsibilities stop at emitting a stable `PatternResult`. Strategy responsibilities begin when entry, stop, target, and `TradeSetup` fields are derived. The design must not require `strategies.strategy()` to mutate the detector output in place.

## Detection Approach

Use an explicit candle-sequence state machine:

1. detect bullish context (`Always In Long`)
2. detect a qualified pullback
3. detect the first breakout attempt (`H1`)
4. confirm `H1` failure using fixed quantitative follow-through rules
5. detect the second breakout attempt (`H2`)

This is preferred over a pivot-only or threshold-only design because the requested pattern definition is sequential and candle-specific.

## Lookback And Active Window

Scan all bars in the input `df` passed to the detector, which is up to 90 calendar days as provided by `detect_all()`.

The detector may evaluate candidate sequences anywhere inside the input window.

There is no detector-specific 3-bar freshness rule. Freshness stays aligned with the existing pipeline behavior in `main.py`:
- `PatternResult.detected_on` remains the last bar date in the input `df`
- `pivot_dates["h2_high"]` and `pivot_dates["h2_low"]` must both be the H2 bar date
- downstream recency filtering continues to use the existing business-day logic applied to pivot dates; specifically, `main.py` filters any candidate whose most recent pivot date is more than 10 business days before `latest_date` from the symbol dataframe (the same rule applied to all other active patterns)

## Pattern Definition

### 1. Always In Long (AIL)

The setup must begin in bullish context. Both conditions must be satisfied:
- at least 3 consecutive bars making both higher highs and higher lows
- bullish majority in the recent trend window before pullback, with `>= 4` bullish closes out of the last `6`

For a given candidate pullback, `ail_start_idx` is defined exactly as:
- start from `pullback_start_idx - 1`
- walk backward while each bar continues the same contiguous higher-high / higher-low run
- `ail_start_idx` is the first bar in that most recent contiguous HH/HL run
- the run length from `ail_start_idx` to `pullback_start_idx - 1` must be at least `3` bars, otherwise the candidate is invalid

The 6-bar window for the bullish-close check is `[pullback_start_idx - 6, pullback_start_idx - 1]`. This window may extend before `ail_start_idx`; bars before `ail_start_idx` are included in the count. If `pullback_start_idx < 6`, the window is `[0, pullback_start_idx - 1]` (use all available bars before the pullback).

Context quality also evaluates retracement relative to the prior bull leg:
- retracement `0%` to `50%` receives full pullback-quality credit
- retracement `> 50%` to `60%` is allowed but penalized in scoring
- retracement `> 60%` is a hard reject

Hard reject:
- no clear higher-high / higher-low structure
- bullish-close count below `4` of the last `6`
- context behaves like a trading range

For this design, `context behaves like a trading range` is defined as:
- `prior_leg_height < 3.0 * median_bar_range_context`

Where:
- `prior_leg_height = prior_swing_high - df.Low[ail_start_idx]`
- `median_bar_range_context` is the median of `(high - low)` over the bars from `ail_start_idx` to `pullback_start_idx - 1`, inclusive

If any bar in that context window has `high == low`, it contributes a range of `0.0` to the median calculation; this does not crash the candidate.

### 2. Pullback

The pullback must be a pause, not a reversal:
- `2` to `5` consecutive bearish or sideways bars
- pullback depth must stay `<= 60%` of the prior bull leg

Where `retracement_pct = (prior_swing_high - pullback_low) / prior_leg_height`, and `prior_leg_height = prior_swing_high - df.Low[ail_start_idx]`. A value of `0.60` means the pullback erased `60%` of the prior bull leg range.

A sideways bar is defined as:
- `abs(close - open) / (high - low) < 0.30`
- `high <= prior_bar_high`

Strong bear momentum is defined per bar as:
- `(open - close) / (high - low) > 0.60`
- `(open - close) > 1.5 * mean_abs_body_20d`

Where `mean_abs_body_20d` is the mean of `abs(close - open)` over the prior 20 bars available before that pullback bar. If fewer than 20 prior bars exist, use all available prior bars. If no prior bars exist, the candidate is invalid.

If any bar used in the sideways-bar, strong-bear-momentum, or H2 signal-bar formulas has `high == low`, the candidate is invalid. This keeps denominator-based rules deterministic and avoids divide-by-zero behavior.

Hard reject:
- pullback depth `> 60%`
- pullback duration `> 5` bars
- any pullback bar satisfies the strong-bear-momentum rule

### 3. High 1 (H1)

After the pullback, `H1` is the first breakout attempt:
- the first bar whose high breaks above the prior bar's high

`H1` is recorded even if the bar is weak, because the failure test happens after the breakout attempt exists.

### 4. H1 Failure

`H1` must fail before `H2` is valid.

Use a fixed two-bar confirmation window:
- inspect bars in `[h1_idx + 1, h1_idx + 2]`
- if any bar in that window closes above `h1_high * 1.001`, `H1` did not fail
- if any bar in that window has `high > h1_high * 1.003`, `H1` did not fail
- otherwise `H1` is classified as failed

If the input does not contain two bars after `H1`, the candidate is invalid because H1 failure cannot be confirmed.

### 5. High 2 (H2)

`H2` is the second bullish breakout attempt after the failed `H1`:
- the first later bar that breaks above `trigger_level`
- `trigger_level = max(h1_high, recent_swing_high)`

For this design, `recent_swing_high` is the same value as `prior_swing_high`.

`H2` must satisfy `h2_idx >= h1_idx + 3` so it starts only after the full H1 failure window has been evaluated.

The H2 signal bar must pass all signal-bar filters:
- small body reject: `(close - open) / (high - low) < 0.30`
- long upper wick reject: `(high - close) / (high - low) > 0.40`
- marginal breakout reject: `(h2_high - trigger_level) / trigger_level < 0.001`

Hard reject:
- H2 bar fails any signal-bar threshold above
- H2 bar does not satisfy `h2_idx >= h1_idx + 3`

## Candidate Selection

If the lookback contains multiple valid sequences:
- keep the highest-confidence valid candidate
- break ties by favoring the more recent `H2`

If no full sequence passes the hard filters:
- return `None`

## Data Contract

The detector returns one `PatternResult` with:

- `pattern = "high2"`
- `ticker = <input ticker>`
- `confidence = 0.0..1.0`
- `detected_on = last bar date in input df`

### Pivots

`pivots` must include:
- `prior_swing_high`
- `pullback_low`
- `h1_high`
- `h2_high`
- `h2_low`

`prior_swing_high` is defined exactly as:
- the highest high from `ail_start_idx` to `pullback_start_idx - 1`, inclusive

`pullback_low` is defined as:
- the lowest low from `pullback_start_idx` to `pullback_end_idx`, inclusive

`h1_high` is:
- the high of the H1 bar

`h2_high` is:
- the high of the H2 bar

`h2_low` is:
- the low of the H2 bar

### Pivot Dates

`pivot_dates` mirrors the pivot keys above.

### Metadata

`metadata` carries diagnostics needed for review and future chart annotations:
- `ail_start_idx`
- `pullback_start_idx`
- `pullback_end_idx`
- `h1_idx`
- `h2_idx`
- `retracement_pct`
- `bullish_ratio`
- `volume_ratio`
- `ail_start_price_low`
- `prior_leg_height`
- `trend_score`
- `pullback_score`
- `h1_failure_score`
- `signal_score`

`ail_start_price_low` is defined as:
- `df.Low[ail_start_idx]`, the low of the first bar in the AIL sequence

`pullback_end_idx` is defined as:
- `h1_idx - 1` (the last bar of the pullback phase, immediately before H1)

`prior_leg_height` is defined as:
- `prior_swing_high - df.Low[ail_start_idx]` (the full height of the prior bull leg, from the AIL starting low to the prior swing peak). This is the correct measured-move projection distance in Al Brooks context.

Optional future flags such as `ema20_filter_passed` and `atr_filter_passed` may be added later, but they are not part of the default implementation.

Strategy-derived values are not part of the detector contract. In particular, the detector does not populate:
- `prior_swing_target`
- `measured_move_target`
- `minimum_rr_target`
- `prior_swing_below_entry`

Those values are derived inside `strategies.strategy()` if needed during target calculation.

Sub-score definitions:
- `trend_score`: normalized trend-quality component before weighting, in `0.0..1.0`
- `pullback_score`: normalized pullback-quality component before weighting, in `0.0..1.0`
- `h1_failure_score`: normalized H1-failure component before weighting, in `0.0..1.0`
- `signal_score`: normalized H2 signal-bar component before weighting, in `0.0..1.0`
- `retracement_pct`: `(prior_swing_high - pullback_low) / prior_leg_height`, where `prior_leg_height = prior_swing_high - df.Low[ail_start_idx]`; this is the fraction of the prior bull leg retraced by the pullback

## Confidence Model

Use weighted scoring after hard rejects.

Base weighted score:
- `0.35 * trend_score`
- `0.25 * pullback_score`
- `0.20 * h1_failure_score`
- `0.20 * signal_score`

Base sub-score definitions:
- `trend_score = 1.0` when the AIL structure is present and bullish-close ratio is at least `4/6`
- `pullback_score = 1.0` when pullback depth is `<= 50%` and duration is `2` to `5` bars with no strong bear momentum
- `pullback_score = 0.7` when pullback depth is `> 50%` and `<= 60%` and other pullback conditions are met
- `h1_failure_score = 1.0` when H1 failure is confirmed by the fixed two-bar rule
- `signal_score = 1.0` when the H2 bar passes all hard filters

Adjustments to raw score:
- `+0.05` if `volume_ratio > 1.5`, where `volume_ratio = df.Volume[h2_idx] / mean(df.Volume[h2_idx - 10 : h2_idx])`; if fewer than 10 bars precede `h2_idx`, use all available bars before `h2_idx`
- `+0.05` if the AIL leg from `ail_start_idx` to `pullback_start_idx - 1` contains no bearish bars with strong-bear-momentum characteristics
- `-0.05` if `retracement_pct > 0.50 and retracement_pct <= 0.60`
- `-0.05` if H2 breakout distance is in the low-quality band `0.001 <= (h2_high - trigger_level) / trigger_level < 0.002`
- `-0.05` if pullback duration is exactly `5` bars

For the AIL confidence boost, compute `mean_abs_body_20d` using the 20 bars immediately preceding `ail_start_idx`. If fewer than 20 bars precede `ail_start_idx`, use all available prior bars.

This makes the operational meaning of the retracement preference explicit:
- retracement `0%` to `50%`: full `pullback_score`, no retracement penalty
- retracement `> 50%` to `60%`: `pullback_score = 0.7` and raw score gets `-0.05`
- retracement `> 60%`: hard reject

Both the `pullback_score` reduction and the raw score adjustment apply simultaneously for `50%` to `60%` retracements; the combined effect reduces confidence by `0.125` relative to a pullback with depth `<= 50%`.

Final normalization:
- `confidence = min(1.0, max(0.0, raw_score))`

## Strategy Integration

`high2` is a first-class detector in the normal pipeline, but it requires a custom branch in `strategies.strategy()` for target calculation.

### Entry

Use the standard breakout buffer style used by non-base detectors:
- `entry = h2_high * 1.0005`

### Stop

Default stop:
- `stop = pullback_low`

Aggressive stop:
- `aggressive_stop = h2_low`

The aggressive stop is derived from detector pivots during strategy calculation. It is not a required detector metadata field. To access it, use `result.pivots["h2_low"]` directly.

### Target

`high2` does not use the default strategy target formula. It requires a custom branch in `strategies.strategy()`.

Compute:
- `R = entry - stop`
- `prior_swing_target = prior_swing_high`
- `minimum_rr_target = entry + 2R`
- `measured_move_target = entry + prior_leg_height`

Canonical target:
- if `prior_swing_high > entry * 1.01`, `target = max(prior_swing_target, minimum_rr_target, measured_move_target)`
- if `prior_swing_high <= entry * 1.01`, exclude `prior_swing_target` from the max and use `target = max(minimum_rr_target, measured_move_target)`

### Risk Table

Add:
- `RISK_REWARD["high2"] = 2.0`

For `high2`, this constant defines `minimum_rr_target` only. It does not replace the custom target formula above.

`TradeSetup.risk_reward` remains `RISK_REWARD["high2"]`, which is the configured minimum reward-to-risk floor of `2.0`. The realized reward-to-risk implied by the final target may be greater than `2.0` and is derived as:
- `(target - entry) / (entry - stop)`

No `TradeSetup` contract change is required for `high2`.

This means `TradeSetup.risk_reward` continues to represent the configured floor, not the realized reward-to-risk of the final target. If the CLI later needs to display realized reward-to-risk for H2, that is a separate presentation change and is not part of this detector spec.

## Implementation Notes

- add `patterns/high2.py`
- update `patterns/__init__.py` to include `High2Detector`
- update `patterns.detect_all()` integration so `high2` is active
- update `strategies.py` with a `high2` special case for target handling
- keep optional EMA20 / ATR / multi-timeframe logic out of the default implementation
- do not modify disabled-detector behavior

## Test-First Plan

### Pattern Tests

Create `tests/test_patterns/test_high2.py` with cases that:
- detect a clean valid H2 sequence
- reject trading-range structure
- reject pullback retracement above `60%`
- apply the `-0.05` retracement penalty for `50%` to `60%` retracements
- reject pullback duration above `5` bars
- reject strong bear pullback momentum using the explicit body-size rule
- reject H1 candidates where a follow-through bar closes above `h1_high * 1.001`
- reject H1 candidates where a follow-through bar has `high > h1_high * 1.003`
- reject weak H2 signal candles using each hard threshold
- reject an H2 bar at `h1_idx + 1` because it is inside the H1 failure window
- accept an H2 bar at `h1_idx + 3` when all other conditions pass
- prefer the best valid H2 when multiple candidates exist
- emit required pivots, dates, and metadata
- emit `pivot_dates["h2_high"]` and `pivot_dates["h2_low"]` equal to the H2 bar date so existing pipeline recency filtering works correctly
- emit `prior_leg_height` in metadata equal to `prior_swing_high - df.Low[ail_start_idx]`
- emit `ail_start_idx` equal to the first bar of the most recent contiguous HH/HL run before the pullback
- emit `pullback_score = 0.7` in metadata when pullback depth is exactly `55%`
- assert that a `55%` pullback applies both `pullback_score == 0.7` and the `-0.05` raw retracement adjustment in the confidence calculation
- count pre-AIL bars in the 6-bar bullish-close window when the AIL segment is shorter than 6 bars
- assert `volume_ratio` uses `df.Volume[h2_idx - 10 : h2_idx]` as the denominator window, or all available prior bars when fewer than 10 exist
- assert `retracement_pct` is computed as `(prior_swing_high - pullback_low) / prior_leg_height` using a known fixture where `prior_swing_high = 110.0`, `pullback_low = 103.0`, `ail_start_low = 95.0` so `retracement_pct ≈ 0.467` (passes, no penalty), and where `pullback_low = 99.0` so `retracement_pct ≈ 0.733` (hard reject)
- reject a candidate where the pre-pullback context satisfies `prior_leg_height < 3.0 * median_bar_range_context`
- reject a candidate with `high == low` on a pullback bar or H2 signal bar because denominator-based rules become invalid

### Registry Tests

Extend `tests/test_patterns/test_registry.py` to prove:
- `high2` is included in `detect_all()`
- `channel` and `support_resistance` stay excluded

### Strategy Tests

Extend `tests/test_strategies.py` to prove:
- `high2` breakout uses `h2_high`
- `high2` stop uses `pullback_low`
- `high2` uses the custom target branch rather than the default target formula
- `minimum_rr_target` is computed from `RISK_REWARD["high2"] = 2.0`
- canonical target is `max(prior_swing_target, minimum_rr_target, measured_move_target)` when `prior_swing_high > entry * 1.01`
- `prior_swing_target` is excluded when `prior_swing_high <= entry * 1.01`
- `prior_leg_height` feeds `measured_move_target` using `prior_swing_high - df.Low[ail_start_idx]`
- realized reward-to-risk computed from `(target - entry) / (entry - stop)` is at least `2.0`
- entry remains above stop and target remains above entry

### Pipeline / CLI Tests

Extend the existing integration path to prove:
- `high2` flows into decision-candidate creation without special handling outside detector and strategy integration
- stale `high2` results continue to be filtered by the existing pivot-date business-day recency rule in `main.py`, using the shared `10`-business-day maximum age

## Risks

- H2 detection is more discretionary than the current base patterns, so false positives are the main risk.
- Tight hard-reject rules are preferable to broad scoring because the user requested low-noise signals.
- Synthetic test fixtures must be explicit and readable so failure modes stay diagnosable.
- The custom target branch is intentionally different from the default strategy path and must be covered directly by tests to avoid silent regressions.

## Acceptance Criteria

The design is complete when:
- `high2` is a first-class active detector
- only qualified H2 long setups are emitted
- H1 failure is determined by the fixed two-bar quantitative rule
- H2 cannot begin before `h1_idx + 3`
- stale setups are filtered by the existing pivot-date business-day recency rule already used by the pipeline, with the shared `10`-business-day maximum age
- the detector returns stable `PatternResult` geometry
- `prior_leg_height` is defined as `prior_swing_high - df.Low[ail_start_idx]` and is available in metadata for target calculation
- `strategies.strategy()` can derive deterministic trade levels from `high2` through a documented special-case target branch
- detector metadata excludes strategy-derived target fields, so `PatternResult` can be emitted without strategy side effects
- confidence scoring uses explicit adjustment magnitudes, includes `pullback_score = 0.7` for `> 50%` to `<= 60%` retracements, applies the separate `-0.05` retracement raw adjustment for the same band, and clamps to `0.0..1.0`
- tests cover valid paths, reject paths, bullish-window edge cases, volume-window edge cases, measured-move target edge cases, retracement-formula edge cases, and target edge cases with no network access
