#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from brooks.breakout import find_latest_breakout, follow_through
from brooks.config import BrooksConfig, tick_buffer
from brooks.extension import is_extended
from brooks.features import compute_features
from brooks.h1h2 import compute_h1h2_state
from brooks.market_cycle import classify_market_cycle
from brooks.output import ALL_OUTPUT_COLUMNS, assemble_row, build_watchlist_buckets
from brooks.scoring import compute_scores
from brooks.state import resolve_state
from brooks.stops_targets import TargetSet, compute_stops, compute_targets
from charts import chart
from strategies import TradeSetup

CHART_LOOKBACK_BARS = 120

DEFAULT_TICKERS_CSV = "ranking_all.csv"
DEFAULT_TOP = 20


def _resolve_entry(h1h2_state, breakout_event, current_price: float, config: BrooksConfig) -> float:
    if h1h2_state is not None and h1h2_state.h2 is not None:
        return h1h2_state.h2.trigger_price
    if h1h2_state is not None and h1h2_state.h1 is not None:
        return h1h2_state.h1.trigger_price
    if breakout_event is not None:
        # Al Brooks' "Buy The Close": for a strong continuation with no
        # pullback yet, entry is at (or just above) the latest strong bar's
        # close, not a stop-buy above the resistance level that was cleared
        # several bars ago at the original breakout -- that's a different
        # (and non-Brooks) mechanic that happened to be close in practice but
        # isn't the actual named technique for this situation.
        return current_price + tick_buffer(current_price, config)
    return current_price


def run_ticker(df: pd.DataFrame, ticker: str, dollar_vol: float, config: BrooksConfig | None = None) -> dict:
    """Run the full Brooks pipeline for one ticker's OHLCV history.

    df: DatetimeIndex, columns [Open, High, Low, Close, Volume], at least
    config.min_bars_required rows (no NaN in the raw OHLCV columns).
    """
    config = config or BrooksConfig()
    feat = compute_features(df, config)
    latest_idx = len(feat) - 1
    current_price = float(feat["Close"].iloc[-1])

    market_cycle = classify_market_cycle(feat, config)
    breakout_event = find_latest_breakout(feat, config)
    follow_through_result = follow_through(feat, breakout_event, config) if breakout_event is not None else None
    h1h2_state = compute_h1h2_state(feat, breakout_event, config)
    extension = is_extended(feat, h1h2_state, breakout_event, config)

    proposed_entry = _resolve_entry(h1h2_state, breakout_event, current_price, config)
    stops = compute_stops(h1h2_state, breakout_event, config)
    if stops.structural_stop is not None:
        targets = compute_targets(
            feat, ticker=ticker, current_price=current_price, structural_stop=stops.structural_stop,
            entry=proposed_entry, config=config,
        )
    else:
        # No trigger and no breakout at all -- there is no real stop to measure
        # reward/risk against yet, so don't fabricate one.
        targets = TargetSet(nearest_resistance=None, target_1=None, target_2=None, rr_target_1=0.0, rr_target_2=None)

    scores = compute_scores(
        market_cycle=market_cycle, breakout_event=breakout_event, follow_through=follow_through_result,
        h1h2_state=h1h2_state, extension=extension, targets=targets, dollar_vol=dollar_vol, config=config,
    )
    setup_state = resolve_state(
        market_cycle=market_cycle, breakout_event=breakout_event, follow_through=follow_through_result,
        h1h2_state=h1h2_state, extension=extension, entry_quality_score=scores.entry_quality_score,
        latest_idx=latest_idx, config=config,
    )

    return assemble_row(
        ticker=ticker, date=feat.index[-1].date(), market_cycle=market_cycle, breakout_event=breakout_event,
        follow_through=follow_through_result, h1h2_state=h1h2_state, extension=extension, stops=stops,
        targets=targets, scores=scores, setup_state=setup_state, proposed_entry=proposed_entry,
        dollar_vol=dollar_vol, config=config,
    )


def _slice_for_ticker(ticker: str, raw_df: pd.DataFrame) -> pd.DataFrame | None:
    group = raw_df.loc[raw_df["Ticker"] == ticker].copy()
    if group.empty:
        return None
    group = group.sort_values("Date")
    group["Date"] = pd.to_datetime(group["Date"])
    group = group.set_index("Date")
    return group[["Open", "High", "Low", "Close", "Volume"]]


