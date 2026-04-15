#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from decision_tickets import (
    DEFAULT_MAX_LOSS_PCT,
    MAX_TICKETS,
    DecisionCandidate,
    build_decision_tickets,
    ticket_to_dict,
)
from display import show_decision_tickets
from fetcher import (
    CacheMissError,
    UniverseCacheMissError,
    fetch_data,
    fetch_data_cached_only,
    get_sp500_tickers,
    get_sp500_tickers_cached_only,
)
from filters import apply_52wk_high_filter, apply_dollar_vol_filter, apply_price_filter
from pipeline import ScreeningArtifacts, build_screening_artifacts
from screener import (
    DEFAULT_EXCLUDED_SECTIONS,
    _apply_section_filter,
    _parse_excluded_sections,
    _slice_for_patterns,
    _sort_results,
)

RECENT_PATTERN_MAX_AGE_BDAYS = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Decision Ticket CLI")
    parser.add_argument("--low-start", default="2026-03-30")
    parser.add_argument("--low-end", default="2026-04-12")
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-dollar-vol", type=float, default=50_000_000)
    parser.add_argument("--min-pct-of-52wk-high", type=float, default=0.70)
    parser.add_argument("--universe", choices=["all", "sp500"], default="sp500")
    parser.add_argument("--benchmark-mode", choices=["all", "any", "qld", "tqqq"], default="any")
    parser.add_argument("--exclude-sections", default=DEFAULT_EXCLUDED_SECTIONS)
    parser.add_argument("--account-size", type=float, required=True)
    parser.add_argument("--risk-pct", type=float, required=True)
    parser.add_argument("--max-loss-pct", type=float, default=DEFAULT_MAX_LOSS_PCT)
    parser.add_argument("--max-position-dollars", type=float, default=None)
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser


def build_candidates(artifacts: ScreeningArtifacts, args: argparse.Namespace) -> list[DecisionCandidate]:
    filtered = _filter_screened_summary(artifacts.summary, args)
    if filtered.empty:
        return []

    from patterns import detect_all
    from strategies import strategy as compute_strategy

    candidates: list[DecisionCandidate] = []
    for ticker in filtered["Ticker"].tolist():
        df = _slice_for_patterns(ticker, artifacts.raw_df)
        if df is None:
            continue
        pattern_results = detect_all(df, ticker)
        if not pattern_results:
            continue
        row = filtered.loc[filtered["Ticker"] == ticker].iloc[0]
        for pattern_result in pattern_results:
            if not pattern_result.pivots:
                continue
            if not _is_recent_pattern_result(pattern_result, latest_date=df.index[-1].date()):
                continue
            try:
                setup = compute_strategy(pattern_result)
            except ValueError:
                continue
            candidates.append(
                DecisionCandidate(
                    ticker=ticker,
                    pattern=pattern_result.pattern,
                    screen_strength=_screen_strength(
                        row=row,
                        filtered=filtered,
                        benchmark_bounces=artifacts.benchmark_bounces,
                        benchmark_mode=args.benchmark_mode,
                    ),
                    pattern_confidence=pattern_result.confidence,
                    entry=setup.entry,
                    stop=setup.stop,
                    target=setup.target,
                    current_price=float(row["current_price"]),
                    dollar_volume=float(row["dollar_vol"]),
                    summary_reason=_summary_reason(
                        pattern=pattern_result.pattern,
                        confidence=pattern_result.confidence,
                        risk_reward=setup.risk_reward,
                        bounce_pct=float(row["bounce_pct"]),
                    ),
                    invalidation_rule=setup.invalidation_rule,
                )
            )
    return candidates


def run(args: argparse.Namespace):
    try:
        artifacts = _build_artifacts(
            args,
            fetch_data_fn=fetch_data_cached_only,
            select_universe_fn=_select_universe_for_timed_cli,
        )
    except (CacheMissError, UniverseCacheMissError):
        if args.universe != "sp500":
            raise
        artifacts = _build_artifacts(
            args,
            fetch_data_fn=fetch_data,
            select_universe_fn=_select_universe_for_default_cli,
        )
    candidates = build_candidates(artifacts, args)
    all_valid_tickets = build_decision_tickets(
        candidates,
        account_size=args.account_size,
        risk_pct=args.risk_pct,
        max_loss_pct=args.max_loss_pct,
        max_position_dollars=args.max_position_dollars,
        top_n=max(len(candidates), MAX_TICKETS),
    )
    tickets = all_valid_tickets[:MAX_TICKETS]
    if args.format == "json":
        print(json.dumps([ticket_to_dict(ticket) for ticket in tickets]))
    else:
        show_decision_tickets(tickets, plain=args.plain)
    _save_ticket_charts(all_valid_tickets if args.debug else tickets, artifacts.raw_df)
    return tickets


