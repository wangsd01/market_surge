import logging
import numpy as np
import pandas as pd
from datetime import date

from patterns.base import PatternDetector, PatternResult

logger = logging.getLogger(__name__)

# Lookback window bounds (trading days from end of df)
_LOOKBACK_MIN = 45
_LOOKBACK_MAX = 65

# Condition thresholds
_CUP_DEPTH_MIN = 0.12
_CUP_DEPTH_MAX = 0.33
_CUP_BOTTOM_MIN_DAYS = 10
_CUP_BOTTOM_BAND_PCT = 0.10
_RIGHT_RECOVERY_MAX = 0.05   # right_high within 5% of left_high
_HANDLE_RETRACE_MAX = 0.50   # handle decline ≤ 50% of cup depth
_HANDLE_MIN_DAYS = 5
_HANDLE_MAX_DAYS = 30


class CupHandleDetector(PatternDetector):
    """Detect cup-with-handle pattern in OHLCV data."""

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        """Return PatternResult if a cup-with-handle is present, else None.

        df must have DatetimeIndex and columns [Open, High, Low, Close, Volume].
        Only the final _LOOKBACK_MAX rows are examined.
        """
        if len(df) < _LOOKBACK_MIN:
            return None

        # Slice to the lookback window
        lookback = min(len(df), _LOOKBACK_MAX)
        window = df.iloc[-lookback:]
        closes = window["Close"].values
        highs = window["High"].values
        volumes = window["Volume"].values
        dates = window.index

        # --- Locate left_high: highest close in first 2/3 of window ---
        search_end = len(closes) * 2 // 3
        left_high_idx = int(np.argmax(closes[:search_end]))
        left_high_price = closes[left_high_idx]

        # Need enough room after left_high for cup + handle
        if left_high_idx >= len(closes) - _HANDLE_MIN_DAYS - _CUP_BOTTOM_MIN_DAYS:
            return None

        # --- Locate cup_low: minimum close after left_high ---
        after_left = closes[left_high_idx:]
        cup_low_rel = int(np.argmin(after_left))
        cup_low_idx = left_high_idx + cup_low_rel
        cup_low_price = closes[cup_low_idx]

        # --- Locate right_high: highest close after cup_low (before handle) ---
        # Handle occupies the last _HANDLE_MIN_DAYS.._HANDLE_MAX_DAYS of the window
        # Leave room for handle; right_high is in the band after cup_low
        handle_search_start = cup_low_idx + 1
        handle_search_end = len(closes) - _HANDLE_MIN_DAYS
        if handle_search_end <= handle_search_start:
            return None

        recovery_segment = closes[handle_search_start:handle_search_end]
        if len(recovery_segment) == 0:
            return None

        right_high_candidates = np.where(recovery_segment == recovery_segment.max())[0]
        right_high_rel = int(right_high_candidates[-1])
        right_high_idx = handle_search_start + right_high_rel
        right_high_price = closes[right_high_idx]

        # Cup must have at least _CUP_BOTTOM_MIN_DAYS of width — find the span
        # where price is within 5% above cup_low across the rounded bottom.
        cup_threshold = cup_low_price * (1 + _CUP_BOTTOM_BAND_PCT)
        bottom_mask = closes[left_high_idx:right_high_idx + 1] <= cup_threshold
        bottom_span = int(np.sum(bottom_mask))

        # --- Locate handle: segment after right_high to end ---
        handle_start_idx = right_high_idx + 1
        handle_prices = closes[handle_start_idx:]
        handle_vols = volumes[handle_start_idx:]
        handle_duration = len(handle_prices)

        if handle_duration < _HANDLE_MIN_DAYS:
            return None

        handle_low_rel = int(np.argmin(handle_prices))
        handle_low_price = handle_prices[handle_low_rel]
        handle_high_price = right_high_price  # handle starts at right_high

        # ---- Evaluate the 6 conditions ----
        cup_depth = (left_high_price - cup_low_price) / left_high_price

        # 1. Cup depth between 15% and 35%
        c1 = _CUP_DEPTH_MIN <= cup_depth <= _CUP_DEPTH_MAX

        # 2. Cup bottom spans ≥ 10 days (not V-shape)
        c2 = bottom_span >= _CUP_BOTTOM_MIN_DAYS

        # 3. Right side recovery within 5% of left_high
        c3 = (left_high_price - right_high_price) / left_high_price <= _RIGHT_RECOVERY_MAX

        # 4. Handle retracement ≤ 50% of cup depth
        handle_decline = right_high_price - handle_low_price
        cup_depth_abs = left_high_price - cup_low_price
        c4 = (handle_decline / cup_depth_abs) <= _HANDLE_RETRACE_MAX if cup_depth_abs > 0 else False

        # 5. Handle duration 5–15 days
        c5 = _HANDLE_MIN_DAYS <= handle_duration <= _HANDLE_MAX_DAYS

        # 6. Volume contraction: slope of 5-day vol SMA during handle is negative
        c6 = False
        if len(handle_vols) >= 5:
            vol_sma = pd.Series(handle_vols, dtype=float).rolling(5).mean().dropna().values
            if len(vol_sma) >= 2:
                slope = np.polyfit(np.arange(len(vol_sma)), vol_sma, 1)[0]
                c6 = slope < 0

        # 7. Handle must form in the upper half of the base.
        base_midpoint = (left_high_price + cup_low_price) / 2
        handle_midpoint = (handle_high_price + handle_low_price) / 2
        c7 = handle_midpoint > base_midpoint

        conditions_met = sum([c1, c2, c3, c4, c5, c6, c7])
        confidence = conditions_met / 7

        # These are structural requirements for a valid cup-with-handle.
        if not (c1 and c2 and c3 and c4 and c5 and c7):
            return None

        # Build pivot dicts
        pivots: dict[str, float] = {
            "left_high": float(left_high_price),
            "cup_low": float(cup_low_price),
            "right_high": float(right_high_price),
            "handle_low": float(handle_low_price),
            "handle_high": float(handle_high_price),
        }
        pivot_dates: dict[str, date] = {
            "left_high": dates[left_high_idx].date(),
            "cup_low": dates[cup_low_idx].date(),
            "right_high": dates[right_high_idx].date(),
            "handle_low": dates[handle_start_idx + handle_low_rel].date(),
            "handle_high": dates[right_high_idx].date(),
        }

        return PatternResult(
            pattern="cup_handle",
            ticker=ticker,
            confidence=confidence,
            detected_on=dates[-1].date(),
            pivots=pivots,
            pivot_dates=pivot_dates,
        )
