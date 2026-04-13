from __future__ import annotations

import logging
from dataclasses import dataclass

from patterns.base import PatternResult

logger = logging.getLogger(__name__)

RISK_REWARD: dict[str, float] = {
    "cup_handle": 2.5,
    "vcp": 2.5,
    "double_bottom": 2.0,
    "channel": 2.0,
    "support_resistance": 2.0,
}


@dataclass
class TradeSetup:
    pattern: str
    ticker: str
    entry: float       # breakout level * 1.0005 (0.05% above pivot high)
    stop: float        # pattern low
    target: float      # entry + (entry - stop) * risk_reward
    risk_reward: float
    risk_pct: float    # (entry - stop) / entry


def strategy(result: PatternResult) -> TradeSetup:
    """Derive informational trade setup from PatternResult geometry."""
    breakout, stop = _levels(result)
    entry = breakout * 1.0005
    rr = RISK_REWARD[result.pattern]
    target = entry + (entry - stop) * rr
    risk_pct = (entry - stop) / entry
    return TradeSetup(
        pattern=result.pattern,
        ticker=result.ticker,
        entry=entry,
        stop=stop,
        target=target,
        risk_reward=rr,
        risk_pct=risk_pct,
    )


def _levels(result: PatternResult) -> tuple[float, float]:
    """Return (breakout_price, stop_price) for the given pattern."""
    p = result.pattern
    pivots = result.pivots

    if p == "cup_handle":
        return pivots["handle_high"], pivots["handle_low"]

    if p == "double_bottom":
        return pivots["middle_high"], pivots["second_trough"]

    if p == "vcp":
        # Last high_N pivot (highest N present)
        high_keys = sorted(
            [k for k in pivots if k.startswith("high_")],
            key=lambda k: int(k.split("_")[1]),
        )
        low_keys = sorted(
            [k for k in pivots if k.startswith("low_")],
            key=lambda k: int(k.split("_")[1]),
        )
        breakout = pivots[high_keys[-1]]
        stop = pivots[low_keys[-1]]
        return breakout, stop

    if p == "channel":
        return pivots["channel_top"], pivots["channel_bottom"]

    if p == "support_resistance":
        metadata = result.metadata
        resistances = []
        supports = []
        for key, price in pivots.items():
            rank = key.split("_")[-1]
            level_type = metadata.get(f"type_{rank}", "support")
            if level_type == "resistance":
                resistances.append(price)
            else:
                supports.append(price)
        # Nearest resistance above (smallest resistance), nearest support below (largest support)
        breakout = min(resistances) if resistances else max(pivots.values())
        stop = max(supports) if supports else min(pivots.values())
        return breakout, stop

    raise ValueError(f"Unknown pattern: {p}")
