from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

from brooks.config import BrooksConfig

_BULL_TREND_STATES = {"STRONG_BULL_TREND", "BULL_TREND"}
_BEAR_TREND_STATES = {"STRONG_BEAR_TREND", "BEAR_TREND"}
_TR_STATES = {"TRADING_RANGE", "BULLISH_TRADING_RANGE", "BEARISH_TRADING_RANGE"}


@dataclass
class MarketCycleResult:
    current_cycle: str
    prior_trend: str | None
    trading_range_length: int
    bear_relevance: float


def _swing_indices(df: pd.DataFrame, config: BrooksConfig) -> tuple[np.ndarray, np.ndarray]:
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    high_idx = argrelextrema(highs, np.greater_equal, order=config.swing_order)[0]
    low_idx = argrelextrema(lows, np.less_equal, order=config.swing_order)[0]

    swings = sorted(
        [(i, "high", highs[i]) for i in high_idx] + [(i, "low", lows[i]) for i in low_idx]
    )
    kept: list[tuple[int, str, float]] = []
    last_opposite: float | None = None
    for i, kind, price in swings:
        if last_opposite is not None and last_opposite != 0:
            if abs(price - last_opposite) / abs(last_opposite) < config.min_swing_pct:
                continue
        kept.append((i, kind, price))
        last_opposite = price

    kept_high_idx = np.array([i for i, kind, _ in kept if kind == "high"], dtype=int)
    kept_low_idx = np.array([i for i, kind, _ in kept if kind == "low"], dtype=int)
    return kept_high_idx, kept_low_idx


def _hh_hl_counts(df: pd.DataFrame, high_idx: np.ndarray, low_idx: np.ndarray, window_start: int, window_end: int) -> tuple[int, int, int, int]:
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    win_highs = sorted(i for i in high_idx if window_start <= i <= window_end)
    win_lows = sorted(i for i in low_idx if window_start <= i <= window_end)

    hh_count = sum(1 for a, b in zip(win_highs, win_highs[1:]) if highs[b] > highs[a])
    lh_count = sum(1 for a, b in zip(win_highs, win_highs[1:]) if highs[b] <= highs[a])
    hl_count = sum(1 for a, b in zip(win_lows, win_lows[1:]) if lows[b] > lows[a])
    ll_count = sum(1 for a, b in zip(win_lows, win_lows[1:]) if lows[b] <= lows[a])
    return hh_count, hl_count, lh_count, ll_count


def _overlap_frac(window: pd.DataFrame, config: BrooksConfig) -> float:
    highs = window["High"].to_numpy()
    lows = window["Low"].to_numpy()
    ranges = highs - lows
    if len(window) < 2:
        return 0.0
    overlaps = 0
    pairs = 0
    for i in range(1, len(window)):
        min_range = min(ranges[i], ranges[i - 1])
        if min_range <= 0:
            continue
        pairs += 1
        overlap = min(highs[i], highs[i - 1]) - max(lows[i], lows[i - 1])
        if overlap / min_range >= config.bar_overlap_ratio_threshold:
            overlaps += 1
    return overlaps / pairs if pairs else 0.0


def classify_cycle_window(
    df: pd.DataFrame,
    window_start: int,
    window_end: int,
    high_idx: np.ndarray,
    low_idx: np.ndarray,
    config: BrooksConfig,
) -> str:
    window = df.iloc[window_start : window_end + 1]
    n = len(window)
    if n == 0:
        return "TRADING_RANGE"

    bull_ratio = float((window["Close"] > window["Open"]).sum()) / n
    bear_ratio = float((window["Close"] < window["Open"]).sum()) / n
    ema20_slope = float(window["slope_20"].iloc[-1]) if not pd.isna(window["slope_20"].iloc[-1]) else 0.0
    pct_above_ema20 = float((window["Close"] > window["ema20"]).sum()) / n
    overlap_frac = _overlap_frac(window, config)
    channel_high = window["High"].max()
    channel_low = window["Low"].min()
    mid = (channel_high + channel_low) / 2
    channel_width_pct = (channel_high - channel_low) / mid if mid > 0 else 0.0

    hh_count, hl_count, lh_count, ll_count = _hh_hl_counts(df, high_idx, low_idx, window_start, window_end)
    hh_hl_dominant = (hh_count + hl_count) > (lh_count + ll_count)
    lh_ll_dominant = (lh_count + ll_count) > (hh_count + hl_count)

    if ema20_slope > 0 and pct_above_ema20 >= 0.80 and bull_ratio >= config.strong_trend_bar_ratio and hh_hl_dominant:
        return "STRONG_BULL_TREND"
    if ema20_slope > 0 and pct_above_ema20 >= 0.60 and bull_ratio >= config.trend_bar_ratio and hh_hl_dominant:
        return "BULL_TREND"
    if ema20_slope < 0 and pct_above_ema20 <= 0.20 and bear_ratio >= config.strong_trend_bar_ratio and lh_ll_dominant:
        return "STRONG_BEAR_TREND"
    if ema20_slope < 0 and pct_above_ema20 <= 0.40 and bear_ratio >= config.trend_bar_ratio and lh_ll_dominant:
        return "BEAR_TREND"

    if overlap_frac >= config.trading_range_overlap_threshold and channel_width_pct <= config.max_range_channel_width_pct:
        if bull_ratio >= 0.55 or pct_above_ema20 >= 0.60:
            return "BULLISH_TRADING_RANGE"
        if bull_ratio <= 0.45 or pct_above_ema20 <= 0.40:
            return "BEARISH_TRADING_RANGE"
        return "TRADING_RANGE"

    if _is_possible_reversal(df, window_start, window_end, high_idx, low_idx, config):
        return "POSSIBLE_MAJOR_TREND_REVERSAL"

    return "TRADING_RANGE"


