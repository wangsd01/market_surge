import logging
import numpy as np
import pandas as pd
from datetime import date
from scipy.signal import argrelextrema

from patterns.base import PatternDetector, PatternResult

logger = logging.getLogger(__name__)

_CLUSTER_TOL = 0.01    # merge levels within 1% of each other
_TOP_N = 5             # return up to 5 levels
_MIN_CONFIDENCE_LEVELS = 3


class SupportResistanceDetector(PatternDetector):
    """Detect support and resistance price levels via pivot clustering.

    Unlike other detectors, this always returns a PatternResult.
    Confidence = 1.0 if ≥ 3 levels found, else levels_found / 3.
    """

    def detect(self, df: pd.DataFrame, ticker: str) -> PatternResult | None:
        highs = df["High"].values.astype(float)
        lows = df["Low"].values.astype(float)
        closes = df["Close"].values.astype(float)
        dates = df.index
        n = len(df)

        current_price = float(closes[-1])
        last_date = dates[-1].date()

        # --- Step 1: Find local maxima in highs and minima in lows ---
        order = 5
        if n < order * 2 + 1:
            order = max(1, n // 4)

        high_idxs = argrelextrema(highs, np.greater, order=order)[0]
        low_idxs = argrelextrema(lows, np.less, order=order)[0]

        # Collect all pivot prices with their index (for recency scoring)
        raw_pivots: list[tuple[int, float]] = (
            [(i, highs[i]) for i in high_idxs]
            + [(i, lows[i]) for i in low_idxs]
        )

        if not raw_pivots:
            return PatternResult(
                pattern="support_resistance",
                ticker=ticker,
                confidence=0.0,
                detected_on=last_date,
                pivots={},
                pivot_dates={},
                metadata={},
            )

        # --- Step 2: Cluster levels within 1% of each other ---
        raw_pivots.sort(key=lambda x: x[1])  # sort by price
        clusters: list[list[tuple[int, float]]] = []
        current_cluster: list[tuple[int, float]] = [raw_pivots[0]]

        for idx, price in raw_pivots[1:]:
            cluster_price = np.mean([p for _, p in current_cluster])
            if abs(price - cluster_price) / cluster_price <= _CLUSTER_TOL:
                current_cluster.append((idx, price))
            else:
                clusters.append(current_cluster)
                current_cluster = [(idx, price)]
        clusters.append(current_cluster)

        # --- Step 3: Score each cluster ---
        def _score(cluster: list[tuple[int, float]]) -> float:
            touches = len(cluster)
            # Recency weight: most recent index / n normalised to [0, 1]
            recency = max(i for i, _ in cluster) / n
            return float(touches + recency)

        scored = [(cluster, _score(cluster)) for cluster in clusters]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_clusters = scored[:_TOP_N]

        # --- Step 4: Build PatternResult ---
        pivots: dict[str, float] = {}
        pivot_dates_map: dict[str, date] = {}
        metadata: dict = {}

        for rank, (cluster, _) in enumerate(top_clusters, start=1):
            level_price = float(np.average([p for _, p in cluster]))
            most_recent_idx = max(i for i, _ in cluster)
            level_type = "support" if level_price < current_price else "resistance"

            pivots[f"level_{rank}"] = level_price
            pivot_dates_map[f"level_{rank}"] = dates[most_recent_idx].date()
            metadata[f"type_{rank}"] = level_type
            metadata[f"touch_count_{rank}"] = len(cluster)

        levels_found = len(top_clusters)
        confidence = 1.0 if levels_found >= _MIN_CONFIDENCE_LEVELS else levels_found / _MIN_CONFIDENCE_LEVELS

        return PatternResult(
            pattern="support_resistance",
            ticker=ticker,
            confidence=confidence,
            detected_on=last_date,
            pivots=pivots,
            pivot_dates=pivot_dates_map,
            metadata=metadata,
        )
