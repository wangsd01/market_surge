from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from brooks.config import BrooksConfig


@dataclass
class BreakoutEvent:
    idx: int
    date: date
    breakout_score: float
    is_strong: bool
    is_extreme: bool
    breakout_level: float  # resistance price level cleared -- NOT a stop candidate
    low: float  # the breakout bar's own Low -- the real structural stop candidate
    prior_high: float | None  # prior bar's High -- top of the gap zone, for gap_failure_stop
    gap_pct: float
    true_gap_up: bool
    volume_ratio: float


@dataclass
class FollowThroughResult:
    follow_through_score: float | None
    retracement_pct: float
    gap_still_open: bool | None


def strong_bull_bar(bar: pd.Series, config: BrooksConfig) -> bool:
    if pd.isna(bar.get("body_pct")) or pd.isna(bar.get("close_location")) or pd.isna(bar.get("range_atr_ratio")):
        return False
    return bool(
        bar["Close"] > bar["Open"]
        and bar["body_pct"] >= config.strong_body_ratio
        and bar["close_location"] >= config.strong_close_location
        and bar["range_atr_ratio"] >= config.strong_range_atr_ratio
    )


def extreme_bull_breakout(bar: pd.Series, config: BrooksConfig) -> bool:
    if pd.isna(bar.get("close_location")) or pd.isna(bar.get("range_atr_ratio")):
        return False
    clears_resistance = (not pd.isna(bar.get("recent_high_20")) and bar["Close"] > bar["recent_high_20"]) or (
        not pd.isna(bar.get("recent_high_50")) and bar["Close"] > bar["recent_high_50"]
    )
    return bool(
        bar["range_atr_ratio"] >= config.extreme_range_atr_ratio
        and bar["close_location"] >= config.extreme_close_location
        and clears_resistance
    )


_BREAKOUT_SCORE_RULES: list[tuple[str, object, float]] = [
    ("large_bull_body", lambda b, c: not pd.isna(b.get("body_pct")) and b["body_pct"] >= c.strong_body_ratio, 1.0),
    ("body_vs_atr", lambda b, c: not pd.isna(b.get("range_atr_ratio")) and b["range_atr_ratio"] >= c.strong_range_atr_ratio, 1.0),
    ("close_near_high", lambda b, c: not pd.isna(b.get("close_location")) and b["close_location"] >= c.strong_close_location, 1.0),
    ("little_upper_tail", lambda b, c: not pd.isna(b.get("upper_tail_pct")) and b["upper_tail_pct"] <= (1 - c.strong_close_location), 1.0),
    ("gap_up", lambda b, c: not pd.isna(b.get("gap_pct")) and b["gap_pct"] > 0, 1.0),
    ("true_gap", lambda b, c: bool(b.get("true_gap_up")), 1.0),
    ("new_20d_high", lambda b, c: not pd.isna(b.get("recent_high_20")) and b["Close"] > b["recent_high_20"], 1.0),
    ("new_50d_high", lambda b, c: not pd.isna(b.get("recent_high_50")) and b["Close"] > b["recent_high_50"], 1.0),
    ("new_252d_high", lambda b, c: not pd.isna(b.get("recent_high_252")) and b["Close"] > b["recent_high_252"], 1.0),
    ("volume_expansion", lambda b, c: not pd.isna(b.get("vol_ratio")) and b["vol_ratio"] >= c.breakout_vol_ratio, 1.0),
    ("range_extreme", lambda b, c: not pd.isna(b.get("range_atr_ratio")) and b["range_atr_ratio"] >= c.extreme_range_atr_ratio, 1.0),
]


def _breakout_score(bar: pd.Series, config: BrooksConfig) -> float:
    total_weight = sum(weight for _, _, weight in _BREAKOUT_SCORE_RULES)
    earned = sum(weight for _, predicate, weight in _BREAKOUT_SCORE_RULES if predicate(bar, config))
    return earned / total_weight


