from __future__ import annotations

import logging
from dataclasses import dataclass

from patterns.base import PatternResult

logger = logging.getLogger(__name__)

RISK_REWARD: dict[str, float] = {
    "cup_handle": 2.5,
    "vcp": 2.5,
    "double_bottom": 2.0,
    "flat_base": 2.0,
    "channel": 2.0,
    "support_resistance": 2.0,
}


@dataclass
class TradeSetup:
    pattern: str
    ticker: str
    entry: float
    stop: float        # pattern low
    target: float      # entry + (entry - stop) * risk_reward
    risk_per_share: float
    risk_reward: float
    risk_pct: float    # (entry - stop) / entry
    invalidation_rule: str


def strategy(result: PatternResult) -> TradeSetup:
    """Derive informational trade setup from PatternResult geometry."""
    breakout, stop = _levels(result)
    entry = _entry_price(result.pattern, breakout)
    rr = RISK_REWARD[result.pattern]
    risk_per_share = entry - stop
    target = entry + risk_per_share * rr
    risk_pct = risk_per_share / entry
    return TradeSetup(
        pattern=result.pattern,
        ticker=result.ticker,
        entry=entry,
        stop=stop,
        target=target,
        risk_per_share=risk_per_share,
        risk_reward=rr,
        risk_pct=risk_pct,
        invalidation_rule="invalid if price trades below stop",
    )


def _entry_price(pattern: str, breakout: float) -> float:
    """Apply pattern-specific breakout buffers."""
    if pattern == "cup_handle":
        return breakout + 0.10
    if pattern == "double_bottom":
        return breakout + 0.10
    if pattern == "flat_base":
        return breakout + 0.10
    return breakout * 1.0005


def _levels(result: PatternResult) -> tuple[float, float]:
    """Return (breakout_price, stop_price) for the given pattern."""
    p = result.pattern
    pivots = result.pivots

    if p == "cup_handle":
        return pivots["handle_high"], pivots["handle_low"]

    if p == "double_bottom":
        return pivots["middle_high"], pivots["second_trough"]

    if p == "flat_base":
        return pivots["base_high"], pivots["base_low"]

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
        if not resistances or not supports:
            raise ValueError("support/resistance setup requires resistance above and support below price")
        # Nearest resistance above (smallest resistance), nearest support below (largest support)
        breakout = min(resistances)
        stop = max(supports)
        if breakout <= stop:
            raise ValueError("support/resistance setup requires breakout above stop")
        return breakout, stop

    raise ValueError(f"Unknown pattern: {p}")