def _is_possible_reversal(
    df: pd.DataFrame,
    window_start: int,
    window_end: int,
    high_idx: np.ndarray,
    low_idx: np.ndarray,
    config: BrooksConfig,
) -> bool:
    reversal_start = window_end - config.reversal_lookback_bars + 1
    if reversal_start <= window_start:
        return False

    prior_state = classify_cycle_window(df, window_start, reversal_start - 1, high_idx, low_idx, config)
    if prior_state not in _BEAR_TREND_STATES:
        return False

    from brooks.breakout import extreme_bull_breakout

    tail = df.iloc[reversal_start : window_end + 1]
    for _, bar in tail.iterrows():
        if extreme_bull_breakout(bar, config) and bar["Close"] > bar["ema20"]:
            return True
    return False


def _trading_range_length(df: pd.DataFrame, high_idx: np.ndarray, low_idx: np.ndarray, config: BrooksConfig) -> int:
    n = len(df)
    length = 0
    e = n - 1
    while e >= config.tr_length_probe_window - 1:
        window_start = e - config.tr_length_probe_window + 1
        state = classify_cycle_window(df, window_start, e, high_idx, low_idx, config)
        if state in _TR_STATES:
            length += 1
            e -= 1
        else:
            break
    return length


def _prior_trend(
    df: pd.DataFrame, trading_range_length: int, high_idx: np.ndarray, low_idx: np.ndarray, config: BrooksConfig
) -> str | None:
    if trading_range_length == 0:
        return None
    n = len(df)
    window_end = n - 1 - trading_range_length
    window_start = max(0, window_end - config.cycle_window + 1)
    if window_end < window_start:
        return None
    return classify_cycle_window(df, window_start, window_end, high_idx, low_idx, config)


def _bear_relevance(prior_trend: str | None, trading_range_length: int, config: BrooksConfig) -> float:
    if prior_trend not in _BEAR_TREND_STATES:
        return 1.0
    if trading_range_length <= config.short_tr_bdays:
        return 1.0
    if trading_range_length >= config.mature_tr_bdays:
        return config.mature_tr_bear_relevance_floor
    frac = (trading_range_length - config.short_tr_bdays) / (config.mature_tr_bdays - config.short_tr_bdays)
    return 1.0 - frac * (1.0 - config.mature_tr_bear_relevance_floor)


def classify_market_cycle(df: pd.DataFrame, config: BrooksConfig) -> MarketCycleResult:
    n = len(df)
    high_idx, low_idx = _swing_indices(df, config)

    window_end = n - 1
    window_start = max(0, window_end - config.cycle_window + 1)
    current_cycle = classify_cycle_window(df, window_start, window_end, high_idx, low_idx, config)

    trading_range_length = _trading_range_length(df, high_idx, low_idx, config)
    prior_trend = _prior_trend(df, trading_range_length, high_idx, low_idx, config)
    bear_relevance = _bear_relevance(prior_trend, trading_range_length, config)

    return MarketCycleResult(
        current_cycle=current_cycle,
        prior_trend=prior_trend,
        trading_range_length=trading_range_length,
        bear_relevance=bear_relevance,
    )
