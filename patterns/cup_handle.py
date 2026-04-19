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
_RIGHT_RECOVERY_MAX = 0.05   # right_high within 5% below left_high
_RIGHT_OVERSHOOT_MAX = 0.0   # post-breakout highs above left_high are not the handle high
_HANDLE_DEPTH_IDEAL = 0.12   # IBD: most strong handles are <= 12%
_HANDLE_DEPTH_MAX = 0.15     # IBD daily-chart hard cap for normal markets
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

        cup_depth = cup_depth_abs / left_high_price
        c1 = _CUP_DEPTH_MIN <= cup_depth <= _CUP_DEPTH_MAX
        cup_threshold = cup_low_price * (1 + _CUP_BOTTOM_BAND_PCT)
        current_bottom_mask = closes[left_high_idx:] <= cup_threshold
        c2_current = int(np.sum(current_bottom_mask)) >= _CUP_BOTTOM_MIN_DAYS
        if not (c1 and c2_current):
            return None

        # --- Scan all right_high candidates in the recovery zone ---
        # The right lip must be near the old high, but not above it. Bars above
        # the left lip are post-breakout action, not the pre-breakout handle high.
        handle_search_start = cup_low_idx + 1
        handle_search_end = len(closes)
        if handle_search_end <= handle_search_start:
            return None

        recovery_segment = closes[handle_search_start:handle_search_end]
        recovery_from_left = (left_high_price - recovery_segment) / left_high_price
        candidate_mask = (
            (recovery_from_left >= -_RIGHT_OVERSHOOT_MAX)
            & (recovery_from_left <= _RIGHT_RECOVERY_MAX)
        )
        candidate_rel_indices = np.where(candidate_mask)[0]
        if len(candidate_rel_indices) == 0:
            latest_above_low = closes[-1] > cup_low_price
            if latest_above_low:
                return PatternResult(
                    pattern="cup_handle",
                    ticker=ticker,
                    confidence=0.5,
                    detected_on=dates[-1].date(),
                    pivots={
                        "left_high": float(left_high_price),
                        "cup_low": float(cup_low_price),
                    },
                    pivot_dates={
                        "left_high": dates[left_high_idx].date(),
                        "cup_low": dates[cup_low_idx].date(),
                    },
                    metadata={
                        "state": "cup_forming",
                        "actionable": False,
                        "cup_depth_pct": float(cup_depth),
                    },
                )
            return None

        best_key: tuple | None = None
        best: tuple | None = None
        fallback_key: tuple | None = None
        fallback: tuple | None = None

        for rel_idx in candidate_rel_indices:  # earliest -> latest
            rh_idx = handle_search_start + int(rel_idx)
            rh_price = float(closes[rh_idx])
            cup_bottom_mask = closes[left_high_idx:rh_idx + 1] <= cup_threshold
            c2 = int(np.sum(cup_bottom_mask)) >= _CUP_BOTTOM_MIN_DAYS
            c3_recovery = (left_high_price - rh_price) / left_high_price
            c3 = -_RIGHT_OVERSHOOT_MAX <= c3_recovery <= _RIGHT_RECOVERY_MAX
            if not (c2 and c3):
                continue

            h_start = rh_idx + 1
            raw_h_end = min(len(closes), h_start + _HANDLE_MAX_DAYS)
            breakout_idx = None
            for idx in range(h_start + _HANDLE_MIN_DAYS, raw_h_end):
                if closes[idx] > rh_price:
                    breakout_idx = idx
                    break

            if breakout_idx is not None:
                h_end = breakout_idx
                state = "complete"
            else:
                h_end = raw_h_end
                state = "handle_forming"

            h_prices = closes[h_start:h_end]
            h_vols = volumes[h_start:h_end]
            h_dur = len(h_prices)
            base_mid = (left_high_price + cup_low_price) / 2

            current_fallback_key = (
                -abs((left_high_price - rh_price) / left_high_price),
                -rh_idx,
            )
            if h_dur == 0:
                if state == "handle_forming" and (
                    fallback is None or current_fallback_key > fallback_key
                ):
                    fallback_key = current_fallback_key
                    fallback = (rh_idx, rh_price, None, None)
                continue

            h_low_rel = int(np.argmin(h_prices))
            h_low = float(h_prices[h_low_rel])
            h_low_idx = h_start + h_low_rel
            h_decline = rh_price - h_low
            midpoint_ok = (rh_price + h_low) / 2 > base_mid

            if state == "handle_forming" and midpoint_ok and (
                fallback is None or current_fallback_key > fallback_key
            ):
                fallback_key = current_fallback_key
                fallback = (rh_idx, rh_price, h_low, h_low_idx)

            # Handle must pull back; breakout bars have h_low > rh_price.
            if h_decline <= 0:
                continue

            handle_depth_pct = h_decline / rh_price if rh_price > 0 else 1.0
            c4 = handle_depth_pct <= _HANDLE_DEPTH_MAX
            ideal_handle_depth = handle_depth_pct <= _HANDLE_DEPTH_IDEAL
            c5 = _HANDLE_MIN_DAYS <= h_dur <= _HANDLE_MAX_DAYS

            c6 = False
            if len(h_vols) >= 5:
                vol_sma = pd.Series(h_vols, dtype=float).rolling(5).mean().dropna().values
                if len(vol_sma) >= 2:
                    c6 = np.polyfit(np.arange(len(vol_sma)), vol_sma, 1)[0] < 0

            c7 = midpoint_ok

            if not (c4 and c5 and c7):
                continue

            score = sum([c4, c5, c6, c7])
            candidate_key = (
                score,
                1 if ideal_handle_depth else 0,
                -abs((left_high_price - rh_price) / left_high_price),
                -rh_idx,
            )
            if best is None or candidate_key > best_key:
                best_key = candidate_key
                best = (
                    rh_idx, rh_price, h_low, h_low_rel, h_dur, h_start,
                    c2, c4, c5, c6, c7, handle_depth_pct, state, breakout_idx
                )

        if best is None:
            if fallback is None:
                return None
            fallback_rh_idx, fallback_rh_price, fallback_handle_low, fallback_handle_low_idx = fallback
            pivots = {
                "left_high": float(left_high_price),
                "cup_low": float(cup_low_price),
                "right_high": float(fallback_rh_price),
                "handle_high": float(fallback_rh_price),
            }
            pivot_dates = {
                "left_high": dates[left_high_idx].date(),
                "cup_low": dates[cup_low_idx].date(),
                "right_high": dates[fallback_rh_idx].date(),
                "handle_high": dates[fallback_rh_idx].date(),
            }
            if fallback_handle_low is not None and fallback_handle_low_idx is not None:
                pivots["handle_low"] = float(fallback_handle_low)
                pivot_dates["handle_low"] = dates[fallback_handle_low_idx].date()
            return PatternResult(
                pattern="cup_handle",
                ticker=ticker,
                confidence=0.6,
                detected_on=dates[-1].date(),
                pivots=pivots,
                pivot_dates=pivot_dates,
                metadata={
                    "state": "handle_forming",
                    "actionable": False,
                    "cup_depth_pct": float(cup_depth),
                },
            )

        (right_high_idx, right_high_price, handle_low_price,
         handle_low_rel, handle_duration, handle_start_idx,
         c2, c4, c5, c6, c7, handle_depth_pct, state, breakout_idx) = best

        # --- Evaluate cup conditions ---
        c3_recovery = (left_high_price - right_high_price) / left_high_price
        c3 = -_RIGHT_OVERSHOOT_MAX <= c3_recovery <= _RIGHT_RECOVERY_MAX

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
        if breakout_idx is not None:
            pivots["breakout"] = float(closes[breakout_idx])
            pivot_dates["breakout"] = dates[breakout_idx].date()

        return PatternResult(
            pattern="cup_handle",
            ticker=ticker,
            confidence=confidence,
            detected_on=dates[-1].date(),
            pivots=pivots,
            pivot_dates=pivot_dates,
            metadata={
                "state": state,
                "actionable": True,
                "cup_depth_pct": float(cup_depth),
                "handle_depth_pct": float(handle_depth_pct),
                "handle_duration_bdays": int(handle_duration),
            },
        )
