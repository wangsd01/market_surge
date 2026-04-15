# Decision Ticket CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python CLI that scans the configured universe and emits up to 3 ranked planned-order tickets with deterministic ranking, fixed-risk sizing, stable terminal output, and stable JSON output.

**Architecture:** Keep `screener.py` as the stage-1 screener and add a thin `main.py` orchestration entrypoint for the Decision Ticket CLI. Extract shared screening-stage assembly into `pipeline.py`, keep ranking/sizing/output contracts in a focused `decision_tickets.py`, and reuse the existing cache, pattern, and strategy modules without adding persistence for downstream artifacts.

**Tech Stack:** Python, pandas, sqlite3, rich, pytest

---

## What Already Exists

- `screener.py` already fetches cached OHLCV, builds the screening summary, applies benchmark and liquidity filters, writes CSV output, and supports downstream pattern/strategy/chart helpers.
- `fetcher.py` and `db.py` already provide SQLite-backed cached price history and cached coverage checks.
- `strategies.py` already produces `TradeSetup` objects with `entry`, `stop`, `target`, `risk_reward`, and `risk_pct`.
- `display.py` already supports stable plain and rich table rendering for the screener output.
- Existing tests already cover cache behavior, parser flags, screener helpers, display, and trade setup geometry.

## Not In Scope

- Broker execution
- Live quotes
- User-tunable ranking weights
- Persistence of ranked decision tickets
- Architecture cleanup beyond what is needed to keep `main.py` viable later

## File Map

- Create: `main.py`
  Responsibility: Decision Ticket CLI parser and top-level orchestration.
- Create: `pipeline.py`
  Responsibility: shared screening-stage data assembly reused by `screener.py` and `main.py`.
- Create: `decision_tickets.py`
  Responsibility: candidate assembly, ranking, tie-breaks, per-ticker consolidation, sizing, serialization.
- Create: `schemas/decision_ticket_v1.json`
  Responsibility: stable JSON contract for ticket objects.
- Create: `tests/test_pipeline.py`
  Responsibility: shared stage-1 pipeline tests.
- Create: `tests/test_decision_tickets.py`
  Responsibility: ranking, sizing, one-ticket-per-ticker, fallback behavior.
- Create: `tests/test_main.py`
  Responsibility: `main.py` parser and end-to-end CLI behavior in table/json/cache-miss paths.
- Create: `tests/test_schema.py`
  Responsibility: JSON contract validation.
- Modify: `fetcher.py`
  Responsibility: add cache-only fetch path for warm-cache timed runs.
- Modify: `display.py`
  Responsibility: stable ticket table/plain rendering.
- Modify: `strategies.py`
  Responsibility: add `invalidation_rule` to `TradeSetup`.
- Modify: `screener.py`
  Responsibility: reuse `pipeline.py` without changing the existing stage-1 contract.
- Modify: `tests/test_fetcher_cache.py`
  Responsibility: fail-closed cache-only tests.
- Modify: `tests/test_display.py`
  Responsibility: ticket rendering tests.

### Task 1: Extract Shared Screening Pipeline

**Files:**
- Create: `pipeline.py`
- Modify: `screener.py`
- Test: `tests/test_pipeline.py`

- [x] **Step 1: Write the failing tests**

Add tests for a shared helper that:
- fetches raw OHLCV once
- computes the full summary
- computes benchmark bounces
- attaches metadata
- returns both `summary_all` and the benchmark-filtered `summary`

- [x] **Step 2: Run the new pipeline tests and verify they fail**

Run: `rtk pytest -q tests/test_pipeline.py`
Expected: FAIL because `pipeline.py` and the shared API do not exist yet.

- [x] **Step 3: Implement the minimal shared pipeline module**

Create `pipeline.py` with a focused API, for example:
- `ScreeningArtifacts` dataclass
- `build_screening_artifacts(...) -> ScreeningArtifacts`

Keep filtering and sorting logic in `screener.py` for now; only extract the shared stage-1 assembly needed by both CLIs.

- [x] **Step 4: Rewire `screener.py` to use `pipeline.py`**

Replace duplicated stage-1 setup in `run()` with the shared helper while keeping current CLI behavior unchanged.

- [x] **Step 5: Run the targeted tests and then the closest regression set**

Run:
- `rtk pytest -q tests/test_pipeline.py`
- `rtk pytest -q tests/test_screener_benchmark.py tests/test_integration.py`

Expected: PASS

### Task 2: Add Warm-Cache-Only Fetch Path

**Files:**
- Modify: `fetcher.py`
- Modify: `tests/test_fetcher_cache.py`

- [x] **Step 1: Write the failing tests**

Add tests proving a cache-only path:
- returns cached data when coverage is complete
- does not call download on cache miss
- raises or returns a typed cache-miss status on partial coverage

- [x] **Step 2: Run the cache-only tests and verify they fail**

Run: `rtk pytest -q tests/test_fetcher_cache.py -k cache_only`
Expected: FAIL because the cache-only API does not exist.

- [x] **Step 3: Implement the minimal cache-only behavior**

