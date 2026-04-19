# High2 H1/H2 Distance Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap the search windows for H1 and H2 in the High2 detector so that AMD (and any ticker) can no longer produce a "valid" setup where H2 is many bars removed from H1.

**Architecture:** Two new module-level constants (`_H1_MAX_BARS`, `_H2_MAX_BARS`) gate the scan loops in `_find_h1` and `_find_h2`. No other logic changes. The fix is purely additive — existing valid setups pass because their H1/H2 are already within range.

**Tech Stack:** Python, pandas, pytest

---

## Background: Al Brooks High 2 Structure

The High 2 is a two-leg pullback-and-resume pattern from Al Brooks' *Reading Price Action with Order Flow*. The precise structure matters:

```
AIL leg (Always In Long)
  ↑ prior_swing_high
  ↓ Pullback  ← 2–5 bars, bearish/sideways, no strong bear bars
  ↑ H1        ← first higher high, FAILS to follow through (1–2 bars stall)
  ↓ micro-pause (0–3 bars, not a new pullback — just hesitation)
  ↑ H2        ← second higher high, the ENTRY bar
```

**Why distance matters:**

Brooks is explicit that H1 and H2 must be *compact*. The whole point is that the market tried once (H1), stalled briefly, then succeeded on the second attempt (H2). If H2 comes 15 bars after H1, the setup has aged out: the context has changed, a new trend may have started, and you are no longer buying a second attempt at the original breakout. You are buying a random breakout with a mistaken H2 label.

