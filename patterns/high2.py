from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from patterns.base import PatternDetector, PatternResult

_MIN_ROWS = 12
_BULLISH_WINDOW = 6
_BULLISH_COUNT_MIN = 4
_TRADING_RANGE_MULTIPLIER = 3.0
_PULLBACK_MIN = 2
_PULLBACK_MAX = 5
_PULLBACK_FULL_SCORE_MAX = 0.50
_PULLBACK_REJECT_MAX = 0.60
_H1_MAX_BARS = 5
_H2_MAX_BARS = 8
_RECENT_UPTREND_LOOKBACK = 40


class High2Detector(PatternDetector):
    """Detect Al Brooks High 2 long setups from OHLCV bars."""

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        if len(df) < _MIN_ROWS:
            return None

        best: PatternResult | None = None
        best_key: tuple[float, int] | None = None
        n = len(df)

        uptrend_start = _recent_uptrend_start(df)
        for pullback_start_idx in range(max(1, uptrend_start + 1), n - 5):
            ail_start_idx = _find_ail_start(df, pullback_start_idx)
            if ail_start_idx is None:
                continue

            prior_swing_high = float(df["High"].iloc[ail_start_idx:pullback_start_idx].max())
            ail_start_low = float(df["Low"].iloc[ail_start_idx])
            prior_leg_height = prior_swing_high - ail_start_low
            if prior_leg_height <= 0:
                continue

            bullish_ratio = _bullish_ratio(df, pullback_start_idx)
            if bullish_ratio * _BULLISH_WINDOW < _BULLISH_COUNT_MIN:
                continue

            context_ranges = (df["High"].iloc[ail_start_idx:pullback_start_idx] - df["Low"].iloc[ail_start_idx:pullback_start_idx]).astype(float)
            median_bar_range_context = float(context_ranges.median())
            if prior_leg_height < (_TRADING_RANGE_MULTIPLIER * median_bar_range_context):
                continue

            for pullback_len in range(_PULLBACK_MIN, _PULLBACK_MAX + 1):
                pullback_end_idx = pullback_start_idx + pullback_len - 1
                if pullback_end_idx >= n - 3:
                    continue

                pullback_low = float(df["Low"].iloc[pullback_start_idx:pullback_end_idx + 1].min())
                retracement_pct = (prior_swing_high - pullback_low) / prior_leg_height
                if retracement_pct > _PULLBACK_REJECT_MAX:
                    continue

                if not _pullback_is_valid(df, pullback_start_idx, pullback_end_idx):
                    continue

                h1_idx = _find_h1(df, pullback_end_idx + 1)
                if h1_idx is None or h1_idx + 2 >= n:
                    continue
                h1_high = float(df["High"].iloc[h1_idx])

                if not _h1_failed(df, h1_idx, h1_high):
                    continue

                h2_idx = _find_h2(df, h1_idx + 3, max(h1_high, prior_swing_high))
                if h2_idx is None:
                    continue
                if not _signal_bar_is_valid(df.iloc[h2_idx], max(h1_high, prior_swing_high)):
                    continue

                trend_score = 1.0
                pullback_score = 1.0 if retracement_pct <= _PULLBACK_FULL_SCORE_MAX else 0.7
                h1_failure_score = 1.0
                signal_score = 1.0
                volume_ratio = _volume_ratio(df, h2_idx)

                raw_score = (
                    0.35 * trend_score
                    + 0.25 * pullback_score
                    + 0.20 * h1_failure_score
                    + 0.20 * signal_score
                )
                if volume_ratio > 1.5:
                    raw_score += 0.05
                if _ail_leg_has_no_strong_bears(df, ail_start_idx, pullback_start_idx):
                    raw_score += 0.05
                if retracement_pct > _PULLBACK_FULL_SCORE_MAX:
                    raw_score -= 0.05
                breakout_distance = (float(df["High"].iloc[h2_idx]) - max(h1_high, prior_swing_high)) / max(h1_high, prior_swing_high)
                if 0.001 <= breakout_distance < 0.002:
                    raw_score -= 0.05
                if pullback_len == _PULLBACK_MAX:
                    raw_score -= 0.05
                confidence = min(1.0, max(0.0, raw_score))

                pivots = {
                    "prior_swing_high": prior_swing_high,
                    "pullback_low": pullback_low,
                    "h1_high": h1_high,
                    "h2_high": float(df["High"].iloc[h2_idx]),
                    "h2_low": float(df["Low"].iloc[h2_idx]),
                }
                pivot_dates = {
                    "prior_swing_high": df.index[int(df["High"].iloc[ail_start_idx:pullback_start_idx].argmax()) + ail_start_idx].date(),
                    "pullback_low": df.index[int(df["Low"].iloc[pullback_start_idx:pullback_end_idx + 1].argmin()) + pullback_start_idx].date(),
                    "h1_high": df.index[h1_idx].date(),
                    "h2_high": df.index[h2_idx].date(),
                    "h2_low": df.index[h2_idx].date(),
                }
                metadata = {
                    "ail_start_idx": ail_start_idx,
                    "pullback_start_idx": pullback_start_idx,
                    "pullback_end_idx": pullback_end_idx,
                    "h1_idx": h1_idx,
                    "h2_idx": h2_idx,
                    "retracement_pct": retracement_pct,
                    "bullish_ratio": bullish_ratio,
                    "volume_ratio": volume_ratio,
                    "ail_start_price_low": ail_start_low,
                    "prior_leg_height": prior_leg_height,
                    "trend_score": trend_score,
                    "pullback_score": pullback_score,
                    "h1_failure_score": h1_failure_score,
                    "signal_score": signal_score,
                }
                candidate = PatternResult(
                    pattern="high2",
                    ticker=ticker,
                    confidence=confidence,
                    detected_on=df.index[-1].date(),
                    pivots=pivots,
                    pivot_dates=pivot_dates,
                    metadata=metadata,
                )
                key = (confidence, h2_idx)
                if best is None or key > best_key:
                    best = candidate
                    best_key = key

        return best


