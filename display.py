from __future__ import annotations

import sys
from typing import Sequence

import pandas as pd
from rich.console import Console
from rich.table import Table

from decision_tickets import DecisionTicket


TICKET_COLUMNS = [
    "rank",
    "ticker",
    "pattern",
    "entry",
    "stop",
    "target",
    "risk_loss_pct",
    "target_gain_pct",
    "risk_per_share",
    "shares",
    "position_value",
    "risk_value",
    "score",
    "summary_reason",
]


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


def show_decision_tickets(tickets: Sequence[DecisionTicket], plain: bool = False) -> None:
    if not tickets:
        print("NO_VALID_SETUPS")
        return

    is_tty = getattr(sys.stdout, "isatty", lambda: False)()
    if plain or not is_tty:
        _render_ticket_plain(tickets)
        return

    table = Table(title="Decision Tickets")
    for column in TICKET_COLUMNS:
        justify = "left" if column in {"ticker", "pattern", "summary_reason"} else "right"
        table.add_column(column, justify=justify, min_width=len(column), no_wrap=True)

    for ticket in tickets:
        table.add_row(
            str(ticket.rank),
            ticket.ticker,
            ticket.pattern,
            f"{ticket.entry:.2f}",
            f"{ticket.stop:.2f}",
            f"{ticket.target:.2f}",
            f"{ticket.risk_loss_pct:.2f}",
            f"{ticket.target_gain_pct:.2f}",
            f"{ticket.risk_per_share:.2f}",
            str(ticket.shares),
            f"{ticket.position_value:.2f}",
            f"{ticket.risk_value:.2f}",
            f"{ticket.score:.4f}",
            ticket.summary_reason,
        )

    console = Console(width=200)
    console.print(" ".join(TICKET_COLUMNS))
    console.print(table)


def _render_ticket_plain(tickets: Sequence[DecisionTicket]) -> None:
    print(" ".join(TICKET_COLUMNS))
    for ticket in tickets:
        print(
            " ".join(
                [
                    str(ticket.rank),
                    ticket.ticker,
                    ticket.pattern,
                    f"{ticket.entry:.2f}",
                    f"{ticket.stop:.2f}",
                    f"{ticket.target:.2f}",
                    f"{ticket.risk_loss_pct:.2f}",
                    f"{ticket.target_gain_pct:.2f}",
                    f"{ticket.risk_per_share:.2f}",
                    str(ticket.shares),
                    f"{ticket.position_value:.2f}",
                    f"{ticket.risk_value:.2f}",
                    f"{ticket.score:.4f}",
                    ticket.summary_reason,
                ]
            )
        )
