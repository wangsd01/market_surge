import numpy as np

from patterns.base import PatternResult
from patterns.flat_base import FlatBaseDetector


def _make_valid_flat_base_prices() -> list[float]:
    prior_uptrend = list(np.linspace(80, 100, 20))
    flat_base = [
        100.0, 99.0, 98.0, 97.0, 96.0,
        95.0, 94.0, 93.0, 92.5, 93.0,
        93.5, 94.0, 94.5, 95.0, 95.5,
        96.0, 96.5, 97.0, 97.5, 98.0,
        98.5, 99.0, 99.2, 99.4, 99.6,
        99.7, 99.8, 99.9, 99.7, 99.8,
    ]
    return prior_uptrend + flat_base


VALID_PRICES = _make_valid_flat_base_prices()
VALID_VOLUMES = [1_200_000] * 20 + [1_000_000] * 15 + [800_000] * 15


class TestFlatBaseDetector:
    def test_detects_valid_flat_base(self, make_ohlcv):
        """A shallow 6-week sideways consolidation after an uptrend should qualify."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = FlatBaseDetector().detect(df, "TEST")

        assert result is not None
        assert isinstance(result, PatternResult)
        assert result.pattern == "flat_base"
        assert result.ticker == "TEST"
        assert result.confidence > 0.5

    def test_pivots_contain_base_high_and_low(self, make_ohlcv):
        """PatternResult.pivots must contain base_high and base_low."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = FlatBaseDetector().detect(df, "TEST")

        assert result is not None
        assert {"base_high", "base_low"}.issubset(result.pivots.keys())
        assert {"base_high", "base_low"}.issubset(result.pivot_dates.keys())

    def test_returns_none_for_short_df(self, make_ohlcv):
        """A flat base needs enough data for the prior uptrend plus the base."""
        df = make_ohlcv([100.0] * 30)
        result = FlatBaseDetector().detect(df, "TEST")

        assert result is None

    def test_rejects_base_deeper_than_fifteen_percent(self, make_ohlcv):
        """A drop of 16%+ should not be classified as a flat base."""
        prices = list(np.linspace(80, 100, 20)) + [
            100.0, 99.0, 98.0, 96.0, 94.0,
            92.0, 90.0, 88.0, 86.0, 84.0,
            85.0, 86.0, 87.0, 88.0, 89.0,
            90.0, 91.0, 92.0, 93.0, 94.0,
            95.0, 96.0, 97.0, 98.0, 99.0,
        ]
        df = make_ohlcv(prices)

        result = FlatBaseDetector().detect(df, "TEST")

        assert result is None

    def test_requires_prior_uptrend(self, make_ohlcv):
        """Sideways action without a meaningful prior advance is not a flat base."""
        prices = [90.0] * 20 + [
            100.0, 99.0, 98.0, 97.0, 96.0,
            95.0, 94.0, 93.0, 92.5, 93.0,
            93.5, 94.0, 94.5, 95.0, 95.5,
            96.0, 96.5, 97.0, 97.5, 98.0,
            98.5, 99.0, 99.2, 99.4, 99.6,
            99.7, 99.8, 99.9, 99.7, 99.8,
        ]
        df = make_ohlcv(prices)

        result = FlatBaseDetector().detect(df, "TEST")

        assert result is None

    def test_requires_sideways_action_not_fresh_uptrend(self, make_ohlcv):
        """A continued climb should not be labeled a flat base."""
        prices = list(np.linspace(80, 100, 20)) + list(np.linspace(100, 115, 30))
        df = make_ohlcv(prices)

        result = FlatBaseDetector().detect(df, "TEST")

        assert result is None
