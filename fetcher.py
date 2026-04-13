from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Sequence
import os
from io import StringIO
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
from db import (
    delete_price_history_for_date,
    delete_invalid_tickers,
    get_cached_price_history,
    get_invalid_tickers,
    get_ticker_metadata as get_cached_ticker_metadata,
    init_db,
    save_invalid_tickers,
    save_price_history,
    save_ticker_metadata,
)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_FIELD_NAMES = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
DEFAULT_SEC_USER_AGENT = "market-surge-screener/0.1 (contact: dev@example.com)"
ALLOWED_EXCHANGES = {"NASDAQ", "NYSE", "CBOE"}
BIOTECH_SECTION = "Biotechnology"
DEFAULT_SECTION = "Other"
DEFAULT_INDUSTRY = ""
_BIOTECH_KEYWORDS = (
    "THERAPEUTICS",
    "BIOTECH",
    "BIOSCIENCE",
    "BIOSCIENCES",
    "BIOPHARMA",
    "GENE THERAP",
)
_BIOTECH_SIC_CODES = {2834, 2835, 2836}
MARKET_TIMEZONE = ZoneInfo("America/New_York")


def _today_market_date():
    return datetime.now(MARKET_TIMEZONE).date()


def _fetch_sec_payload() -> tuple[list[Sequence[object]], dict[str, int]]:
    response = requests.get(
        SEC_TICKERS_URL,
        timeout=30,
        headers={
            "User-Agent": os.getenv("SEC_USER_AGENT", DEFAULT_SEC_USER_AGENT),
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        },
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    fields = payload.get("fields", []) if isinstance(payload, dict) else []
    field_to_idx = {str(name).strip().lower(): idx for idx, name in enumerate(fields)}
    return rows, field_to_idx


def _classify_section(name: str, sic: int | None, sic_description: str) -> str:
    tokens = f"{name} {sic_description}".upper()
    if sic in _BIOTECH_SIC_CODES:
        return BIOTECH_SECTION
    if any(keyword in tokens for keyword in _BIOTECH_KEYWORDS):
        return BIOTECH_SECTION
    return ""


def get_tickers() -> list[str]:
    rows, field_to_idx = _fetch_sec_payload()

    ticker_idx = field_to_idx.get("ticker", 2)
    sic_idx = field_to_idx.get("sic")
    exchange_idx = field_to_idx.get("exchange")

    out: list[str] = []
    for row in rows:
        if not isinstance(row, Sequence) or len(row) <= ticker_idx:
            continue
        ticker = str(row[ticker_idx]).strip().upper()
        if not ticker:
            continue
        if exchange_idx is None or len(row) <= exchange_idx:
            continue
        exchange = str(row[exchange_idx]).strip().upper()
        if exchange not in ALLOWED_EXCHANGES:
            continue
        if "-" in ticker:
            continue
        if ticker.endswith(("W", "R", "P", "Q", "U")):
            continue

        # SEC's exchange feed may not include SIC; if unavailable, keep ticker.
        if sic_idx is None or len(row) <= sic_idx:
            out.append(ticker)
            continue

        sic_raw = row[sic_idx]
        try:
            sic = int(sic_raw)
        except (TypeError, ValueError):
            continue
        if sic == 6500 or 6700 <= sic <= 6799:
            out.append(ticker)
    return sorted(set(out))


def get_ticker_sections(tickers: Sequence[str]) -> dict[str, str]:
    wanted = {str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()}
    if not wanted:
        return {}

    rows, field_to_idx = _fetch_sec_payload()
    ticker_idx = field_to_idx.get("ticker", 2)
    name_idx = field_to_idx.get("name")
    sic_idx = field_to_idx.get("sic")
    sic_desc_idx = field_to_idx.get("sicdescription")
    if sic_desc_idx is None:
        sic_desc_idx = field_to_idx.get("sic_description")

    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Sequence) or len(row) <= ticker_idx:
            continue
        ticker = str(row[ticker_idx]).strip().upper()
        if ticker not in wanted:
            continue

        name = ""
        if name_idx is not None and len(row) > name_idx and row[name_idx] is not None:
            name = str(row[name_idx]).strip()

        sic: int | None = None
        if sic_idx is not None and len(row) > sic_idx:
            try:
                sic = int(row[sic_idx])
            except (TypeError, ValueError):
                sic = None

        sic_description = ""
        if sic_desc_idx is not None and len(row) > sic_desc_idx and row[sic_desc_idx] is not None:
            sic_description = str(row[sic_desc_idx]).strip()

        section = _classify_section(name=name, sic=sic, sic_description=sic_description)
        out[ticker] = section or DEFAULT_SECTION
    return out


