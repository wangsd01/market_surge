from __future__ import annotations

from datetime import date

import pandas as pd

from brooks.breakout import BreakoutEvent, FollowThroughResult
from brooks.config import BrooksConfig
from brooks.extension import ExtensionResult
from brooks.h1h2 import H1H2State
from brooks.market_cycle import MarketCycleResult
from brooks.scoring import ScoreResult
from brooks.stops_targets import StopSet, TargetSet

ALL_OUTPUT_COLUMNS = [
    "ticker",
    "date",
    "market_cycle",
    "prior_trend",
    "trading_range_length",
    "earnings_recent",
    "days_since_earnings",
    "gap_pct",
    "true_gap",
    "gap_still_open",
    "breakout_score",
    "follow_through_score",
    "retracement_depth",
    "setup_state",
    "h1_status",
    "h1_trigger_date",
    "days_since_h1",
    "h2_status",
    "h2_trigger_date",
    "days_since_h2",
    "signal_bar_high",
    "signal_bar_low",
    "pullback_low",
    "proposed_entry",
    "tight_stop",
    "structural_stop",
    "risk_pct",
    "nearest_resistance",
    "target_1",
    "target_2",
    "rr_target_1",
    "rr_target_2",
    "setup_quality_score",
    "entry_quality_score",
    "trade_score",
    "reason",
    "warning",
]

_READY_NOW_STATES = {
    "STRONG_BREAKOUT",
    "STRONG_BREAKOUT_FOLLOW_THROUGH",
    "H1_TRIGGERED_TODAY",
    "H1_TRIGGERED_RECENTLY",
    "H2_TRIGGERED_TODAY",
    "H2_TRIGGERED_RECENTLY",
    "BREAKOUT_PULLBACK",
}
_STRONG_FOLLOW_THROUGH_STATES = {"STRONG_BREAKOUT", "STRONG_BREAKOUT_FOLLOW_THROUGH"}
_EXTENDED_STATES = {"EXTENDED_AFTER_BREAKOUT", "EXTENDED_AFTER_H2"}
_FAILED_STATES = {"FAILED_H1", "FAILED_H2"}


def _h1_status(h1h2_state: H1H2State | None) -> str | None:
    if h1h2_state is None:
        return None
    if h1h2_state.h1 is None:
        return "forming" if h1h2_state.forming == "h1" else None
    return "failed" if h1h2_state.h1_failed else "triggered"


def _h2_status(h1h2_state: H1H2State | None) -> str | None:
    if h1h2_state is None:
        return None
    if h1h2_state.h2 is None:
        return "forming" if h1h2_state.forming == "h2" else None
    return "failed" if h1h2_state.h2_failed else "triggered"


def _build_reason(market_cycle: MarketCycleResult, setup_state: str, h1h2_state: H1H2State | None) -> str:
    parts = [f"{market_cycle.current_cycle.replace('_', ' ').title()} context", f"state: {setup_state}"]
    if h1h2_state is not None and h1h2_state.h2 is not None:
        parts.append("H2 pullback confirmed")
    elif h1h2_state is not None and h1h2_state.h1 is not None:
        parts.append("H1 pullback confirmed")
    return "; ".join(parts) + "."


def _build_warning(
    h1h2_state: H1H2State | None,
    extension: ExtensionResult,
    targets: TargetSet,
    config: BrooksConfig,
) -> str:
    warnings: list[str] = []
    if h1h2_state is not None and h1h2_state.reset_from_failure and h1h2_state.prior_failed_pattern:
        warnings.append(
            f"Prior {h1h2_state.prior_failed_pattern.upper()} failed; current setup is a new attempt."
        )
    if extension.is_extended and extension.reason:
        warnings.append(f"Extended ({extension.reason}) -- do not chase.")
    if targets.rr_target_1 < config.min_plausible_rr:
        warnings.append("Reward/risk to nearest resistance is below the plausible minimum.")
    return " ".join(warnings)


