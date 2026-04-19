# Cup-Handle Post-Breakout Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `CupHandleDetector.detect()` so IBD-style cup-with-handle bases are detected across active formation, pre-breakout handle formation, and post-breakout chart data without drifting to later breakout bars.

**Architecture:** Use IBD-aligned validation rules before candidate scoring: cup depth and duration, right lip near but not materially above the left lip, handle in the upper half, handle depth measured as a percent of the handle high, and light handle volume as a quality signal. Return explicit metadata states for `cup_forming`, `handle_forming`, and `complete` so charts can show active setups before breakout while trade setup generation only uses states with complete handle pivots and `metadata["actionable"] == True`. Add a real-data POWL regression that currently fails because the detector rejects the 2026-03-25 handle as too deep relative to cup depth, then accepts 2026-04-10 as a later "right lip" after breakout.

**Tech Stack:** Python, pandas, numpy, pytest

---

## IBD Research Alignment

Sources checked:
- IBD, "This Chart Pattern Launched Amazon's Big Run; How To Spot It": https://www.investors.com/how-to-invest/investors-corner/amazon-stock-chart-patterns/
- IBD, "How To Buy Stocks: Lam Research's Cup With Handle Launched A 75% Advance": https://www.investors.com/how-to-invest/investors-corner/how-to-buy-stocks-lam-research-cup-with-handle-launched-75-percent-advance/
- IBD, "Making Money In Growth Stocks: How To Find The Correct Buy Point": https://www.investors.com/how-to-invest/investors-corner/chart-reading-basics-how-a-buy-point-marks-a-time-of-opportunity/
- IBD, "This Bullish Chart Pattern Led To 39% Gain For Netflix Stock": https://www.investors.com/how-to-invest/investors-corner/netflix-stock-chart-pattern/
- IBD, "Best Stocks To Buy Form Bullish Bases Before Big Price Gains": https://www.investors.com/how-to-invest/investors-corner/best-stocks-to-buy-form-bullish-bases-before-big-price-gains/

IBD rules to encode:
- A cup-with-handle base is normally at least 7 weeks long; cup-without-handle is at least 6 weeks.
- A normal cup depth is roughly 12% to 33%.
- The cup should be rounded, not a sharp V.
- The handle needs at least 5 trading sessions.
- An active setup can be detected before breakout: if the cup is still forming, return `state="cup_forming"`; if the handle is forming or complete but price has not broken out, return `state="handle_forming"`; after breakout, return `state="complete"`.
- The handle should form in the upper half of the base. Use the midpoint test: handle midpoint must be above base midpoint.
- Handle depth is measured from the handle high, not as a percent of cup depth. Most successful handles are no more than 12%; allow up to 15% as a hard daily-chart cap.
- Handle volume should quiet down; treat this as a confidence/quality signal, not a hard reject.
- The buy point is the highest price in the handle plus the configured buffer used by `strategies.py`.
- Breakout volume should be strong, roughly 40% above the 50-day average, but breakout confirmation belongs in strategy/quality scoring rather than core pre-breakout pattern geometry.

Important implication for POWL:
- Real POWL close data gives `left_high=197.54` on 2026-02-12, `cup_low=161.22` on 2026-03-06, `right_high=194.85` on 2026-03-25, and handle low close `167.52` on 2026-03-30.
- The handle decline is `27.33 / 194.85 = 14.0%`, which is deep but still within the IBD-style 15% hard cap.
- The current detector rejects it because it measures handle decline as `27.33 / 36.32 = 75%` of cup depth and requires <= 50%.
- Later breakout closes on 2026-04-09 and 2026-04-10 are above the left lip. They should not become right-lip candidates for the original base.

---

## File Map

