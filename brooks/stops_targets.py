from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from brooks.breakout import BreakoutEvent
from brooks.config import BrooksConfig
from brooks.h1h2 import H1H2State


@dataclass
class StopSet:
    signal_bar_stop: float | None
    pullback_swing_stop: float | None
    breakout_bar_stop: float | None
    gap_failure_stop: float | None
    tight_stop: float | None
    structural_stop: float | None


@dataclass
class TargetSet:
    nearest_resistance: float | None
    target_1: float
    target_2: float
    rr_target_1: float
    rr_target_2: float


def compute_stops(
    h1h2_state: H1H2State | None, breakout_event: BreakoutEvent | None, config: BrooksConfig
) -> StopSet:
    trigger = None
    if h1h2_state is not None:
        trigger = h1h2_state.h2 if h1h2_state.h2 is not None else h1h2_state.h1

    signal_bar_stop = None
    pullback_swing_stop = None
    if trigger is not None:
        signal_bar_stop = trigger.signal_bar_low * (1 - config.stop_buffer_pct)
        pullback_swing_stop = trigger.pullback_leg_low * (1 - config.stop_buffer_pct)

    breakout_bar_stop = None
    gap_failure_stop = None
    if breakout_event is not None:
        # breakout_level is the resistance price cleared, not a price the
        # breakout bar actually traded at -- using it here (instead of the
        # breakout bar's own Low) put the stop right next to the entry
        # (both are derived from breakout_level), producing a near-zero risk
        # and absurd reward/risk ratios for every breakout-only setup.
        breakout_bar_stop = breakout_event.low * (1 - config.stop_buffer_pct)
        if breakout_event.true_gap_up and breakout_event.prior_high is not None:
            gap_failure_stop = breakout_event.prior_high * (1 - config.stop_buffer_pct)

    tight_stop = signal_bar_stop if signal_bar_stop is not None else breakout_bar_stop
    structural_stop = pullback_swing_stop if pullback_swing_stop is not None else breakout_bar_stop

    return StopSet(
        signal_bar_stop=signal_bar_stop,
        pullback_swing_stop=pullback_swing_stop,
        breakout_bar_stop=breakout_bar_stop,
        gap_failure_stop=gap_failure_stop,
        tight_stop=tight_stop,
        structural_stop=structural_stop,
    )


def _nearest_resistance(df: pd.DataFrame, ticker: str, current_price: float) -> float | None:
    from patterns.support_resistance import SupportResistanceDetector

    result = SupportResistanceDetector().detect(df, ticker)
    resistances = [
        price
        for key, price in result.pivots.items()
        if result.metadata.get(f"type_{key.split('_')[1]}") == "resistance" and price > current_price
    ]
    return min(resistances) if resistances else None


def compute_targets(
    df: pd.DataFrame,
    ticker: str,
    current_price: float,
    structural_stop: float,
    entry: float,
    config: BrooksConfig,
) -> TargetSet:
    nearest_resistance = _nearest_resistance(df, ticker, current_price)
    target_1 = nearest_resistance if nearest_resistance is not None else entry
    risk = entry - structural_stop
    target_2 = entry + 2 * risk

    rr_target_1 = (target_1 - entry) / risk if risk > 0 else 0.0
    rr_target_2 = 2.0

    return TargetSet(
        nearest_resistance=nearest_resistance,
        target_1=target_1,
        target_2=target_2,
        rr_target_1=rr_target_1,
        rr_target_2=rr_target_2,
    )
