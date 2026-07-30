# Yahoo Metadata Rate-Limit Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Yahoo metadata lookup fail softly, persist partial successes, and stop repeatedly fetching cached null 52-week highs.

**Architecture:** Keep the change inside `get_ticker_metadata`. Cache membership, rather than 52-week-high completeness, decides whether a ticker needs fetching; individual future failures are logged and omitted while successful responses are saved and returned.

**Tech Stack:** Python, yfinance, SQLite, `concurrent.futures`, standard-library logging, pytest

---

## File Structure

- Modify `fetcher.py`: change metadata cache-miss selection and isolate individual concurrent lookup failures.
- Modify `tests/test_fetcher.py`: add focused regression tests for cached null metadata, partial failures, deterministic warnings, persistence, and refresh behavior.

No database schema, pipeline, filter, or price-cache changes are required.

### Task 1: Reuse Cached Null Metadata

**Files:**
- Modify: `tests/test_fetcher.py`
- Modify: `fetcher.py:210-238`

- [ ] **Step 1: Write the failing cached-null regression test**

Add `get_ticker_metadata` to the existing `from fetcher import (...)` block and
add the exact database imports:

```python
from db import get_ticker_metadata as get_cached_ticker_metadata, init_db, save_ticker_metadata
```

Then add:

```python
def test_get_ticker_metadata_reuses_cached_null_high(tmp_path, monkeypatch):
    db_path = tmp_path / "metadata.db"
    conn = init_db(db_path)
    save_ticker_metadata(
        conn,
        {
            "NULL": {
                "sector": "Technology",
                "industry": "Software",
                "fifty_two_week_high": None,
            }
        },
    )
    conn.close()

    def unexpected_fetch(_ticker):
        raise AssertionError("cached ticker should not be fetched")

    monkeypatch.setattr("fetcher._fetch_ticker_metadata_for_ticker", unexpected_fetch)

    result = get_ticker_metadata(["NULL"], db_path=db_path)

    assert result["NULL"]["fifty_two_week_high"] is None
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python -m pytest -q tests/test_fetcher.py::test_get_ticker_metadata_reuses_cached_null_high
```

Expected: FAIL because the current `missing` predicate submits `NULL` to Yahoo when its cached 52-week high is null.

- [ ] **Step 3: Implement the minimal cache-membership fix**

In `get_ticker_metadata`, replace the missing predicate with:

```python
missing = [ticker for ticker in normalized if ticker not in cached]
```

Keep `cached = {}` under `refresh=True`, so refresh continues to request every normalized ticker.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
python -m pytest -q tests/test_fetcher.py::test_get_ticker_metadata_reuses_cached_null_high
```

Expected: PASS.

- [ ] **Step 5: Commit the cache-membership change**

```bash
git add fetcher.py tests/test_fetcher.py
git commit -m "fix: reuse cached null ticker metadata"
```

### Task 2: Preserve Partial Metadata Results on Rate Limits

**Files:**
- Modify: `tests/test_fetcher.py`
- Modify: `fetcher.py:1-10,210-238`

- [ ] **Step 1: Write the failing partial-failure regression test**

Add `import logging`; the database getter is already imported under the
unambiguous alias `get_cached_ticker_metadata`. Then add:

```python
def test_get_ticker_metadata_saves_successes_and_warns_on_failures(tmp_path, monkeypatch, caplog):
    db_path = tmp_path / "metadata.db"
    good = {
        "sector": "Technology",
        "industry": "Semiconductors",
        "fifty_two_week_high": 150.0,
    }

    def fetch(ticker):
        if ticker in {"ZZZ", "AAA"}:
            raise RuntimeError("Too Many Requests")
        return ticker, good

    monkeypatch.setattr("fetcher._fetch_ticker_metadata_for_ticker", fetch)

    with caplog.at_level(logging.WARNING, logger="fetcher"):
        result = get_ticker_metadata(["ZZZ", "GOOD", "AAA"], db_path=db_path)

    assert result == {"GOOD": good}
    assert caplog.messages == ["Yahoo metadata unavailable for 2 tickers: AAA, ZZZ"]

    conn = init_db(db_path)
    persisted = get_cached_ticker_metadata(conn, ["GOOD", "AAA", "ZZZ"])
    conn.close()
    assert persisted == {"GOOD": good}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python -m pytest -q tests/test_fetcher.py::test_get_ticker_metadata_saves_successes_and_warns_on_failures
