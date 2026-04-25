from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from db import init_db, save_run
from display import show_results
from fetcher import (
    DEFAULT_INDUSTRY,
    DEFAULT_SECTION,
    _today_market_date,
    fetch_data,
    get_sp500_tickers,
    get_ticker_metadata,
    get_tickers,
)
from filters import apply_52wk_high_filter, apply_dollar_vol_filter, apply_price_filter, compute_bounce
from pipeline import build_screening_artifacts

REFERENCE_TICKERS = ("QLD", "TQQQ")
DEFAULT_EXCLUDED_SECTIONS = "biotechnology"
PATTERN_LOOKBACK_DAYS = 180


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stock bounce screener")
    parser.add_argument("--low-start", default="2026-03-30")
    parser.add_argument("--low-end", default="2026-04-12")
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-dollar-vol", type=float, default=50_000_000)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--universe", choices=["all", "sp500"], default="all")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    parser.add_argument("--output", default="ranking_all.csv")
    parser.add_argument("--sort", choices=["bounce", "dollar_vol", "price"], default="bounce")
    parser.add_argument("--benchmark-mode", choices=["all", "any", "qld", "tqqq"], default="any")
    parser.add_argument(
        "--exclude-sections",
        default=DEFAULT_EXCLUDED_SECTIONS,
        help="Comma-separated sections to exclude (case-insensitive). Use 'none' to disable.",
    )
    parser.add_argument(
        "--min-pct-of-52wk-high",
        type=float,
        default=0.70,
        help="Only keep stocks whose current price is at least this fraction of their 52-week high (default: 0.70).",
    )
    parser.add_argument(
        "--patterns",
        action="store_true",
        help="Detect chart patterns in screener output and print results.",
    )
    parser.add_argument(
        "--chart",
        metavar="TICKER",
        default=None,
        help="Render a plotly candlestick chart with pattern overlays for TICKER.",
    )
    parser.add_argument(
        "--strategy",
        metavar="TICKER",
        default=None,
        help="Print trade setup derived from detected patterns for TICKER.",
    )
    parser.add_argument(
        "--extra-tickers",
        default="SOXL",
        help="Comma-separated tickers to add to the universe (e.g. SOXL,UVXY).",
    )
    return parser


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

    rows: list[dict] = []
    for ticker, group in working.groupby("Ticker", sort=False):
        group = group.sort_values("Date")
        window = group[(group["Date"] >= low_start_ts) & (group["Date"] <= low_end_ts)]
        low_series = pd.to_numeric(window["Low"], errors="coerce") if "Low" in window.columns else pd.Series(dtype=float)
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


def _parse_excluded_sections(raw: str | None) -> set[str]:
    if raw is None:
        return set()
    parts = [part.strip().lower() for part in str(raw).split(",")]
    cleaned = {part for part in parts if part}
    if cleaned == {"none"}:
        return set()
    return cleaned


