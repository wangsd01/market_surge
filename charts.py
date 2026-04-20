from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from patterns.base import PatternResult

if TYPE_CHECKING:
    from decision_tickets import DecisionTicket
    from strategies import TradeSetup

logger = logging.getLogger(__name__)

DEBUG_PATTERN_ORDER = ("cup_handle", "double_bottom", "flat_base", "vcp", "high2")
DEBUG_PATTERN_COLORS = {
    "cup_handle": "#1f77b4",
    "double_bottom": "#d62728",
    "flat_base": "#2ca02c",
    "vcp": "#ff7f0e",
    "high2": "#9467bd",
}
_PATTERN_CONNECTIONS = {
    "cup_handle": ("left_high", "cup_low", "right_high", "handle_low", "handle_high", "breakout"),
    "double_bottom": ("left_high", "first_trough", "middle_high", "second_trough", "breakout"),
    "flat_base": ("base_high", "base_low"),
    "high2": ("prior_swing_high", "pullback_low", "h1_high", "h2_low", "h2_high"),
}


def chart(
    ticker: str,
    df: pd.DataFrame,
    patterns: list[PatternResult],
    setup: "TradeSetup | None" = None,
    ticket: "DecisionTicket | None" = None,
    show: bool = True,
    debug_patterns: bool = False,
    pattern_statuses: list[tuple[str, str]] | None = None,
) -> go.Figure:
    """Render candlestick chart with pattern overlays and optional strategy levels.

    Layout: 2 rows (70% / 30%).
      Top: candlestick + pattern pivot annotations + S/R dashed horizontals + strategy levels.
      Bottom: volume bars (green/red based on price direction).

    show=False returns figure without opening browser (use in tests).
    """
    closes = df["Close"].values
    opens = df["Open"].values
    dates = df.index

    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        shared_xaxes=True,
        vertical_spacing=0.03,
    )

    # --- Top row: candlestick ---
    fig.add_trace(
        go.Candlestick(
            x=dates,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name=ticker,
            showlegend=False,
        ),
        row=1, col=1,
    )

    # --- Bottom row: volume bars ---
    colors = [
        "green" if closes[i] >= opens[i] else "red"
        for i in range(len(closes))
    ]
    fig.add_trace(
        go.Bar(
            x=dates,
            y=df["Volume"],
            marker_color=colors,
            name="Volume",
            showlegend=False,
        ),
        row=2, col=1,
    )

    # --- Pattern overlays ---
    annotations = []
    shapes = []

    ordered_patterns = _ordered_patterns(patterns) if debug_patterns else patterns

    for pr in ordered_patterns:
        if pr.pattern == "support_resistance":
            # Render each S/R level as a dashed horizontal line
            for key, price in pr.pivots.items():
                rank = key.split("_")[-1]
                level_type = pr.metadata.get(f"type_{rank}", "support")
                color = "blue" if level_type == "resistance" else "orange"
                shapes.append(dict(
                    type="line",
                    x0=dates[0], x1=dates[-1],
                    y0=price, y1=price,
                    line=dict(color=color, width=1, dash="dash"),
                    xref="x", yref="y",
                ))
                annotations.append(dict(
                    x=dates[-1],
                    y=price,
                    text=f"{key} ({level_type})",
                    showarrow=False,
                    xanchor="right",
                    font=dict(size=9, color=color),
                    xref="x", yref="y",
                ))
        else:
            if debug_patterns:
                debug_trace = _build_debug_pattern_trace(pr)
                if debug_trace is not None:
                    fig.add_trace(debug_trace, row=1, col=1)

            for pivot_name, price in pr.pivots.items():
                pivot_date = pr.pivot_dates.get(pivot_name)
                if pivot_date is None:
                    continue
                label = f"{pr.pattern}:{pivot_name}" if debug_patterns else pivot_name
                color = DEBUG_PATTERN_COLORS.get(pr.pattern, "black") if debug_patterns else "black"
                annotations.append(dict(
                    x=pivot_date,
                    y=price,
                    text=label,
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1,
                    ax=0,
                    ay=-30,
                    font=dict(size=9, color=color),
                    xref="x", yref="y",
                ))

    # --- Strategy levels ---
    if setup is not None:
        for level_name, price, color in [
            ("entry", setup.entry, "green"),
            ("stop", setup.stop, "red"),
            ("target", setup.target, "blue"),
        ]:
            shapes.append(dict(
                type="line",
                x0=dates[0], x1=dates[-1],
                y0=price, y1=price,
                line=dict(color=color, width=1, dash="dot"),
                xref="x", yref="y",
            ))
            annotations.append(dict(
                x=dates[0],
                y=price,
                text=_strategy_level_text(level_name, price, setup),
                showarrow=False,
                xanchor="left",
                font=dict(size=9, color=color),
                xref="x", yref="y",
            ))

    if ticket is not None:
        annotations.append(
            dict(
                x=0.99,
                y=0.99,
                xref="paper",
                yref="paper",
                text=(
                    f"shares: {ticket.shares}<br>"
                    f"position value: {ticket.position_value:.2f}<br>"
                    f"risk value: {ticket.risk_value:.2f}"
                ),
                showarrow=False,
                xanchor="right",
                yanchor="top",
                align="left",
                font=dict(size=10, color="black"),
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="rgba(0,0,0,0.2)",
                borderpad=6,
            )
        )

    if debug_patterns and pattern_statuses:
        annotations.append(
            dict(
                x=0.01,
                y=0.99,
                xref="paper",
                yref="paper",
                text="<br>".join(f"{pattern}: {status}" for pattern, status in pattern_statuses),
                showarrow=False,
                xanchor="left",
                yanchor="top",
                align="left",
                font=dict(size=10, color="black"),
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="rgba(0,0,0,0.2)",
                borderpad=6,
            )
        )

    fig.update_layout(
        title=dict(text=ticker),
        shapes=shapes,
        annotations=annotations,
        xaxis_rangeslider_visible=False,
        margin=dict(l=60, r=60, t=50, b=30),
    )

    if show:
        fig.show()

    return fig