def find_latest_breakout(df: pd.DataFrame, config: BrooksConfig) -> BreakoutEvent | None:
    n = len(df)
    start = max(0, n - config.breakout_search_bars)
    for idx in range(n - 1, start - 1, -1):
        bar = df.iloc[idx]
        clears_resistance = (not pd.isna(bar.get("recent_high_20")) and bar["Close"] > bar["recent_high_20"]) or (
            not pd.isna(bar.get("recent_high_50")) and bar["Close"] > bar["recent_high_50"]
        )
        if not clears_resistance:
            continue
        score = _breakout_score(bar, config)
        if score >= config.breakout_score_min_threshold:
            breakout_level = max(
                v for v in (bar.get("recent_high_20"), bar.get("recent_high_50")) if v is not None and not pd.isna(v)
            )
            prior_high = float(df.iloc[idx - 1]["High"]) if idx > 0 else None
            return BreakoutEvent(
                idx=idx,
                date=df.index[idx].date(),
                breakout_score=score,
                is_strong=strong_bull_bar(bar, config),
                is_extreme=extreme_bull_breakout(bar, config),
                breakout_level=float(breakout_level),
                low=float(bar["Low"]),
                prior_high=prior_high,
                gap_pct=float(bar["gap_pct"]) if not pd.isna(bar["gap_pct"]) else 0.0,
                true_gap_up=bool(bar["true_gap_up"]),
                volume_ratio=float(bar["vol_ratio"]) if not pd.isna(bar["vol_ratio"]) else 0.0,
            )
    return None


_FOLLOW_THROUGH_POSITIVE_RULES: list[tuple[str, object, float]] = [
    ("higher_high", lambda w, b: w["High"].iloc[-1] > b["High"], 1.0),
    ("higher_low", lambda w, b: w["Low"].iloc[-1] > b["Low"], 1.0),
    ("bull_closes", lambda w, b: (w["Close"] > w["Open"]).mean() >= 0.5, 1.0),
    ("close_above_midpoint", lambda w, b: w["Close"].iloc[-1] > (b["High"] + b["Low"]) / 2, 1.0),
]

_FOLLOW_THROUGH_NEGATIVE_RULES: list[tuple[str, object, float]] = [
    ("closes_near_low", lambda w, b: not pd.isna(w["close_location"].iloc[-1]) and w["close_location"].iloc[-1] <= 0.25, 1.0),
    ("breaks_breakout_low", lambda w, b: w["Low"].min() < b["Low"], 1.0),
    ("consecutive_bear_closes", lambda w, b: (w["Close"] < w["Open"]).sum() >= 2, 1.0),
]


def follow_through(df: pd.DataFrame, breakout_event: BreakoutEvent, config: BrooksConfig) -> FollowThroughResult:
    breakout_bar = df.iloc[breakout_event.idx]
    breakout_high = float(breakout_bar["High"])
    breakout_low = float(breakout_bar["Low"])

    latest_idx = len(df) - 1
    since_breakout = df.iloc[breakout_event.idx + 1 : latest_idx + 1]
    if since_breakout.empty:
        retracement_pct = 0.0
    else:
        min_low_since = float(since_breakout["Low"].min())
        retracement_pct = (breakout_high - min_low_since) / (breakout_high - breakout_low)

    gap_still_open: bool | None = None
    if breakout_event.true_gap_up:
        prior_high = float(df.iloc[breakout_event.idx - 1]["High"]) if breakout_event.idx > 0 else breakout_low
        after = df.iloc[breakout_event.idx + 1 : latest_idx + 1]
        gap_still_open = True if after.empty else bool((after["Low"] > prior_high).all())

    window = df.iloc[breakout_event.idx + 1 : breakout_event.idx + 1 + config.follow_through_bars]
    if window.empty:
        follow_through_score = None
    else:
        pos_total = sum(w for _, _, w in _FOLLOW_THROUGH_POSITIVE_RULES)
        neg_total = sum(w for _, _, w in _FOLLOW_THROUGH_NEGATIVE_RULES)
        pos_earned = sum(w for _, predicate, w in _FOLLOW_THROUGH_POSITIVE_RULES if predicate(window, breakout_bar))
        neg_earned = sum(w for _, predicate, w in _FOLLOW_THROUGH_NEGATIVE_RULES if predicate(window, breakout_bar))
        max_pos_weight = pos_total
        follow_through_score = max(-1.0, min(1.0, (pos_earned - neg_earned) / max_pos_weight))

    return FollowThroughResult(
        follow_through_score=follow_through_score,
        retracement_pct=retracement_pct,
        gap_still_open=gap_still_open,
    )