| File | Change |
|------|--------|
| `patterns/cup_handle.py` | Replace cup-depth-relative handle retrace with IBD handle-depth percent; add an upper bound on right-lip overshoot; return explicit active states; prefer earliest valid IBD handle over higher post-breakout pivots. |
| `strategies.py` | Raise a clean `ValueError` for `cup_handle` results without complete handle pivots or with `metadata["actionable"] == False`, so early active formations can chart without becoming trade tickets. |
| `main.py` | Optional safety belt: skip non-actionable cup-handle states in decision-ticket candidate generation if `strategies.py` is not the only guard. |
| `tests/test_patterns/test_cup_handle.py` | Add a real cached-data POWL regression using static OHLCV rows from 2026-02-12 through 2026-04-17. Add active `cup_forming` and `handle_forming` regressions. Keep the synthetic POWL fixture as a geometry smoke test. |
| `tests/test_strategies.py` | Add coverage that non-actionable cup-handle states are not converted into trade setups. |
| `docs/superpowers/plans/2026-04-19-cup-handle-post-breakout-fix.md` | This plan. |

---

### Task 1: Add Real-Data POWL Regression (RED)

**Files:**
- Modify: `tests/test_patterns/test_cup_handle.py`

- [ ] **Step 1: Add a deterministic row-based OHLCV helper**

The current test file may already have `_make_dated_ohlcv(dates, prices, volumes)`. Do not change that helper. Add a separate row-based helper:

```python
def _make_ohlcv_rows(
    rows: list[tuple[str, float, float, float, float, int]]
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [row[1] for row in rows],
            "High": [row[2] for row in rows],
            "Low": [row[3] for row in rows],
            "Close": [row[4] for row in rows],
            "Volume": [row[5] for row in rows],
        },
        index=pd.to_datetime([row[0] for row in rows]),
    )
```

- [ ] **Step 2: Add static real-data POWL rows**

Add this fixture near the existing POWL tests:

```python
_POWL_REAL_ROWS = [
    ("2026-02-12", 198.038090, 204.068530, 194.573097, 197.538330, 784800),
    ("2026-02-13", 197.078556, 201.229880, 192.110944, 194.929581, 515100),
    ("2026-02-17", 191.617849, 193.890087, 185.410827, 187.123337, 516900),
    ("2026-02-18", 186.873337, 190.666672, 179.000000, 180.993332, 756900),
    ("2026-02-19", 180.406662, 185.000000, 178.666672, 178.786667, 670800),
    ("2026-02-20", 178.396667, 186.520004, 174.910004, 182.273331, 633600),
    ("2026-02-23", 182.270004, 185.000000, 177.460007, 181.383331, 577200),
    ("2026-02-24", 179.943329, 188.833328, 178.326660, 186.386673, 783600),
    ("2026-02-25", 188.333328, 188.666672, 182.000000, 183.000000, 628500),
    ("2026-02-26", 183.270004, 185.666672, 170.240005, 176.960007, 815700),
    ("2026-02-27", 172.646667, 176.663330, 169.000000, 174.533340, 579600),
    ("2026-03-02", 171.256668, 180.446671, 168.666672, 177.500000, 407100),
    ("2026-03-03", 168.449997, 173.330002, 165.720001, 170.373337, 591300),
    ("2026-03-04", 171.833328, 175.000000, 166.000000, 170.963333, 769200),
    ("2026-03-05", 166.333328, 172.666672, 165.346664, 167.669998, 835200),
    ("2026-03-06", 161.589996, 165.476669, 158.666672, 161.216660, 571800),
    ("2026-03-09", 157.563339, 174.070007, 157.503326, 173.363327, 814500),
    ("2026-03-10", 173.910004, 181.666672, 173.910004, 176.513336, 576300),
    ("2026-03-11", 174.663330, 180.956665, 171.336670, 171.733337, 636600),
    ("2026-03-12", 168.266663, 172.669998, 163.000000, 171.186661, 885900),
    ("2026-03-13", 172.813339, 176.893326, 164.786667, 167.570007, 541500),
    ("2026-03-16", 171.163330, 176.653336, 169.226669, 170.606674, 402900),
    ("2026-03-17", 171.333328, 175.996674, 170.006668, 174.039993, 402000),
    ("2026-03-18", 175.440002, 179.039993, 165.886673, 167.410004, 791700),
    ("2026-03-19", 164.250000, 177.800003, 163.333328, 175.133331, 760500),
    ("2026-03-20", 170.000000, 174.690002, 168.666672, 172.000000, 1087500),
    ("2026-03-23", 176.406662, 186.666672, 176.406662, 180.863327, 657600),
    ("2026-03-24", 178.639999, 187.666672, 177.096664, 186.820007, 759300),
    ("2026-03-25", 191.666672, 196.666672, 189.696671, 194.853333, 785400),
    ("2026-03-26", 191.589996, 191.589996, 173.710007, 174.796661, 757800),
    ("2026-03-27", 174.796661, 181.639999, 174.796661, 179.346664, 629700),
    ("2026-03-30", 180.270004, 180.806671, 165.256668, 167.520004, 832500),
    ("2026-03-31", 169.619995, 180.703339, 168.893326, 180.360001, 471300),
    ("2026-04-01", 185.946671, 190.529999, 183.000000, 184.683334, 455700),
    ("2026-04-02", 176.470001, 188.046661, 175.000000, 182.603333, 339600),
    ("2026-04-06", 182.100006, 188.440002, 178.050003, 186.720001, 397000),
    ("2026-04-07", 184.660004, 202.490005, 183.199997, 201.699997, 856900),
    ("2026-04-08", 214.610001, 221.660004, 208.550003, 218.070007, 1065100),
    ("2026-04-09", 217.919998, 237.789993, 217.509995, 230.809998, 822300),
    ("2026-04-10", 230.809998, 235.309998, 227.000000, 230.940002, 708800),
    ("2026-04-13", 229.190002, 232.619995, 225.100006, 228.990005, 449400),
    ("2026-04-14", 232.419998, 236.330002, 225.100006, 234.419998, 619900),
    ("2026-04-15", 231.380005, 234.000000, 224.210007, 229.729996, 471900),
    ("2026-04-16", 229.770004, 234.070007, 224.000000, 232.809998, 452600),
    ("2026-04-17", 237.000000, 246.690002, 230.710007, 241.009995, 928200),
]
```

