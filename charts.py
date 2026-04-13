from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from patterns.base import PatternResult

if TYPE_CHECKING:
    from strategies import TradeSetup

logger = logging.getLogger(__name__)


def chart(
    ticker: str,
    df: pd.DataFrame,
    patterns: list[PatternResult],
    setup: "TradeSetup | None" = None,
    show: bool = True,
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

    for pr in patterns:
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
            # Render pivot points as markers + annotations
            for pivot_name, price in pr.pivots.items():
                pivot_date = pr.pivot_dates.get(pivot_name)
                if pivot_date is None:
                    continue
                annotations.append(dict(
                    x=pivot_date,
                    y=price,
                    text=pivot_name,
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=1,
                    ax=0,
                    ay=-30,
                    font=dict(size=9),
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
                text=f"{level_name}: {price:.2f}",
                showarrow=False,
                xanchor="left",
                font=dict(size=9, color=color),
                xref="x", yref="y",
            ))

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
