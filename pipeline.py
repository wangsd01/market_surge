from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from fetcher import (
    DEFAULT_INDUSTRY,
    DEFAULT_SECTION,
    _today_market_date,
    fetch_data,
    get_sp500_tickers,
    get_ticker_metadata,
    get_tickers,
)
from filters import compute_bounce

REFERENCE_TICKERS = ("QLD", "TQQQ")
PATTERN_LOOKBACK_DAYS = 180


@dataclass
class ScreeningArtifacts:
    raw_df: pd.DataFrame
    summary_all: pd.DataFrame
    summary: pd.DataFrame
    benchmark_bounces: dict[str, float]


def build_screening_artifacts(
    *,
    universe: str,
    low_start: str,
    low_end: str,
    refresh: bool,
    benchmark_mode: str,
    needs_pattern_history: bool,
    cache_dir: str | Path,
    db_path: str | Path,
    select_universe_fn: Callable[[str], list[str]] | None = None,
    today_market_date_fn: Callable[[], object] | None = None,
    fetch_data_fn: Callable[..., pd.DataFrame] | None = None,
    metadata_fn: Callable[..., dict[str, dict[str, str]]] | None = None,
    reference_tickers: tuple[str, ...] = REFERENCE_TICKERS,
) -> ScreeningArtifacts:
    select_universe = select_universe_fn or _select_universe
    today_market_date = today_market_date_fn or _today_market_date
    fetch_prices = fetch_data_fn or fetch_data
    get_metadata = metadata_fn or get_ticker_metadata

    tickers = _with_reference_tickers(select_universe(universe), reference_tickers=reference_tickers)
    end_date = today_market_date().isoformat()
    fetch_start = _resolve_fetch_start(
        low_start=low_start,
        end_date=end_date,
        needs_pattern_history=needs_pattern_history,
    )
    raw_df = fetch_prices(
        tickers=tickers,
        low_start=fetch_start,
        end_date=end_date,
        cache_dir=Path(cache_dir),
        refresh=refresh,
        db_path=Path(db_path),
    )
    summary_all = _compute_summary(raw_df, low_start=low_start, low_end=low_end)
    benchmark_bounces = _compute_benchmark_bounces(
        raw_df,
        low_start=low_start,
        low_end=low_end,
        reference_tickers=reference_tickers,
    )
    summary = _apply_benchmark_filter(
        summary_all,
        benchmark_bounces=benchmark_bounces,
        reference_tickers=reference_tickers,
        mode=benchmark_mode,
    )
    metadata_by_ticker = get_metadata(
        _with_reference_tickers(summary["Ticker"].tolist(), reference_tickers=reference_tickers),
        db_path=Path(db_path),
        refresh=refresh,
    )
    summary_all = _attach_metadata(summary_all, metadata_by_ticker)
    summary = _attach_metadata(summary, metadata_by_ticker)
    return ScreeningArtifacts(
        raw_df=raw_df,
        summary_all=summary_all,
        summary=summary,
        benchmark_bounces=benchmark_bounces,
    )


def _select_universe(universe: str) -> list[str]:
    if universe == "sp500":
        return get_sp500_tickers(cache_path=Path("cache") / "sp500_tickers.txt")
    return get_tickers()


def _with_reference_tickers(
    tickers: list[str], reference_tickers: tuple[str, ...] = REFERENCE_TICKERS
) -> list[str]:
    out = list(dict.fromkeys(tickers))
    for ticker in reference_tickers:
        if ticker not in out:
            out.append(ticker)
    return out


def _resolve_fetch_start(low_start: str, end_date: str, needs_pattern_history: bool) -> str:
    if not needs_pattern_history:
        return low_start

    screen_start = pd.to_datetime(low_start)
    pattern_start = pd.to_datetime(end_date) - pd.offsets.BDay(PATTERN_LOOKBACK_DAYS - 1)
    fetch_start = screen_start if screen_start <= pattern_start else pattern_start
    return fetch_start.date().isoformat()