- [ ] **Step 3: Add the failing regression**

```python
def test_real_powl_post_breakout_keeps_march_25_right_lip():
    df = _make_ohlcv_rows(_POWL_REAL_ROWS)
    result = CupHandleDetector().detect(df, "POWL")

    assert result is not None
    assert result.pivot_dates["left_high"] == date(2026, 2, 12)
    assert result.pivot_dates["cup_low"] == date(2026, 3, 6)
    assert result.pivot_dates["right_high"] == date(2026, 3, 25)
    assert result.pivot_dates["handle_high"] == date(2026, 3, 25)
    assert result.pivot_dates["handle_low"] == date(2026, 3, 30)
    assert result.pivots["right_high"] < result.pivots["left_high"]
```

- [ ] **Step 4: Verify RED**

```bash
rtk python -m pytest tests/test_patterns/test_cup_handle.py::TestPOWLCupHandle::test_real_powl_post_breakout_keeps_march_25_right_lip -v
```

Expected: FAIL. Current detector returns `right_high == 2026-04-10`.

- [ ] **Step 5: Commit RED**

```bash
rtk git add tests/test_patterns/test_cup_handle.py
rtk git commit -m "test: add real POWL cup-handle post-breakout regression"
```

---

### Task 2: Align Detector With IBD Handle Rules (GREEN)

**Files:**
- Modify: `patterns/cup_handle.py`

- [ ] **Step 1: Replace constants**

Replace:

```python
_HANDLE_RETRACE_MAX = 0.50   # handle decline <= 50% of cup depth
```

with:

```python
_RIGHT_OVERSHOOT_MAX = 0.02  # right lip can slightly exceed left lip, but breakout bars cannot qualify
_HANDLE_DEPTH_IDEAL = 0.12   # IBD: most strong handles are <= 12%
_HANDLE_DEPTH_MAX = 0.15     # IBD daily-chart hard cap for normal markets
```

- [ ] **Step 2: Make right-lip candidate band two-sided**

Replace the `candidate_mask` with:

```python
recovery_from_left = (left_high_price - recovery_segment) / left_high_price
candidate_mask = (
    (recovery_from_left >= -_RIGHT_OVERSHOOT_MAX)
    & (recovery_from_left <= _RIGHT_RECOVERY_MAX)
)
```

This keeps candidates near the old high but excludes post-breakout bars that are far above the left lip.

- [ ] **Step 3: Measure handle depth the IBD way**

After `h_decline = rh_price - h_low`, add:

```python
handle_depth_pct = h_decline / rh_price if rh_price > 0 else 1.0
```

