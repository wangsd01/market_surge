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

        lookback = min(len(df), _LOOKBACK_MAX)
        window = df.iloc[-lookback:]
        closes = window["Close"].values
        volumes = window["Volume"].values
        dates = window.index

        # --- left_high: highest close in first 2/3 of window ---
        search_end = len(closes) * 2 // 3
        left_high_idx = int(np.argmax(closes[:search_end]))
        left_high_price = closes[left_high_idx]

        if left_high_idx >= len(closes) - _HANDLE_MIN_DAYS - _CUP_BOTTOM_MIN_DAYS:
            return None

        # --- cup_low: minimum close after left_high ---
        after_left = closes[left_high_idx:]
        cup_low_rel = int(np.argmin(after_left))
        cup_low_idx = left_high_idx + cup_low_rel
        cup_low_price = closes[cup_low_idx]

        cup_depth_abs = left_high_price - cup_low_price
        if cup_depth_abs <= 0:
            return None

        # --- Scan all right_high candidates in the recovery zone ---
        # Any bar within RIGHT_RECOVERY_MAX of left_high is a valid right lip candidate.
        # Iterating earliest → latest and keeping only strict improvements naturally
        # selects the real cup right lip over later breakout bars with the same score.
        handle_search_start = cup_low_idx + 1
        handle_search_end = len(closes) - _HANDLE_MIN_DAYS
        if handle_search_end <= handle_search_start:
            return None

        recovery_segment = closes[handle_search_start:handle_search_end]
        candidate_mask = (
            (left_high_price - recovery_segment) / left_high_price <= _RIGHT_RECOVERY_MAX
        )
        candidate_rel_indices = np.where(candidate_mask)[0]
        if len(candidate_rel_indices) == 0:
            return None

        best_score = -1
        best_rh_price = -1.0
        best: tuple | None = None

        for rel_idx in candidate_rel_indices:  # earliest → latest
            rh_idx = handle_search_start + int(rel_idx)
            rh_price = float(closes[rh_idx])

            # Cap handle window: do not look past HANDLE_MAX bars after right_high.
            # This prevents post-handle breakout data from entering the handle.
            h_start = rh_idx + 1
            h_end = min(len(closes), h_start + _HANDLE_MAX_DAYS)
            h_prices = closes[h_start:h_end]
            h_vols = volumes[h_start:h_end]
            h_dur = len(h_prices)

            if h_dur < _HANDLE_MIN_DAYS:
                continue

            h_low_rel = int(np.argmin(h_prices))
            h_low = float(h_prices[h_low_rel])
            h_decline = rh_price - h_low

            # Handle must pull back (breakout bars have h_low > rh_price → negative decline)
            if h_decline <= 0:
                continue

            c4 = (h_decline / cup_depth_abs) <= _HANDLE_RETRACE_MAX
            c5 = _HANDLE_MIN_DAYS <= h_dur <= _HANDLE_MAX_DAYS

            c6 = False
            if len(h_vols) >= 5:
                vol_sma = pd.Series(h_vols, dtype=float).rolling(5).mean().dropna().values
                if len(vol_sma) >= 2:
                    c6 = np.polyfit(np.arange(len(vol_sma)), vol_sma, 1)[0] < 0

            base_mid = (left_high_price + cup_low_price) / 2
            c7 = (rh_price + h_low) / 2 > base_mid

            if not (c4 and c5 and c7):
                continue

            score = sum([c4, c5, c6, c7])
            # Among equal scores, prefer the highest rh_price (true right-lip peak).
            if (score, rh_price) > (best_score, best_rh_price):
                best_score = score
                best_rh_price = rh_price
                best = (rh_idx, rh_price, h_low, h_low_rel, h_dur, h_start, c4, c5, c6, c7)

        if best is None:
            return None

        (right_high_idx, right_high_price, handle_low_price,
         handle_low_rel, handle_duration, handle_start_idx,
         c4, c5, c6, c7) = best

        # --- Evaluate cup conditions ---
        cup_depth = cup_depth_abs / left_high_price
        c1 = _CUP_DEPTH_MIN <= cup_depth <= _CUP_DEPTH_MAX

        cup_threshold = cup_low_price * (1 + _CUP_BOTTOM_BAND_PCT)
        bottom_mask = closes[left_high_idx:right_high_idx + 1] <= cup_threshold
        c2 = int(np.sum(bottom_mask)) >= _CUP_BOTTOM_MIN_DAYS

        c3 = (left_high_price - right_high_price) / left_high_price <= _RIGHT_RECOVERY_MAX

        conditions_met = sum([c1, c2, c3, c4, c5, c6, c7])
        confidence = conditions_met / 7

        if not (c1 and c2 and c3 and c4 and c5 and c7):
            return None

        pivots: dict[str, float] = {
            "left_high": float(left_high_price),
            "cup_low": float(cup_low_price),
            "right_high": float(right_high_price),
            "handle_low": float(handle_low_price),
            "handle_high": float(right_high_price),
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
