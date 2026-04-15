import logging
import numpy as np
import pandas as pd
from datetime import date

from patterns.base import PatternDetector, PatternResult

logger = logging.getLogger(__name__)

_MIN_ROWS = 45

# Condition thresholds
_TROUGH_PRICE_TOL = 0.03   # troughs within 3% of each other
_TROUGH_SEP_MIN = 15       # trading days between trough centres
_TROUGH_SEP_MAX = 50
_MIDDLE_PEAK_MIN = 0.10    # middle peak ≥ 10% above trough avg


def _find_trough(closes: np.ndarray, start: int, end: int) -> int:
    """Return index of minimum close in closes[start:end]."""
    segment = closes[start:end]
    return start + int(np.argmin(segment))


class DoubleBottomDetector(PatternDetector):
    """Detect double-bottom (W-shape) pattern in OHLCV data."""

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        if len(df) < _MIN_ROWS:
            return None

        closes = df["Close"].values
        volumes = df["Volume"].values
        dates = df.index
        n = len(closes)

        best: PatternResult | None = None
        best_confidence = -1.0

        # Search: place first trough anywhere in first 60% of the window,
        # then look for second trough 15–50 days later.
        search_end = int(n * 0.85)  # leave room for second trough + some tail

        for t1_idx in range(5, search_end - _TROUGH_SEP_MIN - 5):
            # First trough is the local minimum in a ±5 window around t1_idx
            lo1 = max(0, t1_idx - 5)
            hi1 = min(n, t1_idx + 6)
            local_t1 = lo1 + int(np.argmin(closes[lo1:hi1]))
            if local_t1 != t1_idx:
                continue  # only process each trough once (at its true minimum)

            t1_price = closes[t1_idx]

            for sep in range(_TROUGH_SEP_MIN, _TROUGH_SEP_MAX + 1):
                t2_idx = t1_idx + sep
                if t2_idx >= n:
                    break

                # Second trough: minimum in ±5 window around candidate
                lo2 = max(t1_idx + 1, t2_idx - 5)
                hi2 = min(n, t2_idx + 6)
                actual_t2 = lo2 + int(np.argmin(closes[lo2:hi2]))
                t2_price = closes[actual_t2]

                # Condition 1: troughs within 3% of each other
                price_diff = abs(t1_price - t2_price) / max(t1_price, t2_price)
                c1 = price_diff <= _TROUGH_PRICE_TOL

                # Condition 2: separation 15–50 days (always true here by construction)
                c2 = True

                # Middle peak: max close between the two troughs
                if actual_t2 <= t1_idx + 1:
                    continue
                mid_segment = closes[t1_idx:actual_t2 + 1]
                mid_peak_rel = int(np.argmax(mid_segment))
                mid_peak_idx = t1_idx + mid_peak_rel
                mid_peak_price = mid_segment[mid_peak_rel]
                avg_trough = (t1_price + t2_price) / 2

                # Condition 3: middle peak ≥ 10% above trough level
                c3 = (mid_peak_price - avg_trough) / avg_trough >= _MIDDLE_PEAK_MIN

                # Condition 4: second trough volume ≤ first trough volume
                def _avg_vol(idx: int) -> float:
                    lo = max(0, idx - 1)
                    hi = min(len(volumes), idx + 2)
                    return float(np.mean(volumes[lo:hi]))

                c4 = _avg_vol(actual_t2) <= _avg_vol(t1_idx)
                c5 = t2_price <= t1_price

                if not (c1 and c3 and c5):
                    continue

                conditions_met = sum([c1, c2, c3, c4, c5])
                confidence = conditions_met / 5

                if confidence > best_confidence:
                    best_confidence = confidence
                    pivots: dict[str, float] = {
                        "first_trough": float(t1_price),
                        "middle_high": float(mid_peak_price),
                        "second_trough": float(t2_price),
                    }
                    pivot_dates: dict[str, date] = {
                        "first_trough": dates[t1_idx].date(),
                        "middle_high": dates[mid_peak_idx].date(),
                        "second_trough": dates[actual_t2].date(),
                    }
                    best = PatternResult(
                        pattern="double_bottom",
                        ticker=ticker,
                        confidence=confidence,
                        detected_on=dates[-1].date(),
                        pivots=pivots,
                        pivot_dates=pivot_dates,
                    )

        if best is None or best.confidence < 0.5:
            return None
        return best