Replace:

```python
c4 = (h_decline / cup_depth_abs) <= _HANDLE_RETRACE_MAX
```

with:

```python
c4 = handle_depth_pct <= _HANDLE_DEPTH_MAX
ideal_handle_depth = handle_depth_pct <= _HANDLE_DEPTH_IDEAL
```

- [ ] **Step 4: Keep upper-half midpoint as a hard rule**

Keep:

```python
base_mid = (left_high_price + cup_low_price) / 2
c7 = (rh_price + h_low) / 2 > base_mid
```

This directly implements IBD's midpoint test.

- [ ] **Step 5: Prefer earliest valid IBD handle over highest post-breakout price**

Replace the current candidate key:

```python
if (score, rh_price) > (best_score, best_rh_price):
```

with a key that rewards IBD quality but does not prefer later breakout highs:

```python
candidate_key = (
    score,
    1 if ideal_handle_depth else 0,
    -abs((left_high_price - rh_price) / left_high_price),
    -rh_idx,
)
if best is None or candidate_key > best_key:
```

Add `best_key: tuple | None = None` before the loop and store `handle_depth_pct` in the `best` tuple.

- [ ] **Step 6: Add metadata for debugging**

Include at least:

```python
metadata = {
    "state": "complete",
    "actionable": True,
    "cup_depth_pct": float(cup_depth),
    "handle_depth_pct": float(handle_depth_pct),
    "handle_duration_bdays": int(handle_duration),
}
```

Pass `metadata=metadata` into `PatternResult`.

- [ ] **Step 7: Verify GREEN**

```bash
rtk python -m pytest tests/test_patterns/test_cup_handle.py::TestPOWLCupHandle::test_real_powl_post_breakout_keeps_march_25_right_lip -v
```

Expected: PASS.

- [ ] **Step 8: Commit GREEN**

```bash
rtk git add patterns/cup_handle.py
rtk git commit -m "fix: align cup-handle detector with IBD handle rules"
```

---

### Task 3: Detect Active Cup And Handle Formation Before Breakout

**Files:**
- Modify: `patterns/cup_handle.py`
- Modify: `tests/test_patterns/test_cup_handle.py`

State contract:
- `metadata["state"] == "cup_forming"` when a valid cup is forming but price has not yet recovered into the right-lip zone. Required pivots: `left_high`, `cup_low`. Set `metadata["actionable"] = False`.
- `metadata["state"] == "handle_forming"` when the cup has recovered into the right-lip zone but no breakout has happened yet. Required pivots for every `handle_forming` result: `left_high`, `cup_low`, `right_high`, `handle_high`. Include `handle_low` only after at least one post-right-lip bar exists. Set `metadata["actionable"] = True` only when the handle has at least `_HANDLE_MIN_DAYS`, has a real pullback (`handle_low < handle_high`), and passes handle-depth plus upper-half checks; otherwise set it to `False`.
- `metadata["state"] == "complete"` when a valid handle exists and the df includes post-handle breakout bars. Required pivots: `left_high`, `cup_low`, `right_high`, `handle_high`, `handle_low`. Set `metadata["actionable"] = True`.

Do not create a separate pattern name. Use `pattern="cup_handle"` for all three states so charting and display remain simple; use `metadata["actionable"]` to determine whether a trade setup is actionable.

- [ ] **Step 1: Add a cup-forming test**

Use a deterministic series where the left lip and rounded bottom are present, but the latest bar is still below the `_RIGHT_RECOVERY_MAX` right-lip zone:

```python
def test_detects_active_cup_forming_before_right_lip(make_ohlcv):
    prices = [
        95, 98, 100, 99, 97,
        94, 90, 86, 82, 78, 75,
        75, 75, 76, 77, 78, 80, 82, 84, 86,
        88, 90, 91, 92, 93,
    ] + [93, 93, 93, 93, 93, 93, 93, 93, 93, 93,
         93, 93, 93, 93, 93, 93, 93, 93, 93, 93]
    df = make_ohlcv(prices)
    result = CupHandleDetector().detect(df, "FORMING")

    assert result is not None
    assert result.pattern == "cup_handle"
    assert result.metadata["state"] == "cup_forming"
    assert result.metadata["actionable"] is False
    assert {"left_high", "cup_low"}.issubset(result.pivots)
    assert "handle_high" not in result.pivots
```