def _build_artifacts(
    args: argparse.Namespace,
    *,
    fetch_data_fn,
    select_universe_fn,
) -> ScreeningArtifacts:
    return build_screening_artifacts(
        universe=args.universe,
        low_start=args.low_start,
        low_end=args.low_end,
        refresh=False,
        benchmark_mode=args.benchmark_mode,
        needs_pattern_history=True,
        cache_dir="cache",
        db_path="market_surge.db",
        fetch_data_fn=fetch_data_fn,
        select_universe_fn=select_universe_fn,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run(args)
    except (CacheMissError, UniverseCacheMissError) as exc:
        print(f"CACHE_MISS {exc}", file=sys.stderr)
        return 2
    return 0


def _filter_screened_summary(summary: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    screened = _apply_section_filter(summary, excluded_sections=_parse_excluded_sections(args.exclude_sections))
    screened = apply_price_filter(screened, min_price=args.min_price)
    screened = apply_52wk_high_filter(screened, min_pct_of_52wk_high=args.min_pct_of_52wk_high)
    dollar_vol = apply_dollar_vol_filter(screened, min_dollar_vol=args.min_dollar_vol)
    if dollar_vol.empty:
        return dollar_vol
    filtered = screened.merge(dollar_vol[["Ticker", "dollar_vol"]], on="Ticker", how="inner")
    return _sort_results(filtered, sort_key="bounce")


def _screen_strength(
    *,
    row: pd.Series,
    filtered: pd.DataFrame,
    benchmark_bounces: dict[str, float],
    benchmark_mode: str,
) -> float:
    bounce_score = _normalized_rank(filtered["bounce_pct"], float(row["bounce_pct"]))
    liquidity_score = _normalized_rank(filtered["dollar_vol"], float(row["dollar_vol"]))
    benchmark_score = _benchmark_score(filtered, float(row["bounce_pct"]), benchmark_bounces, benchmark_mode)
    return 0.5 * bounce_score + 0.3 * benchmark_score + 0.2 * liquidity_score


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


def _summary_reason(pattern: str, confidence: float, risk_reward: float, bounce_pct: float) -> str:
    return f"{pattern} conf={confidence:.2f} rr={risk_reward:.1f} bounce={bounce_pct:.1f}%"


def _is_recent_pattern_result(
    pattern_result,
    *,
    latest_date: date,
    max_age_bdays: int = RECENT_PATTERN_MAX_AGE_BDAYS,
) -> bool:
    pivot_dates = [pivot_date for pivot_date in pattern_result.pivot_dates.values() if pivot_date is not None]
    reference_date = max(pivot_dates) if pivot_dates else pattern_result.detected_on
    if reference_date > latest_date:
        return True
    age_bdays = max(len(pd.bdate_range(reference_date, latest_date)) - 1, 0)
    return age_bdays <= max_age_bdays


def _save_ticket_charts(tickets, raw_df: pd.DataFrame) -> list[Path]:
    if not tickets:
        return []

    from charts import chart as render_chart
    from patterns import detect_all
    from strategies import strategy as compute_strategy

    output_dir = Path("charts")
    output_dir.mkdir(parents=True, exist_ok=True)
    rank_width = max(2, len(str(len(tickets))))
    saved_paths: list[Path] = []

    for ticket in tickets:
        df = _slice_for_patterns(ticket.ticker, raw_df)
        if df is None:
            continue

        selected_pattern = next(
            (
                result
                for result in detect_all(df, ticket.ticker)
                if result.pattern == ticket.pattern and result.pivots
            ),
            None,
        )
        if selected_pattern is None:
            continue

        fig = render_chart(
            ticket.ticker,
            df,
            [selected_pattern],
            setup=compute_strategy(selected_pattern),
            ticket=ticket,
            show=False,
        )
        output_path = output_dir / f"{ticket.rank:0{rank_width}d}_{ticket.ticker}_{ticket.pattern}.html"
        fig.write_html(str(output_path))
        saved_paths.append(output_path)
    return saved_paths


def _select_universe_for_timed_cli(universe: str) -> list[str]:
    if universe == "sp500":
        return get_sp500_tickers_cached_only("cache/sp500_tickers.txt")
    from fetcher import get_tickers

    return get_tickers()


def _select_universe_for_default_cli(universe: str) -> list[str]:
    if universe == "sp500":
        return get_sp500_tickers(cache_path="cache/sp500_tickers.txt")
    from fetcher import get_tickers

    return get_tickers()


if __name__ == "__main__":
    raise SystemExit(main())
