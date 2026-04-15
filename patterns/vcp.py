import logging
import numpy as np
import pandas as pd
from datetime import date
from scipy.signal import argrelextrema

from patterns.base import PatternDetector, PatternResult

logger = logging.getLogger(__name__)

_MIN_ROWS = 30            # minimum df length to attempt detection
_SWING_MIN_PCT = 0.02     # ignore swings smaller than 2%
_CYCLES_MIN = 2
_CYCLES_MAX = 6
_SHORT_SMA_PERIOD = 50
_LONG_SMA_PERIOD = 150


class VCPDetector(PatternDetector):
    """Detect Volatility Contraction Pattern (VCP) in OHLCV data."""

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        if len(df) < _MIN_ROWS:
            return None

        closes = df["Close"].values.astype(float)
        volumes = df["Volume"].values.astype(float)
        dates = df.index
        n = len(closes)

        # --- Locate local highs and lows (order=5) ---
        high_idxs = argrelextrema(closes, np.greater, order=5)[0]
        low_idxs = argrelextrema(closes, np.less, order=5)[0]

        if len(high_idxs) < 2 or len(low_idxs) < 1:
            return None

        # Build an ordered sequence of alternating pivots (high, low, high, low, ...)
        # Start from the first high, then interleave lows between consecutive highs.
        pivots: list[tuple[str, int, float]] = []  # (kind, idx, price)
        all_pivots = (
            [("high", i, closes[i]) for i in high_idxs]
            + [("low", i, closes[i]) for i in low_idxs]
        )
        all_pivots.sort(key=lambda x: x[1])  # chronological order

        # Enforce strict alternation starting from first high
        filtered: list[tuple[str, int, float]] = []
        expecting = "high"
        for kind, idx, price in all_pivots:
            if kind == expecting:
                filtered.append((kind, idx, price))
                expecting = "low" if expecting == "high" else "high"
            else:
                # Replace last entry if same type and this is more extreme
                if filtered and filtered[-1][0] == kind:
                    if (kind == "high" and price > filtered[-1][2]) or \
                       (kind == "low" and price < filtered[-1][2]):
                        filtered[-1] = (kind, idx, price)

        # Ensure sequence starts with high
        while filtered and filtered[0][0] != "high":
            filtered.pop(0)

        # Extract complete (high, low) cycles
        cycles: list[tuple[tuple[str, int, float], tuple[str, int, float]]] = []
        i = 0
        while i + 1 < len(filtered):
            if filtered[i][0] == "high" and filtered[i + 1][0] == "low":
                cycles.append((filtered[i], filtered[i + 1]))
            i += 1

        # Filter cycles with swing ≥ 2%
        valid_cycles = [
            (h, l) for h, l in cycles
            if (h[2] - l[2]) / h[2] >= _SWING_MIN_PCT
        ]

        if len(valid_cycles) < _CYCLES_MIN or len(valid_cycles) > _CYCLES_MAX:
            return None

        # Only keep the most recent _CYCLES_MAX cycles
        valid_cycles = valid_cycles[-_CYCLES_MAX:]

        # --- Condition 1: 3–5 contraction cycles (guaranteed by filtering above) ---
        c1 = _CYCLES_MIN <= len(valid_cycles) <= _CYCLES_MAX

        # --- Condition 2: Each decline smaller than prior ---
        declines = [(h[2] - l[2]) / h[2] for h, l in valid_cycles]
        c2 = all(declines[i] > declines[i + 1] for i in range(len(declines) - 1))

        # --- Condition 3: Each recovery smaller than prior ---
        # Recovery = (next_high - low) / low
        recoveries = []
        for j in range(len(valid_cycles) - 1):
            _, l_curr = valid_cycles[j]
            h_next, _ = valid_cycles[j + 1]
            rec = (h_next[2] - l_curr[2]) / l_curr[2]
            recoveries.append(rec)
        c3 = all(recoveries[i] > recoveries[i + 1] for i in range(len(recoveries) - 1)) \
            if len(recoveries) >= 2 else True

        # --- Condition 4: Broader uptrend / near-high context (skip if df < 150 days) ---
        if n >= _LONG_SMA_PERIOD:
            series = pd.Series(closes)
            sma50 = series.rolling(_SHORT_SMA_PERIOD).mean().values
            sma150 = series.rolling(_LONG_SMA_PERIOD).mean().values
            latest_close = closes[-1]
            latest_sma50 = sma50[-1]
            latest_sma150 = sma150[-1]
            range_high = float(np.max(closes))
            range_low = float(np.min(closes))
            c4 = bool(
                latest_close >= latest_sma50
                and latest_close >= latest_sma150
                and latest_sma50 >= latest_sma150
                and latest_close >= 0.75 * range_high
                and latest_close >= 1.30 * range_low
            )
        else:
            c4 = True  # condition skipped for short series

        # --- Condition 5: Volume declining with each contraction ---
        def _avg_vol_in_range(start: int, end: int) -> float:
            return float(np.mean(volumes[start:end + 1]))

        if len(valid_cycles) >= 2:
            cycle_vols = [
                _avg_vol_in_range(h[1], l[1]) for h, l in valid_cycles
            ]
            c5 = all(cycle_vols[i] > cycle_vols[i + 1] for i in range(len(cycle_vols) - 1))
        else:
            c5 = False

        conditions_met = sum([c1, c2, c3, c4, c5])
        confidence = conditions_met / 5

        if not (c1 and c2 and c4 and c5):
            return None

        # --- Build pivot dicts ---
        pivot_prices: dict[str, float] = {}
        pivot_dates_map: dict[str, date] = {}
        for j, (h, l) in enumerate(valid_cycles, start=1):
            pivot_prices[f"high_{j}"] = float(h[2])
            pivot_prices[f"low_{j}"] = float(l[2])
            pivot_dates_map[f"high_{j}"] = dates[h[1]].date()
            pivot_dates_map[f"low_{j}"] = dates[l[1]].date()

        return PatternResult(
            pattern="vcp",
            ticker=ticker,
            confidence=confidence,
            detected_on=dates[-1].date(),
            pivots=pivot_prices,
            pivot_dates=pivot_dates_map,
        )
