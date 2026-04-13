import numpy as np
import pytest
from patterns.channel import ChannelDetector
from patterns.base import PatternResult


def _linear_prices(n: int = 60, slope: float = 0.1, start: float = 100.0) -> list[float]:
    """Pure linear prices → highs and lows both perfectly linear (R²≈1)."""
    return [start + i * slope for i in range(n)]


# A gently rising straight line — all 4 conditions should be met
VALID_PRICES = _linear_prices(n=60, slope=0.1, start=100.0)


class TestChannelDetector:

    def test_detects_valid_channel(self, make_ohlcv):
        """A perfectly linear price series forms a channel with confidence=1.0."""
        df = make_ohlcv(VALID_PRICES)
        result = ChannelDetector().detect(df, "TEST")

        assert result is not None
        assert isinstance(result, PatternResult)
        assert result.pattern == "channel"
        assert result.ticker == "TEST"
        assert result.confidence > 0.5

    def test_returns_pattern_result_not_dict(self, make_ohlcv):
        """When a pattern is found, must return PatternResult not a dict."""
        df = make_ohlcv(VALID_PRICES)
        result = ChannelDetector().detect(df, "TEST")
        if result is not None:
            assert type(result) is PatternResult

    def test_pivots_contain_channel_top_and_bottom(self, make_ohlcv):
        """Pivots must contain channel_top and channel_bottom."""
        df = make_ohlcv(VALID_PRICES)
        result = ChannelDetector().detect(df, "TEST")
        if result is not None:
            assert "channel_top" in result.pivots
            assert "channel_bottom" in result.pivots
            assert "channel_top" in result.pivot_dates
            assert "channel_bottom" in result.pivot_dates

    def test_metadata_contains_required_fields(self, make_ohlcv):
        """Metadata must include upper_slope, lower_slope, channel_width_pct, price_position_pct."""
        df = make_ohlcv(VALID_PRICES)
        result = ChannelDetector().detect(df, "TEST")
        if result is not None:
            for key in ("upper_slope", "lower_slope", "channel_width_pct", "price_position_pct"):
                assert key in result.metadata, f"missing metadata key: {key}"

    def test_detected_on_is_last_bar_date(self, make_ohlcv):
        """detected_on must equal the date of the last bar in df."""
        df = make_ohlcv(VALID_PRICES)
        result = ChannelDetector().detect(df, "TEST")
        if result is not None:
            assert result.detected_on == df.index[-1].date()

    def test_confidence_in_unit_interval(self, make_ohlcv):
        """Confidence must be in [0.0, 1.0]."""
        df = make_ohlcv(VALID_PRICES)
        result = ChannelDetector().detect(df, "TEST")
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0

    def test_returns_none_for_short_df(self, make_ohlcv):
        """Returns None when df has fewer than 20 rows (minimum lookback)."""
        df = make_ohlcv([100.0] * 10)
        result = ChannelDetector().detect(df, "TEST")
        assert result is None

    def test_channel_top_above_channel_bottom(self, make_ohlcv):
        """channel_top must always be greater than channel_bottom."""
        df = make_ohlcv(VALID_PRICES)
        result = ChannelDetector().detect(df, "TEST")
        if result is not None:
            assert result.pivots["channel_top"] > result.pivots["channel_bottom"]

    def test_wide_channel_fails_width_condition(self, make_ohlcv):
        """A channel wider than 20% of price should fail condition 3."""
        # Prices with high amplitude oscillation → wide channel
        prices = [100.0 + 15.0 * ((-1) ** i) for i in range(60)]
        df = make_ohlcv(prices)
        result = ChannelDetector().detect(df, "TEST")
        if result is not None:
            assert result.confidence < 1.0

    def test_no_network_calls(self, make_ohlcv, monkeypatch):
        """Detector must not make any network calls."""
        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network call")),
        )
        df = make_ohlcv(VALID_PRICES)
        ChannelDetector().detect(df, "TEST")