def _ordered_patterns(patterns: list[PatternResult]) -> list[PatternResult]:
    order = {pattern: idx for idx, pattern in enumerate(DEBUG_PATTERN_ORDER)}
    return sorted(patterns, key=lambda result: (order.get(result.pattern, len(order)), result.pattern))


def _build_debug_pattern_trace(pattern: PatternResult) -> go.Scatter | None:
    points = _debug_pattern_points(pattern)
    if len(points) < 2:
        return None

    color = DEBUG_PATTERN_COLORS.get(pattern.pattern, "#444444")
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="lines+markers",
        line=dict(color=color, width=2),
        marker=dict(color=color, size=7),
        opacity=0.7,
        name=f"{pattern.pattern} pattern",
        showlegend=False,
    )


def _debug_pattern_points(pattern: PatternResult) -> list[tuple[object, float]]:
    if pattern.pattern == "vcp":
        dated_keys = [
            key
            for key in pattern.pivots
            if key in pattern.pivot_dates and pattern.pivot_dates.get(key) is not None
        ]
        dated_keys.sort(key=lambda key: (pattern.pivot_dates[key], key))
        return [(pattern.pivot_dates[key], pattern.pivots[key]) for key in dated_keys]

    keys = _PATTERN_CONNECTIONS.get(pattern.pattern, ())
    points = []
    for key in keys:
        pivot_date = pattern.pivot_dates.get(key)
        if pivot_date is None or key not in pattern.pivots:
            continue
        points.append((pivot_date, pattern.pivots[key]))
    return points


def save_ticket_charts(tickets: list, raw_df: "pd.DataFrame", run_dir: "Path") -> list["Path"]:
    from pathlib import Path

    import pandas as pd

    from patterns import detect_all
    from screener import _slice_for_patterns
    from strategies import strategy as compute_strategy

    if not tickets:
        return []
    output_dir = Path(run_dir) / "charts"
    output_dir.mkdir(parents=True, exist_ok=True)
    rank_width = max(2, len(str(len(tickets))))
    saved_paths: list[Path] = []
    for ticket in tickets:
        df = _slice_for_patterns(ticket.ticker, raw_df)
        if df is None:
            continue
        selected_pattern = next(
            (r for r in detect_all(df, ticket.ticker) if r.pattern == ticket.pattern and r.pivots),
            None,
        )
        if selected_pattern is None:
            continue
        fig = chart(
            ticket.ticker, df, [selected_pattern],
            setup=compute_strategy(selected_pattern), ticket=ticket, show=False,
        )
        output_path = output_dir / f"{ticket.rank:0{rank_width}d}_{ticket.ticker}_{ticket.pattern}.html"
        fig.write_html(str(output_path))
        saved_paths.append(output_path)
    return saved_paths


def save_detected_pattern_charts(
    filtered: "pd.DataFrame", raw_df: "pd.DataFrame", run_dir: "Path"
) -> list["Path"]:
    from pathlib import Path

    import pandas as pd

    from actionability import assess_actionability
    from patterns import detect_all
    from screener import _slice_for_patterns

    if filtered is None or filtered.empty:
        return []
    output_dir = Path(run_dir) / "detected_patterns"
    output_dir.mkdir(parents=True, exist_ok=True)
    allowed = {pattern: idx for idx, pattern in enumerate(DEBUG_PATTERN_ORDER)}
    saved_paths: list[Path] = []
    for ticker in filtered["Ticker"].astype(str).tolist():
        df = _slice_for_patterns(ticker, raw_df)
        if df is None:
            continue
        pattern_results = [r for r in detect_all(df, ticker) if r.pattern in allowed and r.pivots]
        if not pattern_results:
            continue
        pattern_results.sort(key=lambda r: (allowed[r.pattern], r.pattern))
        current_price = float(filtered.loc[filtered["Ticker"] == ticker].iloc[0]["current_price"])
        pattern_statuses = [
            (r.pattern, "actionable" if assess_actionability(r, current_price=current_price).is_actionable else "non_actionable")
            for r in pattern_results
        ]
        fig = chart(ticker, df, pattern_results, show=False, debug_patterns=True, pattern_statuses=pattern_statuses)
        output_path = output_dir / f"{ticker}.html"
        fig.write_html(str(output_path))
        saved_paths.append(output_path)
    return saved_paths


def _strategy_level_text(level_name: str, price: float, setup: "TradeSetup") -> str:
    if level_name == "stop":
        return f"stop: {price:.2f} (-{setup.risk_pct * 100.0:.2f}%)"
    if level_name == "target":
        gain_pct = ((setup.target - setup.entry) / setup.entry) * 100.0 if setup.entry > 0 else 0.0
        return f"target: {price:.2f} (+{gain_pct:.2f}%)"
    return f"{level_name}: {price:.2f}"
