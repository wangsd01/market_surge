# Market Surge Working Design

## Purpose

This file is the reconciled working design for the current repository.

It has one job: make the project status and intended architecture obvious without forcing
the reader to guess what is already implemented versus what is still planned.

Use this file as the day-to-day engineering reference.

Use `/home/wang/.gstack/projects/market_surge/wang-main-design-20260412-224215.md`
as the upstream approved product and architecture spec. That upstream file contains the
full quantitative pattern definitions and the original phase plan.

## Document Role

This is not a pure "current implementation" note, and it is not the full future-state
spec either.

This file is a working design that separates:
- what exists in the repo today
- what the target architecture should become
- what design decisions are still open

## Project Goal

Build a Python CLI trading workflow around one coherent pipeline:
1. Screen stocks with strong rebounds from a configurable recent-low window.
2. Run pattern recognition only on screened stocks.
3. Generate informational trade setups only for stocks with detected patterns.
4. Render charts that combine price action, pattern geometry, and strategy levels.

## Source of Truth

### Upstream approved design

File:
- `/home/wang/.gstack/projects/market_surge/wang-main-design-20260412-224215.md`

That document is the source of truth for:
- target module boundaries
- pattern definitions
- strategy geometry
- long-term CLI direction

### This document

This file is the source of truth for:
- current repo status
- the transition from current code to target architecture
- unresolved design and persistence decisions

## Current Implementation Status

Implemented in the repo today:
- Universe fetch from the SEC company tickers feed for `all`
- Universe fetch from Wikipedia's S&P 500 constituents table for `sp500`
- OHLCV ingestion from Yahoo Finance via `yfinance`
- Benchmark-relative filtering using `QLD` and `TQQQ`
- Sector and industry enrichment from Yahoo metadata
- 52-week-high enrichment from Yahoo metadata
- Pattern detection for cup-with-handle, double bottom, VCP, channel, and support/resistance
- Strategy generation from detected patterns
- Plotly chart rendering with pattern overlays and optional strategy annotations
- CLI output with rich table in TTY mode and plain text in scheduled mode
- SQLite persistence for screening runs, raw OHLCV cache, invalid Yahoo symbols, and ticker metadata
- CSV export for the ranked screening result set

Partially implemented or not yet aligned with the target architecture:
- There is no dedicated `main.py` orchestrator yet
- `screener.py` currently owns both stage 1 and the downstream pattern/strategy/chart flags
- Pattern and strategy outputs are recomputed from cached price data, not persisted as stage artifacts
- Screening run persistence does not capture the full set of CLI parameters needed for exact replay
- The daily unique run model is too coarse for multiple runs with different parameters on the same date

## Current CLI Behavior

Current entry point:
- `screener.py`

Current supported args:
- `--low-start` default `2026-03-30`
- `--low-end` default `2026-04-12`
- `--min-price` default `5.0`
- `--min-dollar-vol` default `50_000_000`
- `--min-pct-of-52wk-high` default `0.70`
- `--top` default `20`
- `--universe` choices `all|sp500`
- `--refresh` force fresh Yahoo downloads and fresh metadata lookup
- `--schedule` force plain text output and show top 10
- `--output` default `ranking_all.csv`
- `--sort` choices `bounce|dollar_vol|price`, default `bounce`
- `--benchmark-mode` choices `all|any|qld|tqqq`, default `any`
- `--exclude-sections` comma-separated case-insensitive sector/industry exclusions, default `biotechnology`
- `--patterns` run pattern detection for the screened result set
- `--strategy TICKER` print strategy setups for a requested ticker
- `--chart TICKER` render a chart for a requested ticker

Important current behavior:
- `--patterns`, `--strategy`, and `--chart` are implemented inside `screener.py`
- `--strategy` and `--chart` currently recompute patterns from cached OHLCV data on demand
- `--chart` may still render without a generated setup if no strategy is available

## Target Architecture

The intended end state remains the same as the upstream approved design:

1. `screener.py` owns stage 1 only:
   screening, ranking, and persistence of screened candidates.
2. `main.py` becomes the high-level orchestrator for stages 2 to 4:
   pattern detection, strategy generation, and chart rendering.
3. `patterns/` remains the pattern engine package.
4. `strategies.py` converts a `PatternResult` into a `TradeSetup`.
5. `charts.py` renders price, pivots, support/resistance, and optional setup levels.

Target CLI shape:
- `python screener.py`
- `python main.py --patterns`
- `python main.py --strategy AAPL`
- `python main.py --chart AAPL`

## Recommended Transition Rule

Until `main.py` exists, the repo should treat the current `screener.py` downstream flags as
temporary integration behavior, not as the final interface contract.

That avoids two bad outcomes:
- pretending the target architecture already exists
- locking the temporary CLI shape into the design forever

## Data Sources