def _extract_ticker_metadata_from_info(info: dict[str, object] | None) -> dict[str, str]:
    payload = info if isinstance(info, dict) else {}

    def _clean(value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return "" if not text or text.lower() == "none" else text

    sector = (
        _clean(payload.get("sectorDisp"))
        or _clean(payload.get("sector"))
        or _clean(payload.get("typeDisp"))
        or _clean(payload.get("quoteType"))
        or _clean(payload.get("legalType"))
    )
    industry = (
        _clean(payload.get("industryDisp"))
        or _clean(payload.get("industry"))
        or _clean(payload.get("category"))
        or _clean(payload.get("fundFamily"))
    )
    return {"sector": sector, "industry": industry}


def _fetch_ticker_metadata_for_ticker(ticker: str) -> tuple[str, dict[str, str]]:
    info = yf.Ticker(ticker).info
    return ticker, _extract_ticker_metadata_from_info(info)


def get_ticker_metadata(
    tickers: Sequence[str],
    db_path: str | Path,
    refresh: bool = False,
) -> dict[str, dict[str, str]]:
    normalized = [str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()]
    if not normalized:
        return {}

    conn = init_db(db_path)
    try:
        cached = {} if refresh else get_cached_ticker_metadata(conn, normalized)
        missing = [ticker for ticker in normalized if ticker not in cached]
        fetched: dict[str, dict[str, str]] = {}
        if missing:
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(_fetch_ticker_metadata_for_ticker, ticker) for ticker in missing]
                for future in as_completed(futures):
                    ticker, metadata = future.result()
                    fetched[ticker] = metadata
            save_ticker_metadata(conn, fetched)
        out = dict(cached)
        out.update(fetched)
        return out
    finally:
        conn.close()


def get_sp500_tickers() -> list[str]:
    response = requests.get(
        SP500_URL,
        timeout=30,
        headers={
            "User-Agent": os.getenv("SEC_USER_AGENT", DEFAULT_SEC_USER_AGENT),
            "Accept-Encoding": "gzip, deflate",
        },
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    if not tables:
        return []
    table = tables[0]
    symbol_col = "Symbol" if "Symbol" in table.columns else table.columns[0]
    symbols = table[symbol_col].astype(str).str.strip().str.upper()
    # Yahoo uses '-' for class-share separators, e.g. BRK.B -> BRK-B
    symbols = symbols.str.replace(".", "-", regex=False)
    symbols = symbols[~symbols.str.contains("-", regex=False)]
    return sorted(set(symbols.tolist()))


def reshape_download_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])

    if not isinstance(df.columns, pd.MultiIndex):
        out = df.reset_index().rename(columns={"index": "Date"})
        if "Ticker" not in out.columns:
            out["Ticker"] = None
        return out

    working = df.copy()
    column_names = list(working.columns.names)
    if "Ticker" not in column_names:
        level_0 = set(map(str, working.columns.get_level_values(0)))
        level_1 = set(map(str, working.columns.get_level_values(1)))
        if level_0.issubset(_FIELD_NAMES) and not level_1.issubset(_FIELD_NAMES):
            column_names[1] = "Ticker"
        elif level_1.issubset(_FIELD_NAMES) and not level_0.issubset(_FIELD_NAMES):
            column_names[0] = "Ticker"
        else:
            column_names[-1] = "Ticker"
        working.columns = working.columns.set_names(column_names)

    shaped = working.stack(level="Ticker").rename_axis(["Date", "Ticker"]).reset_index()
    ordered_cols = ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]
    existing = [col for col in ordered_cols if col in shaped.columns]
    remainder = [col for col in shaped.columns if col not in existing]
    return shaped[existing + remainder]


