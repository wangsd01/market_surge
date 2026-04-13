# Market Surge Screener Design

## Scope

Build a Python CLI screener that finds stocks with strong rebounds from a configurable recent-low window, while enforcing minimum price, liquidity, and benchmark-relative strength filters.

Current implemented scope:
- Universe fetch from the SEC company tickers feed for `all`
- Universe fetch from Wikipedia's S&P 500 constituents table for `sp500`
- OHLCV data ingestion from Yahoo Finance via `yfinance`
- Benchmark-relative filtering using `QLD` and `TQQQ`
- Sector and industry enrichment from Yahoo profile metadata
- CLI output with rich table in TTY mode and plain text in non-TTY / scheduled mode
- SQLite persistence for screening runs, raw OHLCV cache, invalid Yahoo symbols, and ticker metadata
- CSV export for the ranked result set

## CLI Interface

Entry point: `screener.py`

Supported args:
- `--low-start` default `2026-03-30`
- `--low-end` default `2026-04-12`
- `--min-price` default `5.0`
- `--min-dollar-vol` default `50_000_000`
- `--top` default `20`
- `--universe` choices `all|sp500`
- `--refresh` force fresh Yahoo downloads and fresh metadata lookup
- `--schedule` force plain text output and show top 10
- `--output` default `ranking_all.csv`
- `--sort` choices `bounce|dollar_vol|price`, default `bounce`
- `--benchmark-mode` choices `all|any|qld|tqqq`, default `any`
- `--exclude-sections` comma-separated case-insensitive sector/industry exclusions, default `biotechnology`

Reference tickers:
- `QLD`
- `TQQQ`

These are always appended to the requested universe so benchmark bounce thresholds can be computed even if they are not part of the selected stock universe.

## Data Sources

- SEC ticker universe: `https://www.sec.gov/files/company_tickers_exchange.json`
- S&P 500 universe: Wikipedia constituents table
- Price history: Yahoo Finance historical bars through `yfinance.download(...)`
- Sector / industry metadata: Yahoo Finance per-ticker profile metadata through `yf.Ticker(...).info`

Important constraint:
- The SEC feed is used as a broad listed-symbol universe source, but it is not a reliable "Yahoo-tradable right now" source. Some SEC-listed symbols have no usable Yahoo history. The app now detects and caches those misses locally.

## Data Flow

1. Select universe:
   - `all` uses `get_tickers()` from the SEC feed.
   - `sp500` uses `get_sp500_tickers()` from Wikipedia.
2. Append benchmark tickers `QLD` and `TQQQ`.
3. `fetch_data(...)` uses cache-first raw price logic:
   - Open `market_surge.db`
   - Drop symbols already marked invalid for Yahoo from the request set
   - Check `raw_price_history` coverage for the remaining tickers/date range
   - If coverage is incomplete or `--refresh` is set, download missing tickers in batches of 100
   - Persist successful OHLCV rows to SQLite
   - Persist tickers that Yahoo returned with no rows into `invalid_tickers`
   - Return normalized OHLCV rows by reading back from SQLite
4. Compute summary metrics per ticker:
   - low price and low date in `[low_start, low_end]`
   - current close
   - bounce percent from low to current close
   - trailing 50-day average volume
5. Compute benchmark bounces for `QLD` and `TQQQ`.
6. Apply benchmark-relative filter:
   - `all`: ticker must beat the stronger of `QLD` and `TQQQ`
   - `any`: ticker must beat the weaker of `QLD` and `TQQQ`
   - `qld` or `tqqq`: ticker must beat the selected reference
7. Enrich the working set with sector and industry:
   - Read cached metadata from `ticker_metadata`
   - Fetch missing metadata from Yahoo
   - For equities, prefer Yahoo `sector` / `industry`
   - For ETFs, fall back to labels like `ETF` plus Yahoo fund category
8. Apply exclusion filter:
   - Match requested exclusions against both `sector` and `industry`
   - Default behavior removes `Biotechnology` industry names
9. Apply price and dollar-volume filters.
10. Sort, display, export CSV, and persist the filtered run into `results`.

## Output Model