def _recent_uptrend_start(df: pd.DataFrame) -> int:
    """Return the index of the most recent swing low within the last _RECENT_UPTREND_LOOKBACK bars."""
    n = len(df)
    lookback_start = max(0, n - _RECENT_UPTREND_LOOKBACK)
    return lookback_start + int(df["Low"].iloc[lookback_start:].argmin())


def _find_ail_start(df: pd.DataFrame, pullback_start_idx: int) -> int | None:
    end_idx = pullback_start_idx - 1
    ail_start_idx = end_idx
    while ail_start_idx > 0:
        curr = df.iloc[ail_start_idx]
        prev = df.iloc[ail_start_idx - 1]
        if curr["High"] > prev["High"] and curr["Low"] > prev["Low"]:
            ail_start_idx -= 1
            continue
        break
    if end_idx - ail_start_idx + 1 < 3:
        return None
    return ail_start_idx


def _bullish_ratio(df: pd.DataFrame, pullback_start_idx: int) -> float:
    start_idx = max(0, pullback_start_idx - _BULLISH_WINDOW)
    window = df.iloc[start_idx:pullback_start_idx]
    if window.empty:
        return 0.0
    bullish_count = int((window["Close"] > window["Open"]).sum())
    return bullish_count / len(window)


def _pullback_is_valid(df: pd.DataFrame, start_idx: int, end_idx: int) -> bool:
    for idx in range(start_idx, end_idx + 1):
        row = df.iloc[idx]
        if row["High"] == row["Low"]:
            return False
        if idx == 0:
            return False
        prev_high = float(df["High"].iloc[idx - 1])
        body_ratio = abs(float(row["Close"] - row["Open"])) / float(row["High"] - row["Low"])
        is_sideways = body_ratio < 0.30 and float(row["High"]) <= prev_high
        is_bearish = float(row["Close"]) < float(row["Open"])
        if not (is_sideways or is_bearish):
            return False
        if _is_strong_bear_bar(df, idx):
            return False
    return True


def _find_h1(df: pd.DataFrame, start_idx: int) -> int | None:
    for idx in range(start_idx, min(len(df), start_idx + _H1_MAX_BARS)):
        if float(df["High"].iloc[idx]) > float(df["High"].iloc[idx - 1]):
            return idx
    return None


def _h1_failed(df: pd.DataFrame, h1_idx: int, h1_high: float) -> bool:
    window = df.iloc[h1_idx + 1:h1_idx + 3]
    if len(window) < 2:
        return False
    if (window["Close"] > h1_high * 1.001).any():
        return False
    if (window["High"] > h1_high * 1.003).any():
        return False
    return True


def _find_h2(df: pd.DataFrame, start_idx: int, trigger_level: float) -> int | None:
    for idx in range(start_idx, min(len(df), start_idx + _H2_MAX_BARS)):
        if float(df["High"].iloc[idx]) > trigger_level:
            return idx
    return None


def _signal_bar_is_valid(row: pd.Series, trigger_level: float) -> bool:
    high = float(row["High"])
    low = float(row["Low"])
    open_ = float(row["Open"])
    close = float(row["Close"])
    if high == low:
        return False
    if (close - open_) / (high - low) < 0.30:
        return False
    if (high - close) / (high - low) > 0.40:
        return False
    if (high - trigger_level) / trigger_level < 0.001:
        return False
    return True


def _mean_abs_body_20d(df: pd.DataFrame, idx: int) -> float | None:
    prior = df.iloc[max(0, idx - 20):idx]
    if prior.empty:
        return None
    return float((prior["Close"] - prior["Open"]).abs().mean())


def _is_strong_bear_bar(df: pd.DataFrame, idx: int) -> bool:
    row = df.iloc[idx]
    if row["High"] == row["Low"]:
        return True
    mean_abs_body = _mean_abs_body_20d(df, idx)
    if mean_abs_body is None:
        return True
    return (
        (float(row["Open"] - row["Close"]) / float(row["High"] - row["Low"]) > 0.60)
        and (float(row["Open"] - row["Close"]) > 1.5 * mean_abs_body)
    )


def _volume_ratio(df: pd.DataFrame, h2_idx: int) -> float:
    prior = df["Volume"].iloc[max(0, h2_idx - 10):h2_idx]
    if prior.empty:
        return 0.0
    return float(df["Volume"].iloc[h2_idx] / prior.mean())


def _ail_leg_has_no_strong_bears(df: pd.DataFrame, ail_start_idx: int, pullback_start_idx: int) -> bool:
    for idx in range(ail_start_idx, pullback_start_idx):
        if float(df["Close"].iloc[idx]) < float(df["Open"].iloc[idx]) and _is_strong_bear_bar(df, idx):
            return False
    return True
