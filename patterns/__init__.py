from datetime import date

import pandas as pd

from patterns.base import PatternResult

RECENT_PATTERN_MAX_AGE_BDAYS = 10


def _build_detectors():
    from patterns.cup_handle import CupHandleDetector
    from patterns.double_bottom import DoubleBottomDetector
    from patterns.flat_base import FlatBaseDetector
    from patterns.high2 import High2Detector
    from patterns.vcp import VCPDetector

    return [
        CupHandleDetector(),
        DoubleBottomDetector(),
        FlatBaseDetector(),
        High2Detector(),
        VCPDetector(),
    ]


def is_recent_pattern_result(
    pattern_result: PatternResult,
    *,
    latest_date: date,
    max_age_bdays: int = RECENT_PATTERN_MAX_AGE_BDAYS,
) -> bool:
    if pattern_result.pattern == "double_bottom":
        state = pattern_result.metadata.get("state")
        if state == "confirmed" and pattern_result.pivot_dates.get("breakout") is not None:
            reference_date = pattern_result.pivot_dates["breakout"]
            age_bdays = max(len(pd.bdate_range(reference_date, latest_date)) - 1, 0)
            return age_bdays <= max_age_bdays
        if state == "active_pre_breakout":
            reference_date = pattern_result.detected_on
            age_bdays = max(len(pd.bdate_range(reference_date, latest_date)) - 1, 0)
            return age_bdays <= max_age_bdays

    pivot_dates = [d for d in pattern_result.pivot_dates.values() if d is not None]
    reference_date = max(pivot_dates) if pivot_dates else pattern_result.detected_on
    if reference_date > latest_date:
        return True
    age_bdays = max(len(pd.bdate_range(reference_date, latest_date)) - 1, 0)
    return age_bdays <= max_age_bdays


def detect_all(df: pd.DataFrame, ticker: str) -> list[PatternResult]:
    """Run all detectors on pre-sliced OHLCV data (90 trading days, no NaN).

    Returns all detected patterns sorted by confidence descending.
    Returns [] if df has fewer than 45 rows.
    """
    if len(df) < 45:
        return []
    results = []
    for detector in _build_detectors():
        result = detector.detect(df, ticker)
        if result is not None:
            results.append(result)
    return sorted(results, key=lambda r: r.confidence, reverse=True)
