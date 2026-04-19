from __future__ import annotations

from datetime import date

import pandas as pd

from patterns.base import PatternDetector, PatternResult

_MIN_ROWS = 35
_SWING_ORDER = 2
_MIN_BASE_BDAYS = 35
_MIN_BASE_DEPTH = 0.15
_MAX_BASE_DEPTH = 0.33
_MAX_UNDERCUT_PCT = 0.05
_ACTIVE_ZONE_MAX = 0.10


def _is_swing_low(values: list[float], idx: int, order: int = _SWING_ORDER) -> bool:
    if idx < order or idx + order >= len(values):
        return False
    center = values[idx]
    neighbors = values[idx - order:idx] + values[idx + 1:idx + order + 1]
    return all(center < value for value in neighbors)


def _candidate_lows(lows: list[float]) -> list[int]:
    return [idx for idx in range(len(lows)) if _is_swing_low(lows, idx)]


def _avg_vol(volumes: list[float], idx: int) -> float:
    lo = max(0, idx - 1)
    hi = min(len(volumes), idx + 2)
    window = volumes[lo:hi]
    return sum(window) / len(window)


def _find_breakout(closes: list[float], buy_point: float, start_idx: int) -> int | None:
    for idx in range(start_idx, len(closes)):
        if closes[idx] > buy_point:
            return idx
    return None


def _volume_ratio(volumes: list[float], idx: int) -> float:
    start_idx = max(0, idx - 49)
    baseline = volumes[start_idx:idx + 1]
    average = sum(baseline) / len(baseline)
    if average <= 0:
        return 0.0
    return volumes[idx] / average


def _confidence(
    *,
    base_depth_pct: float,
    undercut_pct: float,
    rebound_pct: float,
    second_trough_volume: float,
    first_trough_volume: float,
    breakout_volume_ratio: float | None,
    state: str,
) -> float:
    depth_score = 1.0 if 0.18 <= base_depth_pct <= 0.30 else 0.85
    undercut_score = 1.0 - min(abs(undercut_pct - 0.02) / 0.03, 1.0) * 0.25
    rebound_score = min(rebound_pct / 0.15, 1.0)
    volume_score = 1.0 if second_trough_volume <= first_trough_volume else 0.75
    state_score = 1.0 if state == "confirmed" else 0.88

    raw = (
        0.25 * depth_score
        + 0.20 * undercut_score
        + 0.20 * rebound_score
        + 0.15 * volume_score
        + 0.20 * state_score
    )
    if breakout_volume_ratio is not None:
        raw += 0.05 if breakout_volume_ratio >= 1.4 else (-0.03 if breakout_volume_ratio < 1.0 else 0.0)
    return max(0.0, min(raw, 1.0))


