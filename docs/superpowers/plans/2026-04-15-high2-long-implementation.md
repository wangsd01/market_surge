# High 2 Long Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `high2` detector, register it in the active pattern pipeline, and add custom H2 trade setup handling in `strategies.py` with deterministic tests.

**Architecture:** Add a dedicated `patterns/high2.py` detector that emits one `PatternResult` using the approved H2 state-machine rules. Keep detector outputs strategy-agnostic, then add a small `high2` branch in `strategies.py` for custom target calculation while preserving the existing `TradeSetup` contract.

**Tech Stack:** Python, pandas, pytest

---

## File Map

- Create: `patterns/high2.py`
  Responsibility: detect one best H2 long setup from OHLCV data and emit a `PatternResult`.
- Modify: `patterns/__init__.py`
  Responsibility: activate `High2Detector` in the detector registry.
- Modify: `strategies.py`
  Responsibility: add H2 levels, risk table entry, and custom target calculation.
- Create: `tests/test_patterns/test_high2.py`
  Responsibility: detector TDD coverage for valid and rejected H2 sequences.
- Modify: `tests/test_patterns/test_registry.py`
  Responsibility: assert `high2` is active while disabled detectors stay excluded.
- Modify: `tests/test_strategies.py`
  Responsibility: assert H2 entry, stop, and target behavior.
- Modify: `tests/test_main.py`
  Responsibility: assert H2 flows through `build_candidates()` and respects shared recency filtering.

### Task 1: Add Failing H2 Detector Tests

**Files:**
- Create: `tests/test_patterns/test_high2.py`
- Modify: `tests/test_patterns/test_registry.py`

- [ ] **Step 1: Write the failing detector tests**
- [ ] **Step 2: Run `rtk pytest -q tests/test_patterns/test_high2.py tests/test_patterns/test_registry.py` and confirm failure**
- [ ] **Step 3: Implement the minimal `patterns/high2.py` detector and registry wiring**
- [ ] **Step 4: Re-run the detector tests and confirm they pass**

### Task 2: Add Failing H2 Strategy Tests

**Files:**
- Modify: `tests/test_strategies.py`
- Modify: `strategies.py`

- [ ] **Step 1: Write the failing H2 strategy tests**
- [ ] **Step 2: Run `rtk pytest -q tests/test_strategies.py -k high2` and confirm failure**
- [ ] **Step 3: Implement the minimal H2 strategy branch**
- [ ] **Step 4: Re-run the H2 strategy tests and confirm they pass**

### Task 3: Add Pipeline Integration Coverage

**Files:**
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing tests for recent and stale H2 candidate handling**
- [ ] **Step 2: Run `rtk pytest -q tests/test_main.py -k high2` and confirm failure**
- [ ] **Step 3: Make any minimal compatibility fixes required by the new detector/strategy behavior**
- [ ] **Step 4: Re-run the targeted main tests and confirm they pass**

### Task 4: Final Verification

**Files:**
- Verify only

- [ ] **Step 1: Run the full affected test slice**
- [ ] **Step 2: Confirm no fresh failures in H2 detector, strategy, registry, and main candidate flow**
