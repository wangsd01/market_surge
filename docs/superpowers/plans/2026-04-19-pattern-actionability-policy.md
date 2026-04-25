# Pattern Actionability Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate chart pattern detection from trade actionability so detectors return valid detected patterns, while only actionable patterns become trade setups and decision candidates.

**Architecture:** Keep detectors focused on structural pattern existence. Add a small policy layer that evaluates a detected `PatternResult` against `current_price`, setup geometry, and pattern state. `main.build_candidates()` gates candidate creation through that policy before calling `strategy()`.

**Tech Stack:** Python, pandas, pytest, existing `PatternResult`, `TradeSetup`, and `DecisionCandidate` flow.

---

## Summary

Detectors should answer: does this chart pattern exist?

The new actionability policy should answer: is this detected pattern tradable now?

Trade setups and decision candidates are created only after the policy says a detected pattern is actionable. The policy returns both a boolean and an internal reason, so tests can distinguish a pre-breakout buy from a post-breakout pullback without changing the public ticket schema.

Default policy constants:

```python
PRE_BREAKOUT_MAX_BELOW_ENTRY_PCT = 0.10
POST_BREAKOUT_MAX_BELOW_ENTRY_PCT = 0.02
POST_BREAKOUT_MAX_ABOVE_ENTRY_PCT = 0.05
```

Actionability states:

```text
PatternResult
  |-- missing setup geometry -> not actionable: incomplete_geometry
  |-- pre-breakout / handle-forming
  |     |-- current_price <= entry and within 10% below entry -> actionable: pre_breakout_buy
  |     `-- otherwise -> not actionable
  `-- confirmed / complete / post-breakout
        |-- current_price below stop -> not actionable
        |-- current_price between 2% below entry and 5% above entry -> actionable: post_breakout_pullback
        `-- otherwise -> not actionable
```

Research calibration:

- IBD-style breakout setups commonly define a buy zone close to the buy point, often up to 5% above the proper entry.
- Cup-with-handle buy points come from clearing the handle area.
- Pullback entries are post-breakout retests of a broken level, not pre-breakout anticipation.

References:

- https://www.investors.com/how-to-invest/investors-corner/buy-zone-nvidia-stock/
- https://www.nasdaq.com/articles/these-3-stocks-are-near-buys-classic-bullish-pattern-futures-2017-10-02
- https://www.investors.com/how-to-invest/investors-corner/growth-stock-investing-how-to-handle-a-pullback-to-the-buy-point/

## Implementation Changes

### Task 1: Add Actionability Policy Tests

**Files:**
- Create: `tests/test_actionability.py`

- [ ] Write tests for incomplete geometry.
- [ ] Write tests for pre-breakout setups inside and outside the 10% band.
- [ ] Write tests for post-breakout pullbacks inside and outside the 2% below / 5% above band.
- [ ] Write tests for below-stop rejection.
- [ ] Verify tests fail before implementation.

Expected scenarios:

```text
cup_forming without handle pivots -> incomplete_geometry, not actionable
handle_forming at 8% below entry -> pre_breakout_buy, actionable
handle_forming at 11% below entry -> too_far_below_entry, not actionable
confirmed at 3% above entry -> post_breakout_pullback, actionable
confirmed at 6% above entry -> too_extended, not actionable
confirmed at 3% below entry -> too_far_below_entry, not actionable
confirmed below stop -> below_stop, not actionable
```

### Task 2: Expose Shared Strategy Geometry

**Files:**
- Modify: `strategies.py`
- Modify: `tests/test_strategies.py`

- [ ] Add a small public helper, for example `levels_for(result)`, that returns setup geometry used by both policy and `strategy()`.
- [ ] The helper should derive breakout, entry, and stop from existing pattern pivots.
- [ ] Update `strategy()` to reuse the helper.
- [ ] Remove `metadata["actionable"]` as a setup gate.
- [ ] Keep structural `ValueError`s for missing required pivots.
- [ ] Update strategy tests so `strategy()` no longer rejects solely because `metadata["actionable"]` is false.

Do not introduce a broad strategy abstraction. This is a shared geometry helper only.

### Task 3: Implement Actionability Policy

**Files:**
- Create: `actionability.py`

- [ ] Add an immutable result type with at least `is_actionable` and `reason`.
- [ ] Include `entry` and `stop` in the result if useful for tests and diagnostics.
- [ ] Implement `assess_actionability(result, current_price)`.
- [ ] Catch strategy-geometry `ValueError`s and return `incomplete_geometry` instead of raising.
- [ ] Classify states using `result.metadata["state"]`:
  - Pre-breakout states: `active_pre_breakout`, `handle_forming`.
  - Post-breakout states: `confirmed`, `complete`.
  - Unknown states: treat as post-breakout only if the result has a breakout pivot; otherwise use pre-breakout price-band behavior.

### Task 4: Gate Candidate Creation In Main Flow

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] Update `build_candidates()` order to:

```text
screened row
  -> detect_all(df, ticker)
  -> skip empty pivots
  -> _is_recent_pattern_result(...)
  -> assess_actionability(pattern_result, current_price)
  -> skip if not actionable
  -> strategy(pattern_result)
  -> DecisionCandidate