def _observed_tickers(df: pd.DataFrame) -> set[str]:
    if df is None or df.empty or "Ticker" not in df.columns:
        return set()

    working = df.copy()
    price_cols = [col for col in ("Open", "High", "Low", "Close", "Volume") if col in working.columns]
    if price_cols:
        working = working.loc[~working[price_cols].isna().all(axis=1)].copy()
    if working.empty:
        return set()
    return {str(ticker).strip().upper() for ticker in working["Ticker"].dropna().tolist() if str(ticker).strip()}


def _download_batch(batch: Iterable[str], low_start: str, end_date: str) -> tuple[pd.DataFrame, list[str]]:
    requested = [str(ticker).strip().upper() for ticker in batch if str(ticker).strip()]
    raw = yf.download(
        requested,
        start=low_start,
        end=end_date,
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=False,
    )
    frame = reshape_download_frame(raw)
    observed = _observed_tickers(frame)
    missing = [ticker for ticker in requested if ticker not in observed]
    return frame, missing


def _download_batch_with_retry(batch: Iterable[str], low_start: str, end_date: str) -> tuple[pd.DataFrame, list[str]]:
    backoffs = [5, 10, 20]
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return _download_batch(batch, low_start=low_start, end_date=end_date)
        except Exception as exc:  # pragma: no cover - defensive branch
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(backoffs[attempt])
    if last_error is not None:  # pragma: no cover - defensive branch
        raise last_error
    return pd.DataFrame(), []


def _download_all_batches(tickers: Sequence[str], low_start: str, end_date: str) -> tuple[pd.DataFrame, list[str]]:
    batches = [tickers[i : i + 100] for i in range(0, len(tickers), 100)]
    frames: list[pd.DataFrame] = []
    unavailable: set[str] = set()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_download_batch_with_retry, batch, low_start, end_date)
            for batch in batches
            if batch
        ]
        for future in as_completed(futures):
            frame, missing = future.result()
            if frame is not None and not frame.empty:
                frames.append(frame)
            unavailable.update(missing)

    if not frames:
        return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]), sorted(unavailable)
    out = pd.concat(frames, ignore_index=True)
    if {"Date", "Ticker"}.issubset(out.columns):
        out = out.sort_values(["Date", "Ticker"]).reset_index(drop=True)
    unavailable.difference_update(_observed_tickers(out))
    return out, sorted(unavailable)


def fetch_data(
    tickers: Sequence[str],
    low_start: str,
    end_date: str,
    cache_dir: str | Path,
    refresh: bool = False,
    db_path: str | Path | None = None,
) -> pd.DataFrame:
    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    sqlite_path = Path(db_path) if db_path is not None else (cache_root / "raw_cache.db")
    conn = init_db(sqlite_path)
    try:
        delete_price_history_for_date(conn, _today_market_date().isoformat())
        invalid_source = "yfinance"
        known_invalid = get_invalid_tickers(conn, invalid_source)
        ticker_list = [
            ticker
            for ticker in dict.fromkeys(str(symbol).strip().upper() for symbol in tickers if str(symbol).strip())
            if ticker not in known_invalid
        ]
        if not refresh:
            cached = get_cached_price_history(conn, ticker_list, low_start, end_date)
            cached_tickers = set(cached["Ticker"].unique()) if not cached.empty and "Ticker" in cached.columns else set()
            missing = [ticker for ticker in ticker_list if ticker not in cached_tickers]
            if not missing:
                return cached
        else:
            missing = ticker_list

        downloaded, unavailable = _download_all_batches(missing, low_start, end_date) if missing else (pd.DataFrame(), [])
        if unavailable:
            save_invalid_tickers(
                conn,
                unavailable,
                source=invalid_source,
                reason=f"Yahoo returned no data for requested range {low_start}..{end_date}",
            )
        if downloaded is not None and not downloaded.empty:
            downloaded = downloaded.loc[
                pd.to_datetime(downloaded["Date"]).dt.date < _today_market_date()
            ].copy()
            delete_invalid_tickers(conn, list(_observed_tickers(downloaded)), source=invalid_source)
            save_price_history(conn, downloaded)
        return get_cached_price_history(conn, ticker_list, low_start, end_date)
    finally:
        conn.close()