def _compute_summary(raw_df: pd.DataFrame, low_start: str, low_end: str) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        return pd.DataFrame(
            columns=[
                "Ticker",
                "low_date",
                "low_price",
                "current_price",
                "bounce_pct",
                "avg_vol_50d",
                "sector",
                "industry",
            ]
        )

    working = raw_df.copy()
    working["Date"] = pd.to_datetime(working["Date"])
    low_start_ts = pd.to_datetime(low_start)
    low_end_ts = pd.to_datetime(low_end)

    rows: list[dict[str, object]] = []
    for ticker, group in working.groupby("Ticker", sort=False):
        group = group.sort_values("Date")
        window = group[(group["Date"] >= low_start_ts) & (group["Date"] <= low_end_ts)]
        low_series = (
            pd.to_numeric(window["Low"], errors="coerce") if "Low" in window.columns else pd.Series(dtype=float)
        )
        if window.empty or low_series.dropna().empty:
            low_price = float("nan")
            low_date = None
        else:
            low_idx = low_series.idxmin()
            low_price = float(low_series.loc[low_idx])
            low_date = pd.to_datetime(window.loc[low_idx, "Date"]).date().isoformat()

        current_price = float(group["Close"].astype(float).iloc[-1])
        bounce_pct = compute_bounce(window, current_close=current_price)
        avg_vol_50d = float(group["Volume"].astype(float).tail(50).mean())
        rows.append(
            {
                "Ticker": ticker,
                "low_date": low_date,
                "low_price": low_price,
                "current_price": current_price,
                "bounce_pct": bounce_pct,
                "avg_vol_50d": avg_vol_50d,
                "sector": "",
                "industry": "",
            }
        )
    return pd.DataFrame(rows)


def _compute_benchmark_bounces(
    raw_df: pd.DataFrame, low_start: str, low_end: str, reference_tickers: tuple[str, ...] = REFERENCE_TICKERS
) -> dict[str, float]:
    if raw_df is None or raw_df.empty:
        return {ticker: float("nan") for ticker in reference_tickers}

    working = raw_df.copy()
    working["Date"] = pd.to_datetime(working["Date"])
    low_start_ts = pd.to_datetime(low_start)
    low_end_ts = pd.to_datetime(low_end)

    out: dict[str, float] = {}
    for ticker in reference_tickers:
        group = working.loc[working["Ticker"] == ticker].sort_values("Date")
        if group.empty:
            out[ticker] = float("nan")
            continue
        window = group[(group["Date"] >= low_start_ts) & (group["Date"] <= low_end_ts)]
        current_price = pd.to_numeric(group["Close"], errors="coerce").iloc[-1]
        out[ticker] = float(compute_bounce(window, current_close=current_price))
    return out


def _apply_benchmark_filter(
    df: pd.DataFrame,
    benchmark_bounces: dict[str, float],
    reference_tickers: tuple[str, ...] = REFERENCE_TICKERS,
    mode: str = "all",
) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.loc[~df["Ticker"].isin(reference_tickers)].copy()
    values = pd.Series(list(benchmark_bounces.values()), dtype=float).dropna()
    if values.empty:
        return out

    norm_mode = str(mode).lower()
    if norm_mode == "all":
        threshold = float(values.max())
    elif norm_mode == "any":
        threshold = float(values.min())
    elif norm_mode in {"qld", "tqqq"}:
        threshold = float(benchmark_bounces.get(norm_mode.upper(), float("nan")))
        if pd.isna(threshold):
            return out
    else:
        raise ValueError(f"Unknown benchmark mode: {mode}")

    return out.loc[pd.to_numeric(out["bounce_pct"], errors="coerce") > threshold].reset_index(drop=True)


def _attach_metadata(summary_df: pd.DataFrame, metadata_by_ticker: dict[str, dict[str, str]]) -> pd.DataFrame:
    if summary_df is None or summary_df.empty:
        return summary_df.copy() if summary_df is not None else pd.DataFrame()
    if not metadata_by_ticker:
        out = summary_df.copy()
        out["sector"] = DEFAULT_SECTION
        out["industry"] = DEFAULT_INDUSTRY
        return out

    out = summary_df.copy()
    ticker_keys = out["Ticker"].astype(str).str.upper()
    out["sector"] = ticker_keys.map(
        lambda ticker: metadata_by_ticker.get(ticker, {}).get("sector", DEFAULT_SECTION)
    ).fillna(DEFAULT_SECTION)
    out["industry"] = ticker_keys.map(
        lambda ticker: metadata_by_ticker.get(ticker, {}).get("industry", DEFAULT_INDUSTRY)
    ).fillna(DEFAULT_INDUSTRY)
    out["fifty_two_week_high"] = ticker_keys.map(
        lambda ticker: metadata_by_ticker.get(ticker, {}).get("fifty_two_week_high")
    )
    return out