- SEC ticker universe: `https://www.sec.gov/files/company_tickers_exchange.json`
- S&P 500 universe: Wikipedia constituents table
- Price history: Yahoo Finance historical bars through `yfinance.download(...)`
- Ticker metadata: Yahoo Finance profile and quote metadata through `yf.Ticker(...).info`

Important constraint:
- The SEC feed is useful for broad universe discovery, but it is not a reliable
  "Yahoo-tradable right now" source. Some SEC-listed symbols have no usable Yahoo history.
  The repo mitigates this with a local invalid-symbol cache.

## Current Data Flow

1. Select the requested universe:
   - `all` uses the SEC feed
   - `sp500` uses Wikipedia
2. Append benchmark tickers `QLD` and `TQQQ`
3. Fetch raw OHLCV data through the cache-first SQLite path
4. Compute summary metrics per ticker:
   - low price and low date within `[low_start, low_end]`
   - current close
   - bounce percent
   - trailing 50-day average volume
5. Compute benchmark bounces for `QLD` and `TQQQ`
6. Apply benchmark-relative filtering
7. Enrich tickers with sector, industry, and 52-week-high metadata
8. Apply sector/industry exclusions
9. Apply price, 52-week-high, and dollar-volume filters
10. Persist the filtered screening result set
11. If requested, run pattern detection on filtered names
12. If requested, compute strategy setups from detected patterns
13. If requested, render charts using the pattern output and optional setup

## Persistence Model

Database file:
- `market_surge.db`

Current persisted tables:
- `screening_runs`
- `results`
- `raw_price_history`
- `invalid_tickers`
- `ticker_metadata`

### Current reality

What is persisted now:
- screening run timestamp
- a subset of screening parameters
- screened result rows
- raw price history
- invalid Yahoo symbols
- ticker metadata

What is not persisted now:
- pattern detection outputs
- generated trade setups
- the full CLI parameter set needed to replay a run exactly

## Recommended Persistence Direction

Recommendation:
- Keep `raw_price_history` as the shared source for screening, pattern detection,
  strategy generation, and charting.
- Continue recomputing patterns and strategies from cached OHLCV data during this phase.
- Do not add pattern/setup persistence until there is a concrete need for replay,
  audit history, or expensive downstream computation.

Reason:
- Raw price history is already the durable shared dataset.
- Persisting stage 2 and stage 3 artifacts now adds schema and invalidation complexity.
- The current project is still stabilizing its CLI and pattern definitions.

What should be added soon:
- full screening run parameter capture in `screening_runs`
- better run identity than one unique run per calendar day
- explicit documentation of replay semantics

## Known Design Gaps

### 1. Exact role of `main.py`

Decision:
- `main.py` is still the intended target orchestrator.

Gap:
- the file does not exist yet, so the current repo behavior still lives in `screener.py`.

### 2. Recompute versus persist downstream artifacts

Decision:
- recompute patterns and strategies from cached OHLCV data for now.

Gap:
- the doc must stay explicit that stage outputs are derived on demand, not stored artifacts.

### 3. Screening run reproducibility

Gap:
- current persistence does not save enough parameters to exactly replay a historical run.

Needed fields include at least:
- `universe`
- `sort`
- `benchmark_mode`
- `exclude_sections`
- `min_pct_of_52wk_high`
- `top`
- refresh behavior, or at least whether refresh was requested

### 4. Run uniqueness

Gap:
- one unique run per day is not a good long-term model when the same day may contain
  multiple experiments with different parameters.

Recommendation:
- make `run_at` fully unique and remove the date-level uniqueness assumption.

### 5. Default low window behavior

Gap:
- hard-coded default dates will age badly.

Recommendation:
- move to rolling market-date defaults such as "last N trading days" rather than fixed literals.

### 6. Naming drift

Gap:
- `--exclude-sections` now matches both sector and industry, but the name still reflects
  the older single-field model.

Recommendation:
- rename it later to `--exclude-tags`, or split into `--exclude-sectors` and `--exclude-industries`.

## Output Model

Current screening CSV fields:
- `Ticker`
- `low_date`
- `low_price`
- `current_price`
- `bounce_pct`
- `avg_vol_50d_m`
- `sector`
- `industry`
- `dollar_vol_m`

Current downstream outputs:
- Pattern detection prints ticker, pattern name, and confidence
- Strategy output prints entry, stop, target, risk/reward, and risk percent
- Chart output renders candlesticks, pivot annotations, support/resistance levels, and strategy lines when available

## Next Design Priorities

1. Add `main.py` and move downstream orchestration out of `screener.py`
2. Expand `screening_runs` so historical runs are reproducible
3. Replace the per-day unique run model
4. Convert fixed default dates into rolling defaults
5. Decide whether downstream artifact persistence is actually needed after the CLI stabilizes

## Summary

The project is incomplete, but the direction is clear.

The current repo already has the core ingredients of the full toolkit. The main thing this
document fixes is ambiguity: it makes the difference between current behavior and target
architecture explicit, and it records the few design decisions that still need to be locked.
