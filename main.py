#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

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
from pipeline import ScreeningArtifacts, build_screening_artifacts
from screener import (
    DEFAULT_EXCLUDED_SECTIONS,
    _parse_excluded_sections,
    _slice_for_patterns,
    filter_summary,
    save_csv_ranking,
    screen_strength,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Decision Ticket CLI")
    parser.add_argument("--low-start", default="2026-03-30")
    parser.add_argument("--low-end", default="2026-04-22")
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
    parser.add_argument("--save-detected-pattern-charts", action="store_true")
    return parser


def build_candidates(artifacts: ScreeningArtifacts, args: argparse.Namespace) -> list[DecisionCandidate]:
    from actionability import assess_actionability
    from patterns import detect_all, is_recent_pattern_result
    from strategies import strategy as compute_strategy, summary_reason

    filtered = filter_summary(
        artifacts.summary,
        excluded_sections=_parse_excluded_sections(args.exclude_sections),
        min_price=args.min_price,
        min_pct_of_52wk_high=args.min_pct_of_52wk_high,
        min_dollar_vol=args.min_dollar_vol,
    )
    if filtered.empty:
        return []

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
            if not is_recent_pattern_result(pattern_result, latest_date=df.index[-1].date()):
                continue
            assessment = assess_actionability(pattern_result, current_price=float(row["current_price"]))
            if not assessment.is_actionable:
                continue
            try:
                setup = compute_strategy(pattern_result)
            except ValueError:
                continue
            candidates.append(
                DecisionCandidate(
                    ticker=ticker,
                    pattern=pattern_result.pattern,
                    screen_strength=screen_strength(
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
                    summary_reason=summary_reason(
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
    from charts import save_detected_pattern_charts, save_ticket_charts

    run_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        artifacts = _build_artifacts(
            args,
            fetch_data_fn=fetch_data_cached_only,
            select_universe_fn=_select_universe_for_timed_cli,
        )
    except (CacheMissError, UniverseCacheMissError) as exc:
        _print_cache_miss_download_status(exc)
        artifacts = _build_artifacts(
            args,
            fetch_data_fn=fetch_data,
            select_universe_fn=_select_universe_for_default_cli,
        )

    filtered = filter_summary(
        artifacts.summary,
        excluded_sections=_parse_excluded_sections(args.exclude_sections),
        min_price=args.min_price,
        min_pct_of_52wk_high=args.min_pct_of_52wk_high,
        min_dollar_vol=args.min_dollar_vol,
    )
    save_csv_ranking(filtered, artifacts.summary_all, artifacts.benchmark_bounces, run_dir / "screened_ranking.csv")

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
    save_ticket_charts(all_valid_tickets if args.debug else tickets, artifacts.raw_df, run_dir)
    if args.save_detected_pattern_charts:
        save_detected_pattern_charts(filtered, artifacts.raw_df, run_dir)
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


def _print_cache_miss_download_status(exc: CacheMissError | UniverseCacheMissError) -> None:
    print(f"CACHE_MISS {_cache_miss_description(exc)}", file=sys.stderr)
    print(f"DOWNLOADING {_download_description(exc)}", file=sys.stderr)


def _cache_miss_description(exc: CacheMissError | UniverseCacheMissError) -> str:
    if isinstance(exc, UniverseCacheMissError):
        return f"cached universe '{exc.universe}' at {exc.cache_path}"
    return (
        f"missing price history for {_format_tickers(exc.missing_tickers)} "
        f"in requested range {exc.low_start}..{exc.end_date}"
    )


def _download_description(exc: CacheMissError | UniverseCacheMissError) -> str:
    if isinstance(exc, UniverseCacheMissError):
        return f"{exc.universe} universe to {exc.cache_path} and market data as needed"
    return (
        f"price history for {_format_tickers(exc.missing_tickers)} "
        f"in requested range {exc.low_start}..{exc.end_date}"
    )


def _format_tickers(tickers: list[str]) -> str:
    if not tickers:
        return "<unknown>"
    if len(tickers) <= 5:
        return ", ".join(tickers)
    return f"{', '.join(tickers[:5])}, ... ({len(tickers)} total)"


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run(args)
    except (CacheMissError, UniverseCacheMissError) as exc:
        print(f"CACHE_MISS {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