- [ ] **Step 2: Add a handle-forming test**

Use a deterministic series where price has recovered into the right-lip zone and the latest bar is still inside an upper-half handle before breakout:

```python
def test_detects_handle_forming_at_right_edge_before_breakout(make_ohlcv):
    prices = [
        90, 95, 100, 99, 98,
        96, 93, 90, 87, 84, 82, 79, 77, 76, 75,
        75, 75, 75, 76, 77, 78, 79, 81, 83, 85,
        87, 89, 91, 92, 93, 94, 95, 96, 97, 97,
        96, 94, 93, 92, 91, 92, 93, 94, 95, 96,
    ]
    df = make_ohlcv(prices)
    result = CupHandleDetector().detect(df, "HANDLE")

    assert result is not None
    assert result.pattern == "cup_handle"
    assert result.metadata["state"] == "handle_forming"
    assert result.metadata["actionable"] is True
    assert result.pivots["handle_low"] < result.pivots["handle_high"]
    assert result.detected_on == df.index[-1].date()
```

- [ ] **Step 3: Verify RED**

```bash
rtk python -m pytest \
  tests/test_patterns/test_cup_handle.py::TestCupHandleDetector::test_detects_active_cup_forming_before_right_lip \
  tests/test_patterns/test_cup_handle.py::TestCupHandleDetector::test_detects_handle_forming_at_right_edge_before_breakout \
  -v
```

Expected: FAIL. The current detector returns `None` for active cups and requires a full handle window after a candidate right lip.

- [ ] **Step 4: Implement `cup_forming` fallback**

After evaluating cup conditions `c1`, `c2`, and rounded-bottom evidence, if there is no right-lip candidate but the latest close is above the cup low and the cup is still inside the 65-bar lookback, return:

```python
PatternResult(
    pattern="cup_handle",
    ticker=ticker,
    confidence=confidence,
    detected_on=dates[-1].date(),
    pivots={
        "left_high": float(left_high_price),
        "cup_low": float(cup_low_price),
    },
    pivot_dates={
        "left_high": dates[left_high_idx].date(),
        "cup_low": dates[cup_low_idx].date(),
    },
    metadata={
        "state": "cup_forming",
        "actionable": False,
        "cup_depth_pct": float(cup_depth),
    },
)
```

Set confidence lower than complete handles; suggested range: `0.45` to `0.65` depending on cup depth and bottom quality.

- [ ] **Step 5: Add a non-actionable handle-forming fallback**

If at least one right-lip candidate exists but no candidate yields a valid actionable handle, return the best right-lip candidate as `handle_forming` instead of `None`.

Use the candidate closest to the left high, then earliest:

```python
fallback_key = (
    -abs((left_high_price - rh_price) / left_high_price),
    -rh_idx,
)
```

Return:

```python
pivots = {
    "left_high": float(left_high_price),
    "cup_low": float(cup_low_price),
    "right_high": float(fallback_rh_price),
    "handle_high": float(fallback_rh_price),
}
pivot_dates = {
    "left_high": dates[left_high_idx].date(),
    "cup_low": dates[cup_low_idx].date(),
    "right_high": dates[fallback_rh_idx].date(),
    "handle_high": dates[fallback_rh_idx].date(),
}
if fallback_h_prices:
    pivots["handle_low"] = float(fallback_handle_low)
    pivot_dates["handle_low"] = dates[fallback_handle_low_idx].date()
```

Set `metadata["state"] = "handle_forming"` and `metadata["actionable"] = False`. This covers the active state where the cup has recovered into the right-lip zone but the handle is too young, too shallow to count as a pullback, or still needs more bars.

- [ ] **Step 6: Split the handle window at breakout**

When evaluating a right-lip candidate, separate handle bars from post-breakout bars. Use the first close above the right lip after at least `_HANDLE_MIN_DAYS` handle bars as the breakout boundary:

