# High 2 Long Detector Design

**Date:** 2026-04-14

## Goal

Add an active `high2` long-pattern detector to the existing screening pipeline so High 2 setups can be detected, scored, ranked, and converted into decision-ticket trade plans using the same interfaces as the current pattern modules.

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

`high2` should follow that contract rather than introducing a parallel signal engine.

## Detection Approach

Use an explicit candle-sequence state machine:

1. detect bullish context (`Always In Long`)
2. detect a qualified pullback
3. detect the first breakout attempt (`H1`)
4. confirm `H1` failure from lack of follow-through
5. detect the second breakout attempt (`H2`)

This is preferred over a pivot-only or threshold-only design because the requested pattern definition is sequential and candle-specific.

## Pattern Definition

### 1. Always In Long (AIL)

The setup must begin in bullish context:
- at least 3 consecutive bars making both higher highs and higher lows
- bullish majority in the recent trend window before pullback, target threshold `>= 4` bullish closes out of the last `6`
- shallow retracement relative to the prior bull leg, with preferred retracement `< 50%`

Hard reject:
- no clear higher-high / higher-low structure
- context behaves like a trading range

### 2. Pullback

The pullback must be a pause, not a reversal:
- `2` to `5` consecutive bearish or sideways bars
- sideways bars may overlap prior range and fail to extend upward
- pullback depth must stay `<= 60%` of the prior bull leg

Hard reject:
- pullback depth `> 60%`
- strong bear momentum during pullback

Strong bear momentum means one or more of:
- outsized bear real bodies versus recent bars
- repeated closes near bar lows
- expanding downward ranges

### 3. High 1 (H1)

After the pullback, `H1` is the first breakout attempt:
- first bar whose high breaks above the prior bar's high
- weak `H1` bars are still recorded if the breakout occurred

### 4. H1 Failure

`H1` must fail before `H2` is valid:
- inspect the next `1` to `3` bars after `H1`
- fail if those bars do not produce meaningful follow-through

Meaningful follow-through is absent when:
- no decisive higher high beyond `H1`
- no strong bull continuation close
- action turns bearish or stalls in a weak tight range

### 5. High 2 (H2)

`H2` is the second bullish breakout attempt after the failed `H1`:
- first later bar that breaks above `max(H1 high, recent swing high)`
- signal bar must not be weak

Hard reject:
- small-body signal bar
- long upper wick
- breakout that only marginally clears the trigger

Confidence boost:
- strong bull bar
- close near high
- higher breakout volume
- tight prior trend with small pullbacks

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
- `prior_leg_height`
- `trend_score`
- `pullback_score`
- `h1_failure_score`
- `signal_score`
- `aggressive_stop`
- `prior_swing_target`
- `measured_move_target`
- `minimum_rr_target`
- optional future flags such as `ema20_filter_passed` and `atr_filter_passed`

## Confidence Model

Use weighted scoring after hard rejects:

- `0.35` trend quality
- `0.25` pullback quality
- `0.20` H1 / H1-failure quality
- `0.20` H2 signal-bar quality

Adjustments:
- add confidence for breakout volume above recent average
- add confidence for tighter trend structure
- subtract confidence for marginal breakout quality
- subtract confidence for retracement close to the rejection boundary

The final score is normalized to `0.0..1.0`.

## Strategy Integration

`high2` is a normal pipeline pattern, not a special case.

### Entry

Use the standard breakout buffer style used by non-base detectors:
- `entry = h2_high * 1.0005`

### Stop

Default stop:
- `stop = pullback_low`

Aggressive stop:
- `h2_low`

The aggressive stop is stored in metadata only for now.

### Target

To keep the pipeline deterministic, strategy output must produce one canonical target:

- `prior_swing_target = prior_swing_high`
- `minimum_rr_target = entry + 2R`
- `measured_move_target = entry + prior_leg_height`
- `target = max(prior_swing_target, minimum_rr_target, measured_move_target)`

Where:
- `R = entry - stop`
- `prior_leg_height` is the price height of the bull leg preceding the pullback

### Risk Table

Add:
- `RISK_REWARD["high2"] = 2.0`

This keeps the strategy aligned with the requested minimum `2:1` reward-to-risk floor.

## Implementation Notes

- add `patterns/high2.py`
- update `patterns/__init__.py` to include `High2Detector`
- update `strategies.py` for `high2` entry/stop/target handling
- keep optional EMA20 / ATR / multi-timeframe logic out of the default implementation
- do not modify disabled-detector behavior

## Test-First Plan

### Pattern Tests

Create `tests/test_patterns/test_high2.py` with cases that:
- detect a clean valid H2 sequence
- reject trading-range structure
- reject pullback retracement above `60%`
- reject strong bear pullback momentum
- reject weak H2 signal candles
- prefer the best valid H2 when multiple candidates exist
- emit required pivots, dates, and metadata

### Registry Tests

Extend `tests/test_patterns/test_registry.py` to prove:
- `high2` is included in `detect_all()`
- `channel` and `support_resistance` stay excluded

### Strategy Tests

Extend `tests/test_strategies.py` to prove:
- `high2` breakout uses `h2_high`
- `high2` stop uses `pullback_low`
- `high2` target is at least `2R`
- entry remains above stop and target remains above entry

### Pipeline / CLI Tests

Extend the existing integration path to prove:
- `high2` flows into decision-candidate creation without special handling
- stale `high2` results are filtered by existing recency rules

## Risks

- H2 detection is more discretionary than the current base patterns, so false positives are the main risk.
- Tight hard-reject rules are preferable to broad scoring because the user requested low-noise signals.
- Synthetic test fixtures must be explicit and readable so failure modes stay diagnosable.

## Acceptance Criteria

The design is complete when:
- `high2` is a first-class active detector
- only qualified H2 long setups are emitted
- the detector returns stable `PatternResult` geometry
- `strategies.strategy()` can derive deterministic trade levels from `high2`
- tests cover both valid and reject paths with no network access
