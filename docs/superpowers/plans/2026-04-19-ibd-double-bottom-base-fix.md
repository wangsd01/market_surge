# IBD Double Bottom Base Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `double_bottom` so it detects IBD-style double-bottom bases instead of narrow internal W subpatterns.

**Architecture:** Rebuild the detector around an IBD base model using swing `High`/`Low` pivots rather than close-only local minima. The detector should support both confirmed and still-forming bases, preserve the current strategy contract, and keep pre-breakout setups ticket-eligible while they remain active near the buy point.

**Tech Stack:** Python, pandas, pytest

---

## Summary

Fix `double_bottom` so it detects IBD-style double-bottom bases instead of narrow internal W subpatterns. The detector must recognize both confirmed and still-forming bases, preserve the existing strategy contract, and keep pre-breakout setups ticket-eligible while they remain active near the buy point.

## Implementation Changes

- Rebuild `patterns/double_bottom.py` around an IBD base model using swing `High`/`Low` pivots rather than close-only local minima.
- Detect the ordered structure:
  - `left_high`: swing high that starts the base
  - `first_trough`: first major swing low after `left_high`
  - `middle_high`: highest intraday swing high between the two troughs; this is the buy point
  - `second_trough`: later swing low after `middle_high`
  - optional `breakout`: first later bar whose `Close` clears `middle_high`
- Hard detector rules:
  - base length from `left_high` to `second_trough` is at least 35 business days
  - base depth from `left_high` to the lower trough is between 15% and 33%
  - `second_trough` must undercut `first_trough`
  - “slightly undercut” means the second trough low is 0% to 5% below the first trough low
  - reject internal/local W candidates when a later valid second trough creates the full broader base
- State model in `PatternResult.metadata`:
  - `state="confirmed"` when breakout exists
  - `state="active_pre_breakout"` when no breakout exists but latest close is within 10% below `middle_high`
  - do not return the pattern if it is neither confirmed nor active_pre_breakout
- Confidence model:
  - base quality from IBD geometry and volume traits
  - breakout volume vs. 50-day average is confidence-only, not a hard gate
  - record `breakout_volume_ratio` in metadata when breakout exists
- Preserve downstream strategy compatibility:
  - keep `first_trough`, `middle_high`, `second_trough` in `pivots`
  - add `left_high`
  - add `breakout` only for confirmed setups
  - keep `strategies.py` unchanged: entry = `middle_high + 0.10`, stop = `second_trough`
- Update recency handling in `main.py` for double bottoms only:
  - confirmed setups age from `breakout`
  - active pre-breakout setups age from the latest bar date while still inside the 10% active zone
- Update the double-bottom spec in `CLAUDE.md` to match the IBD-aligned behavior and metadata contract

## Test Plan

- Targeted:
  - `pytest tests/test_patterns/test_double_bottom.py -v`
  - `pytest tests/test_main.py -v`
  - `pytest tests/test_strategies.py -v`
- Integration sanity:
  - run the decision-ticket flow against cached data and verify AMD surfaces as a double bottom when active or confirmed under the new rules
  - verify the returned buy point is still the middle intraday peak plus $0.10 in strategy output
- Regression focus:
  - AMD no longer resolves to the December internal W
  - pre-breakout double bottoms remain eligible only while within 10% below the buy point
  - weak/no-breakout-volume setups are still detected, but metadata/confidence reflects the weaker confirmation

## Assumptions And Defaults

- IBD-backed rules used as hard constraints: minimum 7-week base, typical 15%-33% depth, second trough lower than first, buy point at the middle intraday peak.
- Breakout volume is tracked as quality only, not eligibility.
- Pre-breakout setups are ticket-eligible.
- “Active” pre-breakout means latest close is within 10% below the buy point.
- No extra “must reclaim left high zone” rule is added because that is not required by the IBD material reviewed.
