# market_surge — Agent Operating Manual

This file is the primary instruction set for Claude Code and Codex agents working
on this repo. Read it before doing anything. It defines what to build, in what order,
and how to build it.

## Project Overview

market_surge is a personal trading toolkit that screens US stocks for bounce setups,
detects classic chart patterns, visualizes them with plotly, and generates informational
trade recommendations (entry, stop, target).

**Current state (Phase 1 complete):**
- `fetcher.py` — yfinance OHLCV downloader with SQLite cache
- `db.py` — SQLite schema and CRUD operations
- `filters.py` — screening filters (volume, price, 52-week high)
- `screener.py` — CLI entry point
- `display.py` — rich table output
- `tests/` — test suite for all existing modules

**Design doc:** `~/.gstack/projects/market_surge/wang-main-design-20260412-224215.md`
Read this for full architecture rationale and pattern quantitative definitions.

---

## Task Queue (work through in order, one module per agent run)

### Phase 2 — Pattern Engine

- [x] `tests/conftest.py` — shared `make_ohlcv` fixture (do this FIRST)
- [x] `patterns/base.py` — `PatternResult` dataclass + `PatternDetector` ABC
- [x] `patterns/cup_handle.py` — cup with handle detector
- [x] `tests/test_patterns/test_cup_handle.py` — TDD for cup with handle
- [x] `patterns/double_bottom.py` — double bottom detector
- [x] `tests/test_patterns/test_double_bottom.py`
- [x] `patterns/vcp.py` — Volatility Contraction Pattern detector
- [x] `tests/test_patterns/test_vcp.py`
- [x] `patterns/channel.py` — upper/lower channel detector
- [x] `tests/test_patterns/test_channel.py`
- [x] `patterns/support_resistance.py` — S/R level detector
- [x] `tests/test_patterns/test_support_resistance.py`
- [x] `patterns/__init__.py` — `detect_all(df, ticker) -> list[PatternResult]`

### Phase 3 — Visualization

- [x] `charts.py` — plotly chart renderer
- [x] `tests/test_charts.py`

### Phase 4 — Strategy

- [x] `strategies.py` — `TradeSetup` calculator from `PatternResult`
- [x] `tests/test_strategies.py`

### Phase 5 — Integration

- [x] `screener.py` — add `--patterns`, `--chart TICKER`, `--strategy TICKER` flags
- [x] End-to-end integration test

---

## Agent Workflow

### Codex (implementer)

Pick the next unchecked item in the task queue above. Then:

1. Read the spec for that module (in this file, below)
2. Write the test file first (TDD — no implementation code yet)
3. Run `python -m pytest tests/` — tests must FAIL at this point (red)
4. Write the implementation
5. Run `python -m pytest tests/` — all tests must PASS (green)
6. Commit: `git add <files> && git commit -m "feat: implement <module>"`
7. Mark the checkbox above as done: `[x]`

**Codex invocation:**
```bash
codex "Implement market_surge patterns/cup_handle.py per the spec in CLAUDE.md.
TDD: write tests/test_patterns/test_cup_handle.py first. Run pytest to confirm
red -> green. Commit with message: 'feat: implement cup with handle pattern detector'"
```

### Claude (reviewer)

After Codex commits, run `/review` in Claude Code. Claude checks:
- Tests pass and test cases cover edge cases from the spec
- PatternResult returned (not raw dicts)
- No network calls in tests (uses conftest.py fixture)
- Coding standards met (see below)

---

## Coding Standards (mandatory for all agents)

- **TDD always**: tests written before implementation. Red → green.
- **Type annotations**: every function signature must be fully annotated.
- **PatternResult**: always return `PatternResult` dataclass, never raw dicts.
- **No print()** in library code. Use `logging.getLogger(__name__)`.
- **No network in tests**: use `make_ohlcv` fixture from `tests/conftest.py`.
- **One commit per module**. Format: `feat: implement <description>`
- **Run `python -m pytest tests/`** before committing. All green.
- **Dependencies**: `plotly`, `scipy` only (no scikit-learn, no ML libraries).

