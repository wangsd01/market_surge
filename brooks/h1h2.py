from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from brooks.breakout import BreakoutEvent
from brooks.config import BrooksConfig, tick_buffer


@dataclass
class TriggerEvent:
    signal_date: date
    trigger_date: date
    trigger_price: float
    signal_bar_low: float
    signal_bar_high: float
    pullback_leg_low: float


@dataclass
class H1H2State:
    h1: TriggerEvent | None
    h2: TriggerEvent | None
    h1_failed: bool
    h2_failed: bool
    h1_structural_failed: bool
    h2_structural_failed: bool
    days_since_h1_trigger: int | None
    days_since_h2_trigger: int | None
    forming: str | None  # "h1" | "h2" | None
    reset_from_failure: bool
    prior_failed_pattern: str | None


def find_anchor(df: pd.DataFrame, breakout_event: BreakoutEvent | None, config: BrooksConfig) -> int | None:
    """Anchor scan_from_anchor's forward scan.

    A recent breakout takes outright priority (this screener's primary use
    case is post-breakout H1/H2 continuation), anchored at the highest high
    since the breakout bar. Without one, fall back to the start of the
    lookback window rather than any single "best" swing point picked by
    argmax/argmin: scan_from_anchor's own "seeking_pullback" state already
    walks forward through any number of rising bars undisturbed until the
    first genuine pullback appears, so an earlier-than-necessary anchor never
    changes the outcome for a clean uptrend -- but a *global* max/min of
    High/Low within the window can land *after* the interesting structure
    (e.g. a later bar that's even higher, or a failure that makes an even
    lower low), silently skipping the very structure being anchored for.
    """
    n = len(df)
    latest_idx = n - 1

    if breakout_event is not None and (latest_idx - breakout_event.idx) <= config.anchor_max_age_bdays:
        since_breakout = df["High"].iloc[breakout_event.idx :]
        breakout_anchor = breakout_event.idx + int(since_breakout.to_numpy().argmax())
        # A currently-still-rising stock will almost always have today's bar
        # qualify as "the breakout" (a new high plus a decent body alone gets
        # most of the way to breakout_score_min_threshold), which leaves no
        # room to scan forward from it. Falling through to the lookback-start
        # fallback below in that case, rather than returning an anchor with
        # nothing after it, is what lets H1/H2 (and EXTENDED_AFTER_H2) still
        # resolve for stocks that are actively extending right now.
        if breakout_anchor < latest_idx:
            return breakout_anchor

    lookback_start = max(0, latest_idx - config.anchor_lookback_bars)
    if lookback_start >= latest_idx:
        return None
    return lookback_start


def scan_from_anchor(df: pd.DataFrame, anchor_idx: int, config: BrooksConfig) -> H1H2State:
    n = len(df)
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    opens = df["Open"].to_numpy()

    state = "seeking_pullback"
    pullback_start_idx: int | None = None
    trigger_count = 0
    h1: TriggerEvent | None = None
    h2: TriggerEvent | None = None

    i = anchor_idx + 1
    while i < n:
        if state == "seeking_pullback":
            if highs[i] < highs[i - 1]:
                pullback_start_idx = i
                state = "in_pullback"
            i += 1
            continue

        # state == "in_pullback"
        if highs[i] > highs[i - 1]:
            signal_idx = i - 1
            trigger_idx = i
            trigger_count += 1
            pullback_leg_low = float(lows[pullback_start_idx : i].min())
            # A stop-buy order set at the signal bar's high (plus buffer) only
            # fills there if the market actually trades up to it. If the
            # trigger bar *opened* above that level (a gap through the stop),
            # the realistic fill is the open -- you cannot get a better price
            # than the market already gapped past before trading began.
            signal_bar_high = float(highs[signal_idx])
            naive_trigger_price = signal_bar_high + tick_buffer(signal_bar_high, config)
            trigger_open = float(opens[trigger_idx])
            trigger_price = max(naive_trigger_price, trigger_open)
            trigger = TriggerEvent(
                signal_date=df.index[signal_idx].date(),
                trigger_date=df.index[trigger_idx].date(),
                trigger_price=trigger_price,
                signal_bar_low=float(lows[signal_idx]),
                signal_bar_high=float(highs[signal_idx]),
                pullback_leg_low=pullback_leg_low,
            )
            if trigger_count == 1:
                h1 = trigger
            elif trigger_count == 2:
                h2 = trigger
                break
            state = "seeking_pullback"
        i += 1

    forming: str | None = None
    if state == "in_pullback" and trigger_count < 2:
        forming = "h1" if trigger_count == 0 else "h2"

    latest_date = df.index[n - 1].date()

    h1_failed, h1_structural_failed = _check_failure(df, h1, n - 1) if h1 is not None else (False, False)
    h2_failed, h2_structural_failed = _check_failure(df, h2, n - 1) if h2 is not None else (False, False)

    return H1H2State(
        h1=h1,
        h2=h2,
        h1_failed=h1_failed,
        h2_failed=h2_failed,
        h1_structural_failed=h1_structural_failed,
        h2_structural_failed=h2_structural_failed,
        days_since_h1_trigger=_business_days_since(h1.trigger_date, latest_date) if h1 is not None else None,
        days_since_h2_trigger=_business_days_since(h2.trigger_date, latest_date) if h2 is not None else None,
        forming=forming,
        reset_from_failure=False,
        prior_failed_pattern=None,
    )