def _apply_section_filter(df: pd.DataFrame, excluded_sections: set[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if not excluded_sections:
        return df.copy()
    if "sector" not in df.columns and "industry" not in df.columns:
        return df.copy()

    sector_matches = (
        df["sector"].astype(str).str.strip().str.lower().isin(excluded_sections)
        if "sector" in df.columns
        else pd.Series(False, index=df.index)
    )
    industry_matches = (
        df["industry"].astype(str).str.strip().str.lower().isin(excluded_sections)
        if "industry" in df.columns
        else pd.Series(False, index=df.index)
    )
    return df.loc[~(sector_matches | industry_matches)].copy()


def _sort_results(df: pd.DataFrame, sort_key: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    sort_column = {
        "bounce": "bounce_pct",
        "dollar_vol": "dollar_vol",
        "price": "current_price",
    }[sort_key]
    return df.sort_values(sort_column, ascending=False, na_position="last").reset_index(drop=True)


def filter_summary(
    summary: pd.DataFrame,
    *,
    excluded_sections: set[str],
    min_price: float,
    min_pct_of_52wk_high: float,
    min_dollar_vol: float,
    sort_key: str = "bounce",
) -> pd.DataFrame:
    screened = _apply_section_filter(summary, excluded_sections=excluded_sections)
    screened = apply_price_filter(screened, min_price=min_price)
    screened = apply_52wk_high_filter(screened, min_pct_of_52wk_high=min_pct_of_52wk_high)
    dollar_vol_df = apply_dollar_vol_filter(screened, min_dollar_vol=min_dollar_vol)
    if dollar_vol_df.empty:
        return dollar_vol_df
    filtered = screened.merge(dollar_vol_df[["Ticker", "dollar_vol"]], on="Ticker", how="inner")
    return _sort_results(filtered, sort_key=sort_key)


def screen_strength(
    *,
    row: pd.Series,
    filtered: pd.DataFrame,
    benchmark_bounces: dict[str, float],
    benchmark_mode: str,
) -> float:
    bounce_score = _normalized_rank(filtered["bounce_pct"], float(row["bounce_pct"]))
    liquidity_score = _normalized_rank(filtered["dollar_vol"], float(row["dollar_vol"]))
    bscore = _benchmark_score(filtered, float(row["bounce_pct"]), benchmark_bounces, benchmark_mode)
    return 0.5 * bounce_score + 0.3 * bscore + 0.2 * liquidity_score


def _benchmark_score(
    filtered: pd.DataFrame,
    bounce_pct: float,
    benchmark_bounces: dict[str, float],
    benchmark_mode: str,
) -> float:
    threshold = _benchmark_threshold(benchmark_bounces, benchmark_mode)
    if threshold is None:
        return 1.0
    gaps = (pd.to_numeric(filtered["bounce_pct"], errors="coerce") - threshold).clip(lower=0.0)
    current_gap = max(0.0, bounce_pct - threshold)
    return _normalized_rank(gaps, current_gap)


def _benchmark_threshold(benchmark_bounces: dict[str, float], benchmark_mode: str) -> float | None:
    values = pd.Series(list(benchmark_bounces.values()), dtype=float).dropna()
    if values.empty:
        return None
    mode = benchmark_mode.lower()
    if mode == "all":
        return float(values.max())
    if mode == "any":
        return float(values.min())
    if mode in {"qld", "tqqq"}:
        value = benchmark_bounces.get(mode.upper())
        return None if value is None or pd.isna(value) else float(value)
    raise ValueError(f"Unknown benchmark mode: {benchmark_mode}")


def _normalized_rank(series: pd.Series, value: float) -> float:
    values = pd.to_numeric(series, errors="coerce")
    if values.empty:
        return 0.0
    if len(values) == 1:
        return 1.0
    augmented = pd.concat([values.reset_index(drop=True), pd.Series([value])], ignore_index=True)
    rank = augmented.rank(method="average", ascending=True).iloc[-1]
    return float((rank - 1) / (len(augmented) - 1))


def _needs_pattern_history(args: argparse.Namespace) -> bool:
    return bool(args.patterns or args.chart or args.strategy)


def _resolve_fetch_start(low_start: str, end_date: str, needs_pattern_history: bool) -> str:
    if not needs_pattern_history:
        return low_start

    screen_start = pd.to_datetime(low_start)
    pattern_start = pd.to_datetime(end_date) - pd.offsets.BDay(PATTERN_LOOKBACK_DAYS - 1)
    fetch_start = screen_start if screen_start <= pattern_start else pattern_start
    return fetch_start.date().isoformat()


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
        selected = benchmark_bounces.get(norm_mode.upper(), float("nan"))
        if pd.isna(selected):
            return out
        threshold = float(selected)
    else:
        raise ValueError(f"Unsupported benchmark mode: {mode}")

    return out.loc[pd.to_numeric(out["bounce_pct"], errors="coerce") > threshold].copy()


def _build_csv_ranking(
    filtered_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    benchmark_bounces: dict[str, float] | None = None,
    reference_tickers: tuple[str, ...] = REFERENCE_TICKERS,
) -> pd.DataFrame:
    filtered = filtered_df.copy() if filtered_df is not None else pd.DataFrame()
    summary = summary_df.copy() if summary_df is not None else pd.DataFrame()

    reference_rows = summary.loc[summary["Ticker"].isin(reference_tickers)].copy() if "Ticker" in summary.columns else pd.DataFrame()
    present_refs = set(reference_rows["Ticker"].tolist()) if not reference_rows.empty else set()

    missing_rows: list[dict] = []
    for ticker in reference_tickers:
        if ticker in present_refs:
            continue
        row = {"Ticker": ticker, "bounce_pct": float("nan")}
        if benchmark_bounces and ticker in benchmark_bounces:
            row["bounce_pct"] = benchmark_bounces[ticker]
        missing_rows.append(row)

    missing_df = pd.DataFrame(missing_rows)
    combined = pd.concat([filtered, reference_rows, missing_df], ignore_index=True, sort=False)
    if combined.empty:
        return combined

    combined = combined.drop_duplicates(subset=["Ticker"], keep="first")
    combined["bounce_pct"] = pd.to_numeric(combined["bounce_pct"], errors="coerce")
    if {"avg_vol_50d", "current_price"}.issubset(combined.columns):
        computed = pd.to_numeric(combined["avg_vol_50d"], errors="coerce") * pd.to_numeric(
            combined["current_price"], errors="coerce"
        )
        if "dollar_vol" in combined.columns:
            combined["dollar_vol"] = pd.to_numeric(combined["dollar_vol"], errors="coerce").fillna(computed)
        else:
            combined["dollar_vol"] = computed
    if "avg_vol_50d" in combined.columns:
        combined["avg_vol_50d"] = pd.to_numeric(combined["avg_vol_50d"], errors="coerce") / 1_000_000.0
    combined = combined.sort_values("bounce_pct", ascending=False, na_position="last").reset_index(drop=True)
    return combined


def _format_csv_ranking_for_output(ranked_df: pd.DataFrame) -> pd.DataFrame:
    out = ranked_df.copy()
    if "avg_vol_50d" in out.columns:
        out = out.drop(columns=["avg_vol_50d"])
    if "dollar_vol" in out.columns:
        out["dollar_vol_m"] = pd.to_numeric(out["dollar_vol"], errors="coerce") / 1_000_000.0
        out = out.drop(columns=["dollar_vol"])

    numeric_cols = out.select_dtypes(include=["number"]).columns
    if len(numeric_cols) > 0:
        out[numeric_cols] = out[numeric_cols].round(2)
    return out


def _slice_for_patterns(ticker: str, raw_df: pd.DataFrame) -> pd.DataFrame | None:
    """Return last pattern lookback bars of OHLCV data for ticker as a DatetimeIndex DataFrame.

    Returns None if ticker is not present in raw_df.
    """
    if raw_df is None or raw_df.empty:
        return None
    group = raw_df.loc[raw_df["Ticker"] == ticker].copy()
    if group.empty:
        return None
    group = group.sort_values("Date")
    group["Date"] = pd.to_datetime(group["Date"])
    group = group.set_index("Date").tail(PATTERN_LOOKBACK_DAYS)
    return group[["Open", "High", "Low", "Close", "Volume"]]


def _run_patterns(tickers: list[str], raw_df: pd.DataFrame) -> dict[str, list]:
    """Run pattern detection on each ticker's recent pattern lookback window.

    Returns dict mapping ticker -> list[PatternResult] (empty list on failure).
    """
    from patterns import detect_all

    results: dict[str, list] = {}
    for ticker in tickers:
        df = _slice_for_patterns(ticker, raw_df)
        if df is None:
            results[ticker] = []
        else:
            results[ticker] = detect_all(df, ticker)
    return results


def _handle_chart(ticker: str, raw_df: pd.DataFrame, show: bool = True):
    """Render a plotly chart for ticker with pattern overlays.

    Returns the Figure, or None if ticker not found in raw_df.
    """
    from charts import chart
    from patterns import detect_all
    from strategies import strategy as compute_strategy

    df = _slice_for_patterns(ticker, raw_df)
    if df is None:
        return None
    patterns = detect_all(df, ticker)
    setup = None
    for pattern in patterns:
        try:
            setup = compute_strategy(pattern)
            break
        except ValueError:
            continue
    return chart(ticker, df, patterns, setup=setup, show=show)


def _handle_strategy(ticker: str, raw_df: pd.DataFrame) -> list:
    """Return a list of TradeSetup objects for all detected patterns for ticker."""
    from patterns import detect_all
    from strategies import strategy as compute_strategy

    df = _slice_for_patterns(ticker, raw_df)
    if df is None:
        return []
    patterns = detect_all(df, ticker)
    setups = []
    for pattern in patterns:
        if not pattern.pivots:
            continue
        try:
            setups.append(compute_strategy(pattern))
        except ValueError:
            continue
    return setups


def save_csv_ranking(
    filtered: pd.DataFrame,
    summary_all: pd.DataFrame,
    benchmark_bounces: dict[str, float],
    path: Path,
) -> None:
    csv_output = _format_csv_ranking_for_output(
        _build_csv_ranking(filtered, summary_all, benchmark_bounces=benchmark_bounces)
    )
    if not csv_output.empty:
        csv_output.to_csv(path, index=False)


def run(args: argparse.Namespace) -> pd.DataFrame:
    # Single-ticker modes: dispatch and return early
    if args.chart:
        tickers = _with_reference_tickers(_select_universe(args.universe))
        end_date = _today_market_date().isoformat()
        fetch_start = _resolve_fetch_start(
            low_start=args.low_start,
            end_date=end_date,
            needs_pattern_history=_needs_pattern_history(args),
        )
        raw_df = fetch_data(
            tickers=tickers,
            low_start=fetch_start,
            end_date=end_date,
            cache_dir=Path("cache"),
            refresh=args.refresh,
            db_path=Path("market_surge.db"),
        )
        _handle_chart(args.chart, raw_df, show=True)
        return pd.DataFrame()

    if args.strategy:
        tickers = _with_reference_tickers(_select_universe(args.universe))
        end_date = _today_market_date().isoformat()
        fetch_start = _resolve_fetch_start(
            low_start=args.low_start,
            end_date=end_date,
            needs_pattern_history=_needs_pattern_history(args),
        )
        raw_df = fetch_data(
            tickers=tickers,
            low_start=fetch_start,
            end_date=end_date,
            cache_dir=Path("cache"),
            refresh=args.refresh,
            db_path=Path("market_surge.db"),
        )
        setups = _handle_strategy(args.strategy, raw_df)
        for setup in setups:
            print(
                f"{setup.pattern}: entry={setup.entry:.2f}  stop={setup.stop:.2f}"
                f"  target={setup.target:.2f}  rr={setup.risk_reward}  risk={setup.risk_pct:.1%}"
            )
        return pd.DataFrame()

    extra_tickers = [t.strip().upper() for t in getattr(args, "extra_tickers", "").split(",") if t.strip()]

    def _select_universe_fn(universe: str) -> list[str]:
        base = _select_universe(universe)
        return list(dict.fromkeys(base + extra_tickers))

    artifacts = build_screening_artifacts(
        universe=args.universe,
        low_start=args.low_start,
        low_end=args.low_end,
        refresh=args.refresh,
        benchmark_mode=args.benchmark_mode,
        needs_pattern_history=_needs_pattern_history(args),
        cache_dir=Path("cache"),
        db_path=Path("market_surge.db"),
        select_universe_fn=_select_universe_fn,
        today_market_date_fn=_today_market_date,
        fetch_data_fn=fetch_data,
        metadata_fn=get_ticker_metadata,
    )
    raw_df = artifacts.raw_df
    summary_all = artifacts.summary_all
    benchmark_bounces = artifacts.benchmark_bounces
    filtered = filter_summary(
        artifacts.summary,
        excluded_sections=_parse_excluded_sections(args.exclude_sections),
        min_price=args.min_price,
        min_pct_of_52wk_high=args.min_pct_of_52wk_high,
        min_dollar_vol=args.min_dollar_vol,
        sort_key=args.sort,
    )
    if args.output:
        save_csv_ranking(filtered, summary_all, benchmark_bounces, Path(args.output))

    top_n = 10 if args.schedule else args.top
    show_results(filtered, top=top_n, plain=args.schedule, benchmark_bounces=benchmark_bounces)

    if args.patterns and not filtered.empty:
        pattern_map = _run_patterns(filtered["Ticker"].tolist(), raw_df)
        for ticker, patterns in pattern_map.items():
            for pr in patterns:
                print(f"{ticker}  {pr.pattern}  conf={pr.confidence:.2f}")

    conn = init_db("market_surge.db")
    try:
        save_run(
            conn,
            {
                "run_at": datetime.now(UTC).replace(microsecond=0).isoformat(sep=" "),
                "low_start": args.low_start,
                "low_end": args.low_end,
                "min_price": args.min_price,
                "min_dollar_vol": args.min_dollar_vol,
            },
            filtered,
        )
    finally:
        conn.close()

    return filtered


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
