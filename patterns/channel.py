import logging
import numpy as np
import pandas as pd
from datetime import date
from scipy.stats import linregress

from patterns.base import PatternDetector, PatternResult

logger = logging.getLogger(__name__)

_LOOKBACK_LONG = 60
_LOOKBACK_SHORT = 20
_R2_THRESHOLD = 0.7
_WIDTH_MAX_PCT = 0.20   # channel width < 20% of mid price


class ChannelDetector(PatternDetector):
    """Detect a price channel (parallel upper/lower linear trend lines)."""

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        if len(df) < _LOOKBACK_SHORT:
            return None

        highs = df["High"].values.astype(float)
        lows = df["Low"].values.astype(float)
        closes = df["Close"].values.astype(float)
        dates = df.index

        # Try 60-day lookback, fall back to 20-day if R² < threshold
        for lookback in (_LOOKBACK_LONG, _LOOKBACK_SHORT):
            if len(df) < lookback:
                continue
            h = highs[-lookback:]
            l = lows[-lookback:]
            c = closes[-lookback:]
            x = np.arange(len(h), dtype=float)

            upper_slope, upper_intercept, upper_r, _, _ = linregress(x, h)
            lower_slope, lower_intercept, lower_r, _, _ = linregress(x, l)

            if upper_r ** 2 >= _R2_THRESHOLD and lower_r ** 2 >= _R2_THRESHOLD:
                break
        else:
            # No lookback window produced adequate R²
            upper_slope, upper_intercept, upper_r, _, _ = linregress(x, h)
            lower_slope, lower_intercept, lower_r, _, _ = linregress(x, l)

        last_x = float(len(h) - 1)
        channel_top = upper_slope * last_x + upper_intercept
        channel_bottom = lower_slope * last_x + lower_intercept
        mid_price = (channel_top + channel_bottom) / 2
        current_close = float(closes[-1])

        # --- Evaluate 4 conditions ---
        # 1. Upper channel R² > 0.7
        c1 = upper_r ** 2 >= _R2_THRESHOLD

        # 2. Lower channel R² > 0.7
        c2 = lower_r ** 2 >= _R2_THRESHOLD

        # 3. Channel width < 20% of price
        channel_width = channel_top - channel_bottom
        channel_width_pct = channel_width / mid_price if mid_price > 0 else float("inf")
        c3 = channel_width_pct < _WIDTH_MAX_PCT

        # 4. Current price between lower and upper channel line
        c4 = channel_bottom <= current_close <= channel_top

        conditions_met = sum([c1, c2, c3, c4])
        confidence = conditions_met / 4

        if confidence < 0.5:
            return None

        # Price position as % within channel (0=bottom, 1=top)
        price_position_pct = (
            (current_close - channel_bottom) / channel_width
            if channel_width > 0 else 0.5
        )

        last_date = dates[-1].date()
        pivots: dict[str, float] = {
            "channel_top": float(channel_top),
            "channel_bottom": float(channel_bottom),
        }
        pivot_dates: dict[str, date] = {
            "channel_top": last_date,
            "channel_bottom": last_date,
        }
        metadata: dict = {
            "upper_slope": float(upper_slope),
            "lower_slope": float(lower_slope),
            "channel_width_pct": float(channel_width_pct),
            "price_position_pct": float(price_position_pct),
        }

        return PatternResult(
            pattern="channel",
            ticker=ticker,
            confidence=confidence,
            detected_on=last_date,
            pivots=pivots,
            pivot_dates=pivot_dates,
            metadata=metadata,
        )