```

- [ ] Move double-bottom active-zone rejection out of `_is_recent_pattern_result()`.
- [ ] Keep `_is_recent_pattern_result()` focused on date freshness only.
- [ ] Add main-flow tests proving non-actionable detected patterns do not become candidates.
- [ ] Keep debug chart saving tied to ticket-backed actionable setups.

### Task 5: Decouple Detectors From Actionability

**Files:**
- Modify: `patterns/cup_handle.py`
- Modify: `patterns/double_bottom.py`
- Modify: `tests/test_patterns/test_cup_handle.py`
- Modify: `tests/test_patterns/test_double_bottom.py`

- [ ] In cup-handle detection, keep `metadata["state"]` but stop using `metadata["actionable"]` as trade-readiness truth.
- [ ] If a cup-handle result includes post-breakout bars, include breakout pivot/date where the detector can identify it.
- [ ] In double-bottom detection, return structurally valid `active_pre_breakout` results even when more than 10% below the buy point.
- [ ] Preserve `active_zone_pct_below_buy_point` metadata for diagnostics.
- [ ] Update detector tests to assert detection existence separately from actionability.

## Test Plan

Run targeted tests first:

```bash
rtk pytest tests/test_actionability.py tests/test_strategies.py tests/test_main.py tests/test_patterns/test_cup_handle.py tests/test_patterns/test_double_bottom.py -q
```

Then run the full suite:

```bash
rtk pytest -q
```

Required coverage:

- Detected incomplete cup pattern does not create a candidate.
- Pre-breakout pattern within 10% below entry creates a candidate.
- Pre-breakout pattern more than 10% below entry is detected but skipped.
- Confirmed/post-breakout pattern inside the pullback buy zone creates a candidate.
- Confirmed/post-breakout pattern more than 5% above entry is skipped.
- Confirmed/post-breakout pattern more than 2% below entry is skipped.
- Pattern below stop is skipped.
- Stale detected patterns remain skipped independently from actionability.
- `strategy()` no longer rejects solely because `metadata["actionable"]` is false.
- Debug chart saving still renders ticket-backed actionable setups.

## Assumptions

- No CLI flags for actionability bands in v1.
- `current_price` from the screened summary is the actionability price source.
- `DecisionCandidate` and ticket output schemas remain unchanged.
- Actionability reason is internal for now.
- Existing dirty files are user-owned. Do not revert, reformat, or clean unrelated changes.
- This plan intentionally introduces one new policy module. Avoid additional abstractions unless tests prove the single module is not enough.

## Engineering Review Report

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture and test coverage | 1 | DONE_WITH_CONCERNS | Added state-aware actionability reason so breakout buys and pullback buys remain distinguishable without changing public ticket output. |

**VERDICT:** Ready for implementation after preserving dirty-worktree changes.