def save_ready_now_charts(ready_df: pd.DataFrame, raw_df: pd.DataFrame, output_dir: str | Path) -> list[Path]:
    """Render and save one candlestick chart per READY_NOW ticker, with the
    proposed entry/stop/target drawn as horizontal lines (reuses charts.chart
    and strategies.TradeSetup -- the same rendering used by the Decision
    Ticket pipeline, just fed from Brooks' own entry/stop/target fields).

    Prefers structural_stop over tight_stop, matching the rest of the
    pipeline's "prefer the structural stop" convention. Skips a ticker if
    its price history or any required entry/stop/target value is missing.
    """
    if ready_df is None or ready_df.empty:
        return []
    charts_dir = Path(output_dir) / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for _, row in ready_df.iterrows():
        ticker = str(row["ticker"])
        df = _slice_for_ticker(ticker, raw_df)
        if df is None:
            continue

        entry = row["proposed_entry"]
        stop = row["structural_stop"] if pd.notna(row.get("structural_stop")) else row.get("tight_stop")
        target = row["target_1"]
        if pd.isna(entry) or pd.isna(stop) or pd.isna(target):
            continue

        entry = float(entry)
        stop = float(stop)
        target = float(target)
        setup = TradeSetup(
            pattern=str(row["setup_state"]),
            ticker=ticker,
            entry=entry,
            stop=stop,
            target=target,
            risk_per_share=entry - stop,
            risk_reward=float(row["rr_target_1"]) if pd.notna(row.get("rr_target_1")) else 0.0,
            risk_pct=float(row["risk_pct"]) if pd.notna(row.get("risk_pct")) else (entry - stop) / entry,
            invalidation_rule=f"Invalid if price closes below {stop:.2f}",
        )

        fig = chart(ticker, df.tail(CHART_LOOKBACK_BARS), [], setup=setup, show=False)
        output_path = charts_dir / f"{ticker}.html"
        fig.write_html(str(output_path))
        saved_paths.append(output_path)
    return saved_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Al Brooks post-earnings bullish screener")
    parser.add_argument("--tickers-csv", default=DEFAULT_TICKERS_CSV)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--refresh", action="store_true")
    return parser


def run(args: argparse.Namespace) -> pd.DataFrame:
    from fetcher import _today_market_date, fetch_data

    config = BrooksConfig()
    tickers_df = pd.read_csv(args.tickers_csv)
    tickers = tickers_df["Ticker"].dropna().astype(str).str.upper().unique().tolist()

    end_date = _today_market_date().isoformat()
    fetch_start = (pd.Timestamp(end_date) - pd.offsets.BDay(config.lookback_bdays - 1)).date().isoformat()
    raw_df = fetch_data(
        tickers=tickers, low_start=fetch_start, end_date=end_date,
        cache_dir=Path("cache"), refresh=args.refresh, db_path=Path("market_surge.db"),
    )

    rows: list[dict] = []
    for ticker in tickers:
        df = _slice_for_ticker(ticker, raw_df)
        if df is None or len(df) < config.min_bars_required:
            continue
        dollar_vol = float(df["Close"].iloc[-1] * df["Volume"].tail(50).mean())
        rows.append(run_ticker(df, ticker, dollar_vol, config))

    result = pd.DataFrame(rows, columns=ALL_OUTPUT_COLUMNS)
    if not result.empty:
        result = result.sort_values("trade_score", ascending=False).reset_index(drop=True)

    output_dir = Path(args.output_dir) if args.output_dir else Path("runs") / "brooks" / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "brooks_ranking.csv", index=False)

    if not result.empty:
        buckets = build_watchlist_buckets(result, config)
        for name, bucket_df in buckets.items():
            bucket_df.to_csv(output_dir / f"{name.lower()}.csv", index=False)
        saved_charts = save_ready_now_charts(buckets["READY_NOW"], raw_df, output_dir)
        if saved_charts:
            print(f"Saved {len(saved_charts)} READY_NOW charts to {output_dir / 'charts'}")

    print(result.head(args.top).to_string(index=False))
    return result


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