Add a dedicated API in `fetcher.py`, not a boolean explosion on `fetch_data()`.
Suggested shape:
- `class CacheMissError(RuntimeError): ...`
- `fetch_data_cached_only(...) -> pd.DataFrame`

- [x] **Step 4: Run the updated cache tests**

Run: `rtk pytest -q tests/test_fetcher_cache.py`
Expected: PASS

### Task 3: Extend Trade Setup Contract

**Files:**
- Modify: `strategies.py`
- Modify: `tests/test_strategies.py`

- [x] **Step 1: Write the failing tests**

Add tests proving every emitted `TradeSetup` includes:
- `invalidation_rule`
- `risk_per_share`

Use the fixed v1 invalidation rule:
- `"invalid if price trades below stop"`

- [x] **Step 2: Run the strategy tests and verify they fail**

Run: `rtk pytest -q tests/test_strategies.py`
Expected: FAIL because the new fields are not present yet.

- [x] **Step 3: Implement the minimal setup contract change**

Update `TradeSetup` and `strategy()` with:
- `risk_per_share = entry - stop`
- `invalidation_rule = "invalid if price trades below stop"`

- [ ] **Step 4: Run the strategy and chart-adjacent regressions**

Blocked in the current environment by missing optional runtime dependencies:
- `plotly` for `tests/test_charts.py`
- `scipy` for detector-backed integration paths

Run:
- `rtk pytest -q tests/test_strategies.py`
- `rtk pytest -q tests/test_charts.py tests/test_integration.py`

Expected: PASS

### Task 4: Build Deterministic Decision Ticket Engine

**Files:**
- Create: `decision_tickets.py`
- Create: `tests/test_decision_tickets.py`

- [x] **Step 1: Write the failing tests**

Cover:
- fixed v1 weights
- exact tie-break order
- one-ticket-per-ticker consolidation
- top-3 truncation
- fallback behavior for `0`, `1`, `2`, `3+`
- reject `risk_per_share <= 0`
- reject `final shares < 1`
- apply `max_position_dollars` cap

- [x] **Step 2: Run the decision ticket tests and verify they fail**

Run: `rtk pytest -q tests/test_decision_tickets.py`
Expected: FAIL because the engine does not exist.

- [x] **Step 3: Implement the minimal ticket engine**

Create:
- candidate dataclasses
- deterministic score computation
- per-ticker consolidation
- fixed-risk sizing
- JSON-ready ticket serialization

Lock the approved v1 weights and tie-breaks in module-level constants.

- [x] **Step 4: Run the decision ticket tests**

Run: `rtk pytest -q tests/test_decision_tickets.py`
Expected: PASS

### Task 5: Add Stable Ticket Rendering

**Files:**
- Modify: `display.py`
- Modify: `tests/test_display.py`

- [x] **Step 1: Write the failing tests**

Add tests for:
- plain-text ticket output column order
- empty-ticket output sentinel
- rich/table mode header order

- [x] **Step 2: Run the display tests and verify they fail**

Run: `rtk pytest -q tests/test_display.py`
Expected: FAIL because ticket rendering helpers do not exist.

- [x] **Step 3: Implement minimal ticket rendering**

Add dedicated helpers for decision tickets rather than overloading `show_results()`.

- [x] **Step 4: Run the display tests**

Run: `rtk pytest -q tests/test_display.py`
Expected: PASS

### Task 6: Add `main.py` Decision Ticket CLI

**Files:**
- Create: `main.py`
- Create: `tests/test_main.py`
- Create: `schemas/decision_ticket_v1.json`
- Create: `tests/test_schema.py`

- [x] **Step 1: Write the failing tests**

Cover:
- parser arguments
- cache-only timed path
- `NO_VALID_SETUPS` + `[]`
- `1` or `2` valid tickets preserve order
- `3+` tickets truncate to top 3
- stable JSON field set

- [x] **Step 2: Run the new CLI tests and verify they fail**

Run:
- `rtk pytest -q tests/test_main.py`
- `rtk pytest -q tests/test_schema.py`

Expected: FAIL because `main.py` and the schema file do not exist.

- [x] **Step 3: Implement the minimal CLI**

`main.py` should:
- call `build_screening_artifacts(...)`
- use cache-only fetch on the timed path
- build candidates from pattern + setup outputs
- rank and size tickets
- render table or JSON output

- [x] **Step 4: Run the CLI test set**

Run:
- `rtk pytest -q tests/test_main.py tests/test_schema.py`

Expected: PASS

### Task 7: Final Verification

**Files:**
- No new files

- [x] **Step 1: Run the focused regression suite**

Run:
- `rtk pytest -q tests/test_pipeline.py tests/test_fetcher_cache.py tests/test_strategies.py tests/test_decision_tickets.py tests/test_display.py tests/test_main.py tests/test_schema.py`

- [x] **Step 2: Run the broader repo regression suite**

Run: `rtk pytest -q tests/`
Expected: PASS

- [x] **Step 3: Record any residual risk**

Residual notes:
- The repo-wide suite now passes after installing `plotly` and `scipy`; `requirements.txt` was updated to reflect that runtime/test dependency surface.
- Warm-cache SLA for a real `sp500` cache is still not benchmarked by the automated suite; current verification is correctness-oriented, not timed performance verification.