```

Expected: FAIL because the first failed future currently escapes, prevents successful metadata from being returned, and can bypass persistence.

- [ ] **Step 3: Implement per-future failure isolation**

Add module logging setup:

```python
import logging

logger = logging.getLogger(__name__)
```

Retain the ticker for each future and catch its exception:

```python
futures = {
    executor.submit(_fetch_ticker_metadata_for_ticker, ticker): ticker
    for ticker in missing
}
failed = []
for future in as_completed(futures):
    ticker = futures[future]
    try:
        fetched_ticker, metadata = future.result()
    except Exception:
        failed.append(ticker)
        continue
    fetched[fetched_ticker] = metadata
```

After the executor finishes, save `fetched` regardless of failures, then log one deterministic warning:

```python
save_ticker_metadata(conn, fetched)
if failed:
    failed = sorted(failed)
    logger.warning(
        "Yahoo metadata unavailable for %d tickers: %s",
        len(failed),
        ", ".join(failed),
    )
```

Do not log exception bodies or add retries; the desired behavior is fail-soft and concise.

- [ ] **Step 4: Run both focused tests and verify GREEN**

Run:

```bash
python -m pytest -q \
  tests/test_fetcher.py::test_get_ticker_metadata_reuses_cached_null_high \
  tests/test_fetcher.py::test_get_ticker_metadata_saves_successes_and_warns_on_failures
```

Expected: 2 passed.

- [ ] **Step 5: Commit fail-soft handling**

```bash
git add fetcher.py tests/test_fetcher.py
git commit -m "fix: tolerate Yahoo metadata rate limits"
```

### Task 3: Characterize Refresh and Run Regression Verification

**Files:**
- Modify: `tests/test_fetcher.py`

- [ ] **Step 1: Add the refresh behavior characterization test**

This is intentionally a green-only preservation test: `refresh=True` already
fetches cached tickers, and Tasks 1 and 2 must not change that behavior. The
bug-fix behaviors themselves have RED/GREEN coverage in the preceding tasks.

```python
def test_get_ticker_metadata_refreshes_cached_ticker(tmp_path, monkeypatch):
    db_path = tmp_path / "metadata.db"
    conn = init_db(db_path)
    save_ticker_metadata(
        conn,
        {
            "AAA": {
                "sector": "Old",
                "industry": "Old",
                "fifty_two_week_high": None,
            }
        },
    )
    conn.close()
    refreshed = {
        "sector": "Technology",
        "industry": "Software",
        "fifty_two_week_high": 200.0,
    }
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        return ticker, refreshed

    monkeypatch.setattr("fetcher._fetch_ticker_metadata_for_ticker", fetch)

    result = get_ticker_metadata(["AAA"], db_path=db_path, refresh=True)

    assert calls == ["AAA"]
    assert result == {"AAA": refreshed}
```

- [ ] **Step 2: Run all metadata-focused tests**

Run:

```bash
python -m pytest -q tests/test_fetcher.py -k "ticker_metadata"
```

Expected: all selected tests pass.

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
python -m pytest -q tests/
```

Expected: all tests pass with no new failures.

- [ ] **Step 4: Inspect the final scoped diff**

Run:

```bash
git diff --check
git status --short
git diff -- fetcher.py tests/test_fetcher.py
```

Expected: no whitespace errors; implementation changes are limited to metadata fetching and focused tests. Pre-existing unrelated working-tree changes remain untouched.

- [ ] **Step 5: Commit the refresh regression test if it was not included earlier**

```bash
git add tests/test_fetcher.py
git commit -m "test: preserve metadata refresh behavior"
```