def _check_failure(df: pd.DataFrame, trigger: TriggerEvent, latest_idx: int) -> tuple[bool, bool]:
    trigger_idx = df.index.get_indexer([pd.Timestamp(trigger.trigger_date)])[0]
    window = df.iloc[trigger_idx + 1 : latest_idx + 1]
    if window.empty:
        return False, False

    tight_stop_failure = bool((window["Low"] < trigger.signal_bar_low).any())
    structural_failure = bool((window["Low"] < trigger.pullback_leg_low).any())
    strong_structural_failure = bool(
        ((window["Close"] < trigger.pullback_leg_low) & (window["Close"] < window["Open"])).any()
    )
    failed = tight_stop_failure or structural_failure or strong_structural_failure
    return failed, (structural_failure or strong_structural_failure)


def _business_days_since(trigger_date: date, latest_date: date) -> int:
    return max(len(pd.bdate_range(trigger_date, latest_date)) - 1, 0)


def compute_h1h2_state(
    df: pd.DataFrame, breakout_event: BreakoutEvent | None, config: BrooksConfig
) -> H1H2State | None:
    anchor_idx = find_anchor(df, breakout_event, config)
    if anchor_idx is None or anchor_idx >= len(df) - 1:
        return None

    state = scan_from_anchor(df, anchor_idx, config)

    most_advanced = state.h2 if state.h2 is not None else state.h1
    most_advanced_failed = state.h2_failed if state.h2 is not None else state.h1_failed
    if most_advanced is not None and most_advanced_failed and config.max_state_resets > 0:
        failure_confirm_idx = _first_failure_idx(df, most_advanced)
        if failure_confirm_idx is not None and failure_confirm_idx < len(df) - 1:
            reset_anchor = find_anchor(df.iloc[: failure_confirm_idx + 1], None, config)
            # Search forward from the failure point for a fresh anchor/swing high.
            fresh_anchor = _fresh_anchor_after(df, failure_confirm_idx, config)
            if fresh_anchor is not None:
                reset_state = scan_from_anchor(df, fresh_anchor, config)
                reset_state.reset_from_failure = True
                reset_state.prior_failed_pattern = "h2" if state.h2 is not None else "h1"
                return reset_state

    return state


def _first_failure_idx(df: pd.DataFrame, trigger: TriggerEvent) -> int | None:
    trigger_idx = df.index.get_indexer([pd.Timestamp(trigger.trigger_date)])[0]
    window = df.iloc[trigger_idx + 1 :]
    for offset, (_, row) in enumerate(window.iterrows()):
        idx = trigger_idx + 1 + offset
        if row["Low"] < trigger.signal_bar_low or row["Low"] < trigger.pullback_leg_low:
            return idx
        if row["Close"] < trigger.pullback_leg_low and row["Close"] < row["Open"]:
            return idx
    return None


def _fresh_anchor_after(df: pd.DataFrame, failure_idx: int, config: BrooksConfig) -> int | None:
    remaining = df["High"].iloc[failure_idx:]
    if len(remaining) < 2:
        return None
    return failure_idx + int(remaining.to_numpy().argmax())