```python
raw_h_end = min(len(closes), h_start + _HANDLE_MAX_DAYS)
breakout_idx = None
for idx in range(h_start + _HANDLE_MIN_DAYS, raw_h_end):
    if closes[idx] > rh_price:
        breakout_idx = idx
        break

if breakout_idx is not None:
    h_end = breakout_idx
    state = "complete"
else:
    h_end = raw_h_end
    state = "handle_forming"

h_prices = closes[h_start:h_end]
h_vols = volumes[h_start:h_end]
h_dur = len(h_prices)

if h_dur < _HANDLE_MIN_DAYS and state == "handle_forming":
    actionable = False
elif h_dur >= _HANDLE_MIN_DAYS:
    actionable = True
else:
    continue
```

This makes real POWL complete because it breaks above the 2026-03-25 right lip on 2026-04-07. It keeps a same-day/right-edge pre-breakout handle as `handle_forming`.

Compute `h_low`, `h_decline`, `handle_depth_pct`, volume contraction, and midpoint checks only after `h_prices` has been trimmed to `h_end`. Do not reuse handle values computed from the untrimmed `raw_h_end` window.

For actionable `handle_forming` and `complete` candidates, still require:
- `h_decline > 0`
- `handle_depth_pct <= _HANDLE_DEPTH_MAX`
- upper-half midpoint passes

Non-actionable `handle_forming` fallbacks from Step 5 may fail one or more of those handle checks; that is why they must set `metadata["actionable"] = False`.

Treat volume contraction as optional confidence.

- [ ] **Step 7: Mark actionability explicitly**

For completed handles, keep `metadata["state"] = "complete"` and `metadata["actionable"] = True`. For active handles, set `metadata["state"] = "handle_forming"`. Include `handle_low` only when a post-right-lip handle bar exists. Set `metadata["actionable"] = h_dur >= _HANDLE_MIN_DAYS and h_decline > 0 and c4 and c7`.

- [ ] **Step 8: Verify GREEN**

```bash
rtk python -m pytest \
  tests/test_patterns/test_cup_handle.py::TestCupHandleDetector::test_detects_active_cup_forming_before_right_lip \
  tests/test_patterns/test_cup_handle.py::TestCupHandleDetector::test_detects_handle_forming_at_right_edge_before_breakout \
  -v
```

Expected: PASS.

- [ ] **Step 9: Commit active detection**

```bash
rtk git add patterns/cup_handle.py tests/test_patterns/test_cup_handle.py
rtk git commit -m "feat: detect active cup-handle formations before breakout"
```

---

### Task 4: Prevent Non-Actionable Cup-Handle States From Becoming Trade Tickets

**Files:**
- Modify: `strategies.py`
- Modify: `tests/test_strategies.py`
- Optional Modify: `main.py`

- [ ] **Step 1: Add strategy rejection tests**

Add these as module-level tests in `tests/test_strategies.py`, not inside `TestTradeSetup`, so the pytest selectors below are valid:

```python
def test_strategy_rejects_cup_forming_without_handle():
    result = _result(
        "cup_handle",
        {"left_high": 100.0, "cup_low": 75.0},
        metadata={"state": "cup_forming"},
    )

    with pytest.raises(ValueError, match="requires complete handle"):
        strategy(result)


def test_strategy_rejects_non_actionable_early_handle():
    result = _result(
        "cup_handle",
        {"left_high": 100.0, "cup_low": 75.0, "handle_high": 97.0, "handle_low": 91.0},
        metadata={"state": "handle_forming", "actionable": False},
    )

    with pytest.raises(ValueError, match="requires complete handle"):
        strategy(result)


def test_strategy_allows_actionable_handle_forming_setup():
    result = _result(
        "cup_handle",
        {"left_high": 100.0, "cup_low": 75.0, "handle_high": 97.0, "handle_low": 91.0},
        metadata={"state": "handle_forming", "actionable": True},
    )

    setup = strategy(result)

    assert setup.entry == 97.10
```

- [ ] **Step 2: Verify RED**

```bash
rtk python -m pytest \
  tests/test_strategies.py::test_strategy_rejects_cup_forming_without_handle \
  tests/test_strategies.py::test_strategy_rejects_non_actionable_early_handle \
  tests/test_strategies.py::test_strategy_allows_actionable_handle_forming_setup \
  -v
```

Expected: FAIL. Current code raises `KeyError` for `cup_forming` and does not understand `actionable`.