The CSV output includes:
- `Ticker`
- `low_date`
- `low_price`
- `current_price`
- `bounce_pct`
- `avg_vol_50d_m`
- `sector`
- `industry`
- `dollar_vol_m`

The plain-text / console display shows:
- ticker
- low date
- low price
- current price
- bounce percent
- dollar volume
- sector
- industry

## SQLite Model

Database file: `market_surge.db`

### `screening_runs`
- `id INTEGER PRIMARY KEY`
- `run_at TIMESTAMP`
- `low_start DATE`
- `low_end DATE`
- `min_price FLOAT`
- `min_dollar_vol FLOAT`
- unique index on `date(run_at)`

### `results`
- `run_id INTEGER` FK to `screening_runs(id)` with cascade delete
- `ticker TEXT`
- `low_date DATE`
- `low_price FLOAT`
- `current_price FLOAT`
- `bounce_pct FLOAT`
- `dollar_vol FLOAT`
- `sector TEXT`
- `industry TEXT`
- primary key `(run_id, ticker)`
- indexes on `ticker` and `bounce_pct DESC`

### `raw_price_history`
- `date DATE`
- `ticker TEXT`
- `open FLOAT`
- `high FLOAT`
- `low FLOAT`
- `close FLOAT`
- `volume FLOAT`
- primary key `(date, ticker)`
- index `(ticker, date)`

### `invalid_tickers`
- `ticker TEXT`
- `source TEXT`
- `reason TEXT`
- `detected_at TIMESTAMP`
- primary key `(ticker, source)`

Current usage:
- source is `yfinance`
- rows mean "Yahoo returned no usable history for this symbol and range"

### `ticker_metadata`
- `ticker TEXT PRIMARY KEY`
- `sector TEXT`
- `industry TEXT`
- `updated_at TIMESTAMP`

## Caching Behavior

### Price cache
- Raw OHLCV is cached in SQLite, not parquet.
- Returned price data is always normalized through SQLite reads.
- `--refresh` bypasses the raw-history cache and redownloads requested symbols.

### Invalid-symbol cache
- Symbols that Yahoo returns with no usable rows are persisted in `invalid_tickers`.
- Subsequent runs skip those symbols before the main history query.
- This reduces repeated "possibly delisted" noise and wasted Yahoo calls.

### Metadata cache
- Sector and industry data is cached in `ticker_metadata`.
- First metadata-enriched run is slower because per-ticker Yahoo profile calls are required.
- Later runs reuse cached metadata unless `--refresh` is set.

## Universe Rules

`get_tickers()` currently applies these SEC-side filters:
- allow only `NASDAQ`, `NYSE`, `CBOE`
- drop symbols containing `-`
- drop suffixes commonly associated with warrants / rights / units / special share classes: `W`, `R`, `P`, `Q`, `U`
- keep rows only when SEC SIC logic passes the current filter implemented in code

Note:
- These rules are pragmatic, not authoritative market-status truth.
- Tradability is ultimately verified by whether Yahoo returns usable price data.

## Known Constraints

- SEC listing membership and Yahoo symbol availability still do not match perfectly. The invalid-symbol cache mitigates this after discovery, but the first encounter still requires a failed Yahoo lookup.
- Metadata enrichment depends on Yahoo profile coverage. ETFs generally do not expose equity-style sector/industry labels, so the implementation falls back to values like `ETF` and fund category.
- `--exclude-sections` is still named after the old single-field model, but it now matches both sector and industry values.
- There is no explicit offline mode. Missing cache coverage still triggers network fetches unless blocked externally.

## Future Iterations

- Rename `--exclude-sections` to something clearer like `--exclude-tags` or split it into `--exclude-sectors` and `--exclude-industries`.
- Add staleness windows for `ticker_metadata` and `invalid_tickers` instead of treating them as effectively permanent until refresh.
- Tighten the SEC universe filter logic so it better matches the intended tradable stock universe before Yahoo discovery.
- Add explicit offline behavior for cache-only runs.
- Future modules such as pattern recognition or order / stop planning can continue reusing `raw_price_history` as the shared historical price store.