---

## Module Specs

### tests/conftest.py

```python
import pytest
import numpy as np
import pandas as pd

@pytest.fixture
def make_ohlcv():
    def _make(prices: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
        """Deterministic OHLCV DataFrame. Highs = close*1.005, Lows = close*0.995."""
        closes = np.array(prices, dtype=float)
        highs = closes * 1.005
        lows = closes * 0.995
        opens = np.roll(closes, 1); opens[0] = closes[0]
        vols = np.array(volumes if volumes else [1_000_000] * len(closes), dtype=int)
        dates = pd.date_range("2025-01-01", periods=len(closes), freq="B")
        return pd.DataFrame(
            {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
            index=dates
        )
    return _make
```

### patterns/base.py

```python
from dataclasses import dataclass, field
from datetime import date
from abc import ABC, abstractmethod
import pandas as pd

@dataclass
class PatternResult:
    pattern: str            # "cup_handle", "double_bottom", "vcp", "channel", "support_resistance"
    ticker: str
    confidence: float       # 0.0–1.0 = conditions_met / total_conditions
    detected_on: date       # date of last bar in input df
    pivots: dict[str, float]       # named price levels {"left_high": 150.0, "cup_low": 120.0, ...}
    pivot_dates: dict[str, date]   # dates of each pivot
    metadata: dict = field(default_factory=dict)  # pattern-specific extras

class PatternDetector(ABC):
    @abstractmethod
    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        """Return PatternResult if pattern found, None otherwise.
        df: DatetimeIndex, columns [Open, High, Low, Close, Volume], pre-sliced to 90 days.
        """
        ...
```

### patterns/cup_handle.py

Conditions (each is binary — met or not — for confidence calculation):
1. Cup depth: `(left_high - cup_low) / left_high` is between 0.15 and 0.35
2. Cup shape: bottom spans ≥ 10 days (not a V-shape)
3. Right side recovery: current price within 5% of left_high
4. Handle retracement: handle decline ≤ 50% of cup depth
5. Handle duration: 5–15 trading days
6. Volume contraction: slope of 5-day volume SMA during handle is negative

Confidence = conditions_met / 6

Pivots to return: `left_high`, `cup_low`, `right_high`, `handle_low`, `handle_high`

Lookback: 45–65 trading days from end of df.

### patterns/double_bottom.py

Conditions:
1. Two troughs within 3% of each other in price
2. Troughs separated by 15–50 trading days
3. Middle peak ≥ 10% above trough levels
4. Second trough volume ≤ first trough volume

Confidence = conditions_met / 4

Pivots: `first_trough`, `middle_high`, `second_trough`

### patterns/vcp.py

Conditions:
1. 3–5 contraction cycles detected over 30–90 days
2. Each contraction smaller % decline than prior (monotonically decreasing)
3. Each contraction smaller % recovery than prior
4. Price above 150-day SMA throughout (use full df length; if df < 150 days, skip this condition)
5. Volume declining with each contraction

Confidence = conditions_met / 5

Implementation note: use `scipy.signal.argrelextrema(closes, np.greater, order=5)` for
local highs and `argrelextrema(closes, np.less, order=5)` for local lows. Minimum swing
size = 2% (ignore swings < 2% to filter noise).

Pivots: `high_N` and `low_N` for each contraction (e.g. `high_1`, `low_1`, `high_2`, ...)

### patterns/channel.py

Conditions:
1. Upper channel R² > 0.7 (fit via `scipy.stats.linregress` on highs)
2. Lower channel R² > 0.7 (fit via `scipy.stats.linregress` on lows)
3. Channel width < 20% of price (not too wide to be meaningful)
4. Current price between lower and upper channel line

Confidence = conditions_met / 4

Lookback: 20–60 days (try 60, fall back to 20 if R² < 0.7)

Pivots: `channel_top` (upper line at last date), `channel_bottom` (lower line at last date)
Metadata: `upper_slope`, `lower_slope`, `channel_width_pct`, `price_position_pct`

### patterns/support_resistance.py