- [ ] **Step 3: Add a clean guard in `strategies.py`**

In `_levels()`, before reading `handle_high` and `handle_low`:

```python
if p == "cup_handle":
    if result.metadata.get("actionable", True) is False:
        raise ValueError("cup_handle strategy requires complete handle")
    if "handle_high" not in pivots or "handle_low" not in pivots:
        raise ValueError("cup_handle strategy requires complete handle")
    return pivots["handle_high"], pivots["handle_low"]
```

- [ ] **Step 4: Optional main safety belt**

If desired, skip non-actionable states before strategy generation in `main.build_candidates()`:

```python
if pattern_result.pattern == "cup_handle" and pattern_result.metadata.get("actionable", True) is False:
    continue
```

This is optional because `build_candidates()` already catches `ValueError`, but it makes intent explicit.

- [ ] **Step 5: Verify GREEN**

```bash
rtk python -m pytest tests/test_strategies.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit strategy guard**

```bash
rtk git add strategies.py tests/test_strategies.py
rtk git commit -m "fix: keep incomplete cup-handle states out of trade setups"
```

If Step 4 changed `main.py`, inspect the diff and stage it separately:

```bash
rtk git diff -- main.py
rtk git add main.py
```

---

### Task 5: Verify Existing Behavior And Chart Output

**Files:**
- Modify if needed: `tests/test_patterns/test_cup_handle.py`
- Inspect: `charts.py`, `main.py`

- [ ] **Step 1: Run all cup-handle tests**

```bash
rtk python -m pytest tests/test_patterns/test_cup_handle.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run full test suite**

```bash
rtk python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Verify actual cached POWL output**

Run:

```bash
rtk python - <<'PY'
import sqlite3
import pandas as pd
from patterns.cup_handle import CupHandleDetector

conn = sqlite3.connect("market_surge.db")
df = pd.read_sql_query(
    """
    SELECT date as Date, open as Open, high as High, low as Low, close as Close, volume as Volume
    FROM raw_price_history
    WHERE ticker='POWL'
    ORDER BY date
    """,
    conn,
)
df["Date"] = pd.to_datetime(df["Date"])
ohlcv = df.set_index("Date").tail(65)[["Open", "High", "Low", "Close", "Volume"]]
result = CupHandleDetector().detect(ohlcv, "POWL")
print(result.pivot_dates if result else None)
print(result.pivots if result else None)
print(result.metadata if result else None)
PY
```

Expected: `right_high` and `handle_high` dates are `2026-03-25`, not `2026-04-10`.

- [ ] **Step 4: Verify chart behavior for incomplete states**

Create a local `PatternResult` with `metadata["state"] = "cup_forming"` and call `charts.chart(..., show=False)`.

Expected: chart renders cup pivots without needing handle pivots.

- [ ] **Step 5: Commit verification-only test adjustments if needed**

Only commit if Task 3 required test changes:

```bash
rtk git add tests/test_patterns/test_cup_handle.py
rtk git commit -m "test: cover IBD cup-handle edge cases"
```

---

## Self-Review Checklist

- [ ] Test fails before implementation on real POWL data.
- [ ] Handle depth is measured as percent decline from handle high.
- [ ] A 14% handle can pass if it remains in the upper half of the base.
- [ ] Post-breakout bars materially above the left lip cannot become right-lip candidates.
- [ ] Candidate selection does not prefer later highs just because they are higher.
- [ ] Active `cup_forming` setups are returned before the right lip is complete.
- [ ] Active `handle_forming` setups are returned at the right edge before breakout.
- [ ] Non-actionable cup-handle states render on charts but do not produce trade setups.
- [ ] Actionable pre-breakout handles can still produce buy-point strategy levels.
- [ ] Existing synthetic POWL tests still pass.
- [ ] Full test suite passes.

---

## Known Non-Goals

- Do not add network calls to tests.
- Do not make chart rendering infer pivots independently; charts should render `PatternResult`.
- Do not implement full CAN SLIM context such as earnings, relative strength, or market direction in this detector.
- Do not require breakout volume in `CupHandleDetector.detect()`; keep breakout volume as strategy/quality metadata unless a later plan explicitly moves it into detector acceptance.
