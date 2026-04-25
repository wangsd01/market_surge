# Detected Pattern Debug Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in debug mode that saves one combined HTML chart per screened ticker with overlays for detected `cup_handle`, `double_bottom`, `flat_base`, `vcp`, and `high2` patterns, including non-actionable detections.

**Architecture:** Reuse the existing Plotly renderer in `charts.py` and add a second save path in `main.py` instead of creating a separate charting system. The renderer gains pattern markers, connecting lines, and an optional status block for debug charts, while ticket-backed chart output remains intact.

**Tech Stack:** Python, pandas, Plotly, pytest

---

### Task 1: Add failing chart-renderer tests

**Files:**
- Modify: `tests/test_charts.py`
- Modify: `charts.py`

- [ ] Add a failing test asserting debug charts prefix annotations with the pattern name and include a grouped status block.
- [ ] Add a failing test asserting combined debug charts draw connecting geometry for multiple patterns.
- [ ] Run `rtk pytest tests/test_charts.py -q` and confirm the new tests fail for the expected missing behavior.

### Task 2: Add failing main-flow tests

**Files:**
- Modify: `tests/test_main.py`
- Modify: `main.py`

- [ ] Add a failing test asserting `--save-detected-pattern-charts` creates `run_dir/detected_patterns/<ticker>.html`.
- [ ] Add a failing test asserting excluded patterns (`support_resistance`, `channel`) are not saved while stale-but-detected allowed patterns are saved.
- [ ] Add a failing test asserting one combined debug chart is written per screened ticker even when multiple allowed patterns are returned.
- [ ] Run `rtk pytest tests/test_main.py -q` and confirm the new tests fail for the expected missing behavior.

### Task 3: Implement renderer support

**Files:**
- Modify: `charts.py`
- Test: `tests/test_charts.py`

- [ ] Add minimal helper logic for deterministic allowed-pattern ordering, per-pattern colors, pivot connection sequences, and optional status rows.
- [ ] Extend `chart()` to render debug markers and connecting lines without breaking existing ticket chart behavior.
- [ ] Keep strategy/ticket annotations unchanged for the existing ticket-backed path.
- [ ] Run `rtk pytest tests/test_charts.py -q` and confirm the chart tests pass.

### Task 4: Implement the debug save path

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py`

- [ ] Add `--save-detected-pattern-charts` to `build_parser()`.
- [ ] Add a helper that iterates `filtered["Ticker"]`, calls `detect_all()`, filters to the allowed pattern set, computes status from `filtered["current_price"]`, and saves one combined chart per ticker under `detected_patterns/`.
- [ ] Keep `_save_ticket_charts()` behavior unchanged.
- [ ] Run `rtk pytest tests/test_main.py -q` and confirm the main-flow tests pass.

### Task 5: Final verification

**Files:**
- Modify: only files touched above

- [ ] Run `rtk pytest tests/test_charts.py tests/test_main.py -q`.
- [ ] Run `rtk pytest -q`.
- [ ] Review the diff to confirm the change stays scoped to the debug chart feature.