def assemble_row(
    *,
    ticker: str,
    date: date,
    market_cycle: MarketCycleResult,
    breakout_event: BreakoutEvent | None,
    follow_through: FollowThroughResult | None,
    h1h2_state: H1H2State | None,
    extension: ExtensionResult,
    stops: StopSet,
    targets: TargetSet,
    scores: ScoreResult,
    setup_state: str,
    proposed_entry: float,
    dollar_vol: float,
    config: BrooksConfig | None = None,
) -> dict:
    config = config or BrooksConfig()
    h1 = h1h2_state.h1 if h1h2_state is not None else None
    h2 = h1h2_state.h2 if h1h2_state is not None else None
    signal_bar = h2 if h2 is not None else h1

    entry = proposed_entry
    risk_pct = (entry - stops.structural_stop) / entry if stops.structural_stop is not None and entry else None

    return {
        "ticker": ticker,
        "date": date,
        "market_cycle": market_cycle.current_cycle,
        "prior_trend": market_cycle.prior_trend,
        "trading_range_length": market_cycle.trading_range_length,
        "earnings_recent": None,
        "days_since_earnings": None,
        "gap_pct": breakout_event.gap_pct if breakout_event is not None else None,
        "true_gap": breakout_event.true_gap_up if breakout_event is not None else None,
        "gap_still_open": follow_through.gap_still_open if follow_through is not None else None,
        "breakout_score": breakout_event.breakout_score if breakout_event is not None else None,
        "follow_through_score": follow_through.follow_through_score if follow_through is not None else None,
        "retracement_depth": follow_through.retracement_pct if follow_through is not None else None,
        "setup_state": setup_state,
        "h1_status": _h1_status(h1h2_state),
        "h1_trigger_date": h1.trigger_date if h1 is not None else None,
        "days_since_h1": h1h2_state.days_since_h1_trigger if h1h2_state is not None else None,
        "h2_status": _h2_status(h1h2_state),
        "h2_trigger_date": h2.trigger_date if h2 is not None else None,
        "days_since_h2": h1h2_state.days_since_h2_trigger if h1h2_state is not None else None,
        "signal_bar_high": signal_bar.signal_bar_high if signal_bar is not None else None,
        "signal_bar_low": signal_bar.signal_bar_low if signal_bar is not None else None,
        "pullback_low": signal_bar.pullback_leg_low if signal_bar is not None else None,
        "proposed_entry": proposed_entry,
        "tight_stop": stops.tight_stop,
        "structural_stop": stops.structural_stop,
        "risk_pct": risk_pct,
        "nearest_resistance": targets.nearest_resistance,
        "target_1": targets.target_1,
        "target_2": targets.target_2,
        "rr_target_1": targets.rr_target_1,
        "rr_target_2": targets.rr_target_2,
        "setup_quality_score": scores.setup_quality_score,
        "entry_quality_score": scores.entry_quality_score,
        "trade_score": scores.trade_score,
        "reason": _build_reason(market_cycle, setup_state, h1h2_state),
        "warning": _build_warning(h1h2_state, extension, targets, config),
    }


def build_watchlist_buckets(df: pd.DataFrame, config: BrooksConfig | None = None) -> dict[str, pd.DataFrame]:
    config = config or BrooksConfig()

    def _sorted(mask: pd.Series) -> pd.DataFrame:
        return df.loc[mask].sort_values("trade_score", ascending=False).reset_index(drop=True)

    ready_now_mask = (
        df["setup_state"].isin(_READY_NOW_STATES)
        & (df["entry_quality_score"] >= config.min_entry_quality_for_ready_now)
        & (df["rr_target_1"] >= config.min_plausible_rr)
    )

    return {
        "READY_NOW": _sorted(ready_now_mask),
        "WAIT_PULLBACK": _sorted(df["setup_state"] == "WAIT_FIRST_PULLBACK"),
        "H1_WATCH": _sorted(df["setup_state"] == "H1_FORMING"),
        "H2_WATCH": _sorted(df["setup_state"] == "H2_FORMING"),
        "STRONG_FOLLOW_THROUGH": _sorted(df["setup_state"].isin(_STRONG_FOLLOW_THROUGH_STATES)),
        "EXTENDED_DO_NOT_CHASE": _sorted(df["setup_state"].isin(_EXTENDED_STATES)),
        "FAILED_SETUP": _sorted(df["setup_state"].isin(_FAILED_STATES)),
    }
