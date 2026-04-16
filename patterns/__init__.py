import pandas as pd

from patterns.base import PatternResult


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
