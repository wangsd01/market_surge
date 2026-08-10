from __future__ import annotations

from brooks.breakout import BreakoutEvent, FollowThroughResult
from brooks.config import BrooksConfig
from brooks.extension import ExtensionResult
from brooks.h1h2 import H1H2State
from brooks.market_cycle import MarketCycleResult

_BULL_CYCLES = {"STRONG_BULL_TREND", "BULL_TREND"}


def resolve_state(
    *,
    market_cycle: MarketCycleResult,
    breakout_event: BreakoutEvent | None,
    follow_through: FollowThroughResult | None,
    h1h2_state: H1H2State | None,
    extension: ExtensionResult,
    entry_quality_score: float,
    latest_idx: int,
    config: BrooksConfig,
) -> str:
    if h1h2_state is not None and h1h2_state.h2_failed and not h1h2_state.reset_from_failure:
        return "FAILED_H2"

    if (
        h1h2_state is not None
        and h1h2_state.h1_failed
        and h1h2_state.h2 is None
        and not h1h2_state.reset_from_failure
    ):
        return "FAILED_H1"

    if (
        breakout_event is not None
        and follow_through is not None
        and follow_through.follow_through_score is not None
        and follow_through.follow_through_score < 0
        and follow_through.retracement_pct >= 1.0
    ):
        return "FAILED_H1"

    if extension.is_extended and h1h2_state is not None and h1h2_state.h2 is not None:
        return "EXTENDED_AFTER_H2"

    if extension.is_extended and (h1h2_state is None or h1h2_state.h2 is None):
        return "EXTENDED_AFTER_BREAKOUT"

    if h1h2_state is not None and h1h2_state.days_since_h2_trigger == 0:
        return "H2_TRIGGERED_TODAY"

    if (
        h1h2_state is not None
        and h1h2_state.h2 is not None
        and 0 < h1h2_state.days_since_h2_trigger < config.h2_stale_bdays
    ):
        return "H2_TRIGGERED_RECENTLY"

    if h1h2_state is not None and h1h2_state.forming == "h2":
        return "H2_FORMING"

    if h1h2_state is not None and h1h2_state.days_since_h1_trigger == 0 and h1h2_state.h2 is None:
        return "H1_TRIGGERED_TODAY"

    if (
        h1h2_state is not None
        and h1h2_state.h1 is not None
        and h1h2_state.h2 is None
        and 0 < h1h2_state.days_since_h1_trigger < config.h1_stale_bdays
    ):
        return "H1_TRIGGERED_RECENTLY"

    if (
        h1h2_state is not None
        and h1h2_state.forming == "h1"
        and breakout_event is not None
        and follow_through is not None
        and (latest_idx - breakout_event.idx) <= config.breakout_pullback_max_age_bdays
        and follow_through.retracement_pct <= config.moderate_retracement_max
    ):
        return "BREAKOUT_PULLBACK"

    if h1h2_state is not None and h1h2_state.forming == "h1":
        return "H1_FORMING"

    if breakout_event is not None and breakout_event.idx == latest_idx:
        return "STRONG_BREAKOUT"

    if (
        breakout_event is not None
        and follow_through is not None
        and (latest_idx - breakout_event.idx) <= config.follow_through_bars
        and follow_through.follow_through_score is not None
        and follow_through.follow_through_score > 0
    ):
        return "STRONG_BREAKOUT_FOLLOW_THROUGH"

    if market_cycle.current_cycle in _BULL_CYCLES and entry_quality_score < config.min_entry_quality_for_ready_now:
        return "WAIT_FIRST_PULLBACK"

    return "TRADING_RANGE"
