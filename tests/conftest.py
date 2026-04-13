import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def make_ohlcv():
    def _make(prices: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
        """Deterministic OHLCV DataFrame. Highs = close*1.005, Lows = close*0.995."""
        closes = np.array(prices, dtype=float)
        highs = closes * 1.005
        lows = closes * 0.995
        opens = np.roll(closes, 1)
        opens[0] = closes[0]
        vols = np.array(volumes if volumes else [1_000_000] * len(closes), dtype=int)
        dates = pd.date_range("2025-01-01", periods=len(closes), freq="B")
        return pd.DataFrame(
            {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
            index=dates,
        )

    return _make