Algorithm:
1. Find local maxima using `scipy.signal.argrelextrema(highs, np.greater, order=5)`
2. Find local minima using `argrelextrema(lows, np.less, order=5)`
3. Collect all pivot prices into one list
4. Cluster: merge levels within 1% of each other (weighted average)
5. Score each level: touches (count of pivots within 1%) + recency weight (more recent = higher)
6. Return top-5 levels sorted by score, each labeled as "support" (below current price) or "resistance" (above)

PatternResult for S/R is special — always returns a result (confidence = 1.0 if ≥ 3 levels found,
else levels_found / 3). Pivots dict: `{"level_1": price, "level_2": price, ...}`.
Metadata: `{"type_1": "support", "type_2": "resistance", ..., "touch_count_1": 4, ...}`

### patterns/__init__.py

```python
from .cup_handle import CupHandleDetector
from .double_bottom import DoubleBottomDetector
from .vcp import VCPDetector
from .channel import ChannelDetector
from .support_resistance import SupportResistanceDetector

_DETECTORS = [
    CupHandleDetector(),
    DoubleBottomDetector(),
    VCPDetector(),
    ChannelDetector(),
    SupportResistanceDetector(),
]

def detect_all(df: pd.DataFrame, ticker: str) -> list[PatternResult]:
    """Run all detectors on pre-sliced OHLCV data (90 trading days, no NaN).
    Returns all detected patterns sorted by confidence descending.
    Returns [] if df has fewer than 45 rows.
    """
    if len(df) < 45:
        return []
    results = []
    for detector in _DETECTORS:
        result = detector.detect(df, ticker)
        if result is not None:
            results.append(result)
    return sorted(results, key=lambda r: r.confidence, reverse=True)
```

### charts.py

```python
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from patterns.base import PatternResult
from strategies import TradeSetup  # optional import — use TYPE_CHECKING guard

def chart(
    ticker: str,
    df: pd.DataFrame,
    patterns: list[PatternResult],
    setup: TradeSetup | None = None,
    show: bool = True,
) -> go.Figure:
    """Render candlestick chart with pattern overlays and optional strategy levels.
    show=False returns figure without opening browser (use in tests).
    """
```

Layout: 2 rows (70% / 30%). Top: candlestick + pattern pivot annotations + S/R dashed
horizontals + strategy levels (entry=green, stop=red, target=blue dashed).
Bottom: volume bars (green/red based on price direction).

Tests: assert `len(fig.data) >= 2` (candle + volume), assert annotation texts contain
expected pivot names. Do NOT call `fig.show()` in tests.

### strategies.py

```python
from dataclasses import dataclass
from patterns.base import PatternResult

RISK_REWARD = {"cup_handle": 2.5, "vcp": 2.5, "double_bottom": 2.0, "channel": 2.0, "support_resistance": 2.0}

@dataclass
class TradeSetup:
    pattern: str
    ticker: str
    entry: float      # breakout level * 1.0005 (0.05% above pivot high)
    stop: float       # pattern low (handle_low, second_trough, channel_bottom, etc.)
    target: float     # entry + (entry - stop) * risk_reward
    risk_reward: float
    risk_pct: float   # (entry - stop) / entry

def strategy(result: PatternResult) -> TradeSetup:
    """Derive informational trade setup from PatternResult geometry."""
```

Breakout price per pattern:
- cup_handle: `pivots["handle_high"]`
- double_bottom: `pivots["middle_high"]`
- vcp: last local high in pivots
- channel: `pivots["channel_top"]`
- support_resistance: nearest resistance above current price

Stop price: lowest relevant pivot (handle_low, second_trough, channel_bottom, nearest support below)

---

## Running

```bash
# Current functionality
python screener.py --min-price 10 --min-vol 1000000

# Phase 5 additions (not yet implemented)
python screener.py --patterns                    # detect patterns in screener output
python screener.py --chart AAPL                  # plotly chart for one ticker
python screener.py --strategy AAPL               # print trade setup
```

## Tests

```bash
python -m pytest tests/ -v
```

All tests must pass before any commit.

## Behavioral guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
