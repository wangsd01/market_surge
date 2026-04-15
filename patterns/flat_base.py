import numpy as np
import pandas as pd
from datetime import date

from patterns.base import PatternDetector, PatternResult

_MIN_ROWS = 45
_PRIOR_UPTREND_DAYS = 20
_BASE_MIN_DAYS = 25
_BASE_MAX_DAYS = 40
_DEPTH_MAX_PCT = 0.15
_PRIOR_UPTREND_MIN_PCT = 0.20
_TOP_ZONE_MIN_PCT = 0.70
_SIDEWAYS_DRIFT_MAX_PCT = 0.08


class FlatBaseDetector(PatternDetector):
    """Detect a standalone IBD-style flat base."""

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        if len(df) < _MIN_ROWS:
            return None

        closes = df["Close"].values.astype(float)
        volumes = df["Volume"].values.astype(float)
        dates = df.index
        n = len(closes)

        best: PatternResult | None = None
        best_score = -1.0

        max_base_days = min(_BASE_MAX_DAYS, n - _PRIOR_UPTREND_DAYS)
        for base_days in range(_BASE_MIN_DAYS, max_base_days + 1):
            start = n - base_days
            base_closes = closes[start:]
            base_volumes = volumes[start:]
            prior_closes = closes[start - _PRIOR_UPTREND_DAYS:start]

            if len(prior_closes) < _PRIOR_UPTREND_DAYS:
                continue

            base_high_rel = int(np.argmax(base_closes))
            base_low_rel = int(np.argmin(base_closes))
            base_high = float(base_closes[base_high_rel])
            base_low = float(base_closes[base_low_rel])
            base_range = base_high - base_low

            if base_high <= 0:
                continue

            depth_pct = base_range / base_high
            c1 = base_days >= _BASE_MIN_DAYS
            c2 = depth_pct <= _DEPTH_MAX_PCT

            prior_low = float(np.min(prior_closes))
            prior_uptrend_pct = ((base_high - prior_low) / prior_low) if prior_low > 0 else 0.0
            c3 = prior_uptrend_pct >= _PRIOR_UPTREND_MIN_PCT

            last_close = float(base_closes[-1])
            if base_range > 0:
                price_position_pct = (last_close - base_low) / base_range
            else:
                price_position_pct = 1.0
            c4 = price_position_pct >= _TOP_ZONE_MIN_PCT

            first_close = float(base_closes[0])
            sideways_drift_pct = abs(last_close - first_close) / first_close if first_close > 0 else 0.0
            c5 = sideways_drift_pct <= _SIDEWAYS_DRIFT_MAX_PCT

            half = len(base_volumes) // 2
            first_half_vol = float(np.mean(base_volumes[:half])) if half > 0 else float(np.mean(base_volumes))
            second_half_vol = float(np.mean(base_volumes[half:])) if half < len(base_volumes) else first_half_vol
            c6 = second_half_vol <= first_half_vol

            if not (c1 and c2 and c3 and c4 and c5):
                continue

            confidence = sum([c1, c2, c3, c4, c5, c6]) / 6
            score = confidence - depth_pct
            if score <= best_score:
                continue

            pivots = {
                "base_high": base_high,
                "base_low": base_low,
            }
            pivot_dates: dict[str, date] = {
                "base_high": dates[start + base_high_rel].date(),
                "base_low": dates[start + base_low_rel].date(),
            }
            metadata = {
                "base_days": base_days,
                "depth_pct": depth_pct,
                "prior_uptrend_pct": prior_uptrend_pct,
                "price_position_pct": price_position_pct,
            }
            best = PatternResult(
                pattern="flat_base",
                ticker=ticker,
                confidence=confidence,
                detected_on=dates[-1].date(),
                pivots=pivots,
                pivot_dates=pivot_dates,
                metadata=metadata,
            )
            best_score = score

        return best