**Correct distances (derived from Brooks' day-trading rules):**

| Segment | Description | Max bars |
|---|---|---|
| pullback end → H1 | First recovery attempt | 5 bars |
| H1 + failure window → H2 scan | `_find_h2` search window | 8 bars |

In the current `_valid_h2_rows()` test fixture, H1 arrives at `pullback_end + 1` and H2 arrives at `h1_idx + 3` (the first possible bar). Both are well within these limits. Existing valid tests are unaffected.

In AMD's recent data, the scanner finds a legitimate AIL + pullback, a real H1 that fails — but then H2 is 10–20+ bars later when AMD eventually breaks out. That is not a High 2. It is just a breakout.

---

## Files

| File | Change |
|---|---|
| `patterns/high2.py` | Add `_H1_MAX_BARS = 5` and `_H2_MAX_BARS = 8`; cap both scan loops |
| `tests/test_patterns/test_high2.py` | Add two rejection tests |

---

## Task 1: Write failing test — H1 too far from pullback

**Files:**
- Modify: `tests/test_patterns/test_high2.py`

The test inserts 6 descending-high sideways bars between the pullback end (index 11) and the original H1 bar. Each inserted bar has `High <= previous bar's High`, so none of them trigger `_find_h1`'s `High > prev_High` check. H1 is now 7 bars after `pullback_end_idx`, exceeding `_H1_MAX_BARS = 5`.

- [ ] **Step 1: Add the test**

Add this function to `tests/test_patterns/test_high2.py` (before the last test in the file):

```python
def test_rejects_h1_too_far_from_pullback():
    # Rows 0-11 are the valid AIL + pullback.
    # Rows 12-14 in the original fixture are H1, failure window.
    # We splice in 6 descending-high bars after index 11 so that H1
    # is 7 bars after pullback_end — beyond _H1_MAX_BARS = 5.
    rows = _valid_h2_rows()
    # Row 11 has High = 104.7 (end of pullback). Each new bar's High must
    # be <= the previous bar's High so none become H1.
    extra: list[tuple[float, float, float, float, int]] = [
        (103.9, 104.6, 103.7, 104.0, 850_000),
        (104.0, 104.5, 103.8, 104.1, 840_000),
        (104.1, 104.4, 103.9, 104.0, 830_000),
        (104.0, 104.3, 103.8, 103.9, 820_000),
        (103.9, 104.2, 103.7, 103.8, 810_000),
        (103.8, 104.1, 103.6, 103.7, 800_000),
    ]
    # Insert after index 11, before original index 12 (H1)
    rows = rows[:12] + extra + rows[12:]

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None
```

- [ ] **Step 2: Run and confirm RED**

```
python -m pytest tests/test_patterns/test_high2.py::test_rejects_h1_too_far_from_pullback -v
```

Expected: `FAILED` — the detector currently finds a result because `_find_h1` has no distance cap.

---

## Task 2: Fix `_find_h1` with `_H1_MAX_BARS`

**Files:**
- Modify: `patterns/high2.py:10-17` (constants block)
- Modify: `patterns/high2.py:192-196` (`_find_h1`)

- [ ] **Step 1: Add the constant**

In [patterns/high2.py](patterns/high2.py), in the constants block (lines 10–17), add after `_PULLBACK_REJECT_MAX`:

```python
_H1_MAX_BARS = 5   # H1 must arrive within 5 bars of pullback end (Brooks: compact recovery)
```

Full constants block after the change:

```python
_MIN_ROWS = 12
_BULLISH_WINDOW = 6
_BULLISH_COUNT_MIN = 4
_TRADING_RANGE_MULTIPLIER = 3.0
_PULLBACK_MIN = 2
_PULLBACK_MAX = 5
_PULLBACK_FULL_SCORE_MAX = 0.50
_PULLBACK_REJECT_MAX = 0.60
_H1_MAX_BARS = 5
```

- [ ] **Step 2: Cap `_find_h1`**

Replace the body of `_find_h1` at [patterns/high2.py:192-196](patterns/high2.py#L192-L196):

Old:
```python
def _find_h1(df: pd.DataFrame, start_idx: int) -> int | None:
    for idx in range(start_idx, len(df)):
        if float(df["High"].iloc[idx]) > float(df["High"].iloc[idx - 1]):
            return idx
    return None
```

New:
```python
def _find_h1(df: pd.DataFrame, start_idx: int) -> int | None:
    for idx in range(start_idx, min(len(df), start_idx + _H1_MAX_BARS)):
        if float(df["High"].iloc[idx]) > float(df["High"].iloc[idx - 1]):
            return idx
    return None
```

- [ ] **Step 3: Run and confirm GREEN**

```
python -m pytest tests/test_patterns/test_high2.py -v
```

Expected: all tests pass including the new one.

- [ ] **Step 4: Commit**

```bash
git add patterns/high2.py tests/test_patterns/test_high2.py
git commit -m "fix: cap H1 search to _H1_MAX_BARS=5 bars after pullback end"
```

---

## Task 3: Write failing test — H2 too far from H1

**Files:**
- Modify: `tests/test_patterns/test_high2.py`

The test inserts 9 bars between the H1 failure confirmation window (indices 13–14) and the original H2 bar (index 15). Each inserted bar has `High <= trigger_level = max(h1_high=104.7, prior_swing_high=105.6) = 105.6` so none trigger `_find_h2`. H2 is now at `h1_idx + 3 + 9 = h1_idx + 12`, exceeding `_H2_MAX_BARS = 8`.

- [ ] **Step 1: Add the test**

Add this function to `tests/test_patterns/test_high2.py`:

```python
def test_rejects_h2_too_far_from_h1():
    # h1_idx=12, failure window covers indices 13-14, _find_h2 starts at idx 15.
    # We insert 9 non-breakout bars after index 14 so H2 is 12 bars after H1 —
    # beyond _H2_MAX_BARS = 8.
    rows = _valid_h2_rows()
    # Each inserted bar must have High <= 105.6 (trigger_level) so _find_h2
    # does not fire early. Use gradually declining highs to be safe.
    extra: list[tuple[float, float, float, float, int]] = [
        (104.5, 105.5, 104.3, 104.8, 900_000),
        (104.8, 105.4, 104.6, 104.9, 890_000),
        (104.9, 105.3, 104.7, 105.0, 880_000),
        (105.0, 105.3, 104.8, 105.1, 870_000),
        (105.1, 105.4, 104.9, 105.2, 860_000),
        (105.2, 105.5, 105.0, 105.3, 850_000),
        (105.3, 105.5, 105.1, 105.4, 840_000),
        (105.4, 105.5, 105.2, 105.3, 830_000),
        (105.3, 105.5, 105.1, 105.2, 820_000),
    ]
    # Insert after index 14 (last failure-window bar), before original H2 at index 15
    rows = rows[:15] + extra + rows[15:]

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None
```

- [ ] **Step 2: Run and confirm RED**

```
python -m pytest tests/test_patterns/test_high2.py::test_rejects_h2_too_far_from_h1 -v
```

Expected: `FAILED` — the detector currently finds the distant H2 because `_find_h2` has no distance cap.

---

## Task 4: Fix `_find_h2` with `_H2_MAX_BARS`

**Files:**
- Modify: `patterns/high2.py` (constants block + `_find_h2`)

- [ ] **Step 1: Add the constant**

In [patterns/high2.py](patterns/high2.py), add after `_H1_MAX_BARS`:

```python
_H2_MAX_BARS = 8   # H2 must arrive within 8 bars of the scan start (Brooks: compact second attempt)
```

Full constants block after the change:

```python
_MIN_ROWS = 12
_BULLISH_WINDOW = 6
_BULLISH_COUNT_MIN = 4
_TRADING_RANGE_MULTIPLIER = 3.0
_PULLBACK_MIN = 2
_PULLBACK_MAX = 5
_PULLBACK_FULL_SCORE_MAX = 0.50
_PULLBACK_REJECT_MAX = 0.60
_H1_MAX_BARS = 5
_H2_MAX_BARS = 8
```

- [ ] **Step 2: Cap `_find_h2`**

Replace the body of `_find_h2` at [patterns/high2.py:210-214](patterns/high2.py#L210-L214):

Old:
```python
def _find_h2(df: pd.DataFrame, start_idx: int, trigger_level: float) -> int | None:
    for idx in range(start_idx, len(df)):
        if float(df["High"].iloc[idx]) > trigger_level:
            return idx
    return None
```

New:
```python
def _find_h2(df: pd.DataFrame, start_idx: int, trigger_level: float) -> int | None:
    for idx in range(start_idx, min(len(df), start_idx + _H2_MAX_BARS)):
        if float(df["High"].iloc[idx]) > trigger_level:
            return idx
    return None
```

- [ ] **Step 3: Run full suite and confirm GREEN**

```
python -m pytest tests/test_patterns/test_high2.py -v
```

Expected: all tests pass, including both new rejection tests.

- [ ] **Step 4: Run entire project suite — no regressions**

```
python -m pytest tests/ -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add patterns/high2.py tests/test_patterns/test_high2.py
git commit -m "fix: cap H2 search to _H2_MAX_BARS=8 bars — reject aged-out AMD-style setups"
```

---

## Self-Review

**Spec coverage:**
- Root cause addressed: `_find_h1` unbounded scan → capped with `_H1_MAX_BARS = 5` ✓
- Root cause addressed: `_find_h2` unbounded scan → capped with `_H2_MAX_BARS = 8` ✓
- Al Brooks rationale documented in plan and as inline comments on constants ✓
- TDD: failing tests written before each fix ✓
- Existing valid test fixture passes: H1 at `pullback_end + 1` (1 bar, within 5), H2 at `h1_idx + 3` (0 bars into search window, within 8) ✓
- No other logic touched ✓

**Placeholder scan:** None found.

**Type consistency:** `_find_h1` and `_find_h2` signatures unchanged; only the `range()` upper bound is modified.