class DoubleBottomDetector(PatternDetector):
    """Detect IBD-style double-bottom bases from swing highs and lows."""

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        if len(df) < _MIN_ROWS:
            return None

        highs = pd.to_numeric(df["High"], errors="coerce").astype(float).tolist()
        lows = pd.to_numeric(df["Low"], errors="coerce").astype(float).tolist()
        closes = pd.to_numeric(df["Close"], errors="coerce").astype(float).tolist()
        volumes = pd.to_numeric(df["Volume"], errors="coerce").astype(float).tolist()
        dates = list(df.index)

        trough_indices = _candidate_lows(lows)
        best: PatternResult | None = None
        best_key: tuple[int, int, int, float] | None = None

        for left_pos, first_trough_idx in enumerate(trough_indices):
            if first_trough_idx < 2:
                continue

            left_high_idx = max(range(first_trough_idx), key=lambda idx: highs[idx])
            left_high = highs[left_high_idx]
            first_trough = lows[first_trough_idx]

            for second_trough_idx in trough_indices[left_pos + 1:]:
                if second_trough_idx <= first_trough_idx + 3:
                    continue

                second_trough = lows[second_trough_idx]
                undercut_pct = (first_trough - second_trough) / first_trough if first_trough > 0 else -1.0
                if undercut_pct < 0.0 or undercut_pct > _MAX_UNDERCUT_PCT:
                    continue

                base_length_bdays = len(pd.bdate_range(dates[left_high_idx], dates[second_trough_idx]))
                if base_length_bdays < _MIN_BASE_BDAYS:
                    continue

                base_depth_pct = (left_high - min(first_trough, second_trough)) / left_high if left_high > 0 else 0.0
                if base_depth_pct < _MIN_BASE_DEPTH or base_depth_pct > _MAX_BASE_DEPTH:
                    continue

                middle_window = highs[first_trough_idx + 1:second_trough_idx]
                if not middle_window:
                    continue
                middle_high_offset = max(range(len(middle_window)), key=lambda idx: middle_window[idx])
                middle_high_idx = first_trough_idx + 1 + middle_high_offset
                middle_high = highs[middle_high_idx]
                if middle_high >= left_high:
                    continue

                avg_trough = (first_trough + second_trough) / 2.0
                rebound_pct = (middle_high - avg_trough) / avg_trough if avg_trough > 0 else 0.0

                breakout_idx = _find_breakout(closes, middle_high, second_trough_idx + 1)
                breakout_volume_ratio: float | None = None
                if breakout_idx is not None:
                    state = "confirmed"
                    breakout_volume_ratio = _volume_ratio(volumes, breakout_idx)
                else:
                    active_zone_pct = (middle_high - closes[-1]) / middle_high if middle_high > 0 else 1.0
                    if active_zone_pct < 0.0 or active_zone_pct > _ACTIVE_ZONE_MAX:
                        continue
                    state = "active_pre_breakout"

                first_trough_volume = _avg_vol(volumes, first_trough_idx)
                second_trough_volume = _avg_vol(volumes, second_trough_idx)
                confidence = _confidence(
                    base_depth_pct=base_depth_pct,
                    undercut_pct=undercut_pct,
                    rebound_pct=rebound_pct,
                    second_trough_volume=second_trough_volume,
                    first_trough_volume=first_trough_volume,
                    breakout_volume_ratio=breakout_volume_ratio,
                    state=state,
                )

                pivots = {
                    "left_high": float(left_high),
                    "first_trough": float(first_trough),
                    "middle_high": float(middle_high),
                    "second_trough": float(second_trough),
                }
                pivot_dates: dict[str, date] = {
                    "left_high": dates[left_high_idx].date(),
                    "first_trough": dates[first_trough_idx].date(),
                    "middle_high": dates[middle_high_idx].date(),
                    "second_trough": dates[second_trough_idx].date(),
                }
                metadata = {
                    "state": state,
                    "buy_point": float(middle_high),
                    "base_length_bdays": int(base_length_bdays),
                    "base_depth_pct": float(base_depth_pct),
                    "undercut_pct": float(undercut_pct),
                    "rebound_pct": float(rebound_pct),
                }
                if breakout_idx is not None:
                    pivots["breakout"] = float(closes[breakout_idx])
                    pivot_dates["breakout"] = dates[breakout_idx].date()
                    metadata["breakout_volume_ratio"] = float(breakout_volume_ratio)
                else:
                    metadata["active_zone_pct_below_buy_point"] = float((middle_high - closes[-1]) / middle_high)

                candidate = PatternResult(
                    pattern="double_bottom",
                    ticker=ticker,
                    confidence=confidence,
                    detected_on=dates[-1].date(),
                    pivots=pivots,
                    pivot_dates=pivot_dates,
                    metadata=metadata,
                )
                candidate_key = (
                    1 if state == "confirmed" else 0,
                    second_trough_idx,
                    second_trough_idx - first_trough_idx,
                    confidence,
                )
                if best is None or candidate_key > best_key:
                    best = candidate
                    best_key = candidate_key

        return best
