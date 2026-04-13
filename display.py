from __future__ import annotations

import sys

import pandas as pd
from rich.console import Console
from rich.table import Table


def _render_plain(df: pd.DataFrame, top: int) -> None:
    clipped = df.head(top)
    for _, row in clipped.iterrows():
        print(
            f"{row.get('Ticker', '')} "
            f"{row.get('low_date', '')} "
            f"{row.get('low_price', '')} "
            f"{row.get('current_price', '')} "
            f"{row.get('bounce_pct', '')} "
            f"{row.get('dollar_vol', '')} "
            f"{row.get('sector', '')} "
            f"{row.get('industry', '')}"
        )


def _render_benchmark_reference(benchmark_bounces: dict[str, float] | None) -> None:
    if not benchmark_bounces:
        return
    parts = []
    for ticker, value in benchmark_bounces.items():
        if pd.isna(value):
            parts.append(f"{ticker}=N/A")
        else:
            parts.append(f"{ticker}={float(value):.2f}%")
    print(f"Reference bounce: {' | '.join(parts)}")


def show_results(
    df: pd.DataFrame, top: int = 20, plain: bool = False, benchmark_bounces: dict[str, float] | None = None
) -> None:
    if df is None or df.empty:
        show_empty()
        return

    is_tty = getattr(sys.stdout, "isatty", lambda: False)()
    if plain or not is_tty:
        _render_benchmark_reference(benchmark_bounces)
        _render_plain(df, top=top)
        return

    table = Table(title="Stock Bounce Screener")
    table.add_column("Ticker", justify="left")
    table.add_column("Low Date", justify="left")
    table.add_column("Low $", justify="right")
    table.add_column("Current $", justify="right")
    table.add_column("Bounce %", justify="right")
    table.add_column("Vol*Price", justify="right")
    table.add_column("Sector", justify="left")
    table.add_column("Industry", justify="left")

    for _, row in df.head(top).iterrows():
        table.add_row(
            str(row.get("Ticker", "")),
            str(row.get("low_date", "")),
            f"{float(row.get('low_price', 0.0)):.2f}",
            f"{float(row.get('current_price', 0.0)):.2f}",
            f"{float(row.get('bounce_pct', 0.0)):.2f}",
            f"{float(row.get('dollar_vol', 0.0)):.0f}",
            str(row.get("sector", "")),
            str(row.get("industry", "")),
        )

    console = Console()
    if benchmark_bounces:
        parts = []
        for ticker, value in benchmark_bounces.items():
            if pd.isna(value):
                parts.append(f"{ticker}=N/A")
            else:
                parts.append(f"{ticker}={float(value):.2f}%")
        console.print(f"Reference bounce: {' | '.join(parts)}")
    console.print(table)


def show_empty() -> None:
    print("No results matching filters")
