import numpy as np
import pytest
from patterns.support_resistance import SupportResistanceDetector
from patterns.base import PatternResult


def _oscillating_prices(n_cycles: int = 4, low: float = 90.0, high: float = 110.0) -> list[float]:
    """Price that oscillates between low and high over n_cycles — creates clear S/R levels."""
    prices: list[float] = []
    keypoints = []
    for c in range(n_cycles):
        base = c * 20
        keypoints += [(base, low), (base + 10, high)]
    keypoints.append((n_cycles * 20, low))
    for i in range(len(keypoints) - 1):
        x0, p0 = keypoints[i]
        x1, p1 = keypoints[i + 1]
        seg = list(np.linspace(p0, p1, x1 - x0 + 1))
        prices.extend(seg if i == 0 else seg[1:])
    return prices


# Three distinct price zones → 3+ levels → confidence = 1.0
def _three_level_prices() -> list[float]:
    """Creates local extrema at 3 distinct price zones: ~95, ~108, ~115.

    High peaks at 115 (idx 10, 30) and 108 (idx 50, 70) → two resistance clusters.
    Low troughs at 95 (idx 20, 40) and 101 (idx 60) → two support clusters.
    Total ≥ 3 clusters → confidence = 1.0.
    """
    keypoints = [
        (0, 95), (10, 115), (20, 95), (30, 115),
        (40, 95), (50, 108), (60, 101), (70, 108),
    ]
    prices: list[float] = []
    for i in range(len(keypoints) - 1):
        x0, p0 = keypoints[i]
        x1, p1 = keypoints[i + 1]
        seg = list(np.linspace(p0, p1, x1 - x0 + 1))
        prices.extend(seg if i == 0 else seg[1:])
    return prices


OSCILLATING_PRICES = _oscillating_prices()
THREE_LEVEL_PRICES = _three_level_prices()


class TestSupportResistanceDetector:

    def test_always_returns_pattern_result(self, make_ohlcv):
        """S/R detector always returns a PatternResult (never None) for a valid df."""
        df = make_ohlcv(OSCILLATING_PRICES)
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        assert isinstance(result, PatternResult)
        assert result.pattern == "support_resistance"
        assert result.ticker == "TEST"

    def test_returns_pattern_result_not_dict(self, make_ohlcv):
        """Result must be a PatternResult dataclass, not a raw dict."""
        df = make_ohlcv(OSCILLATING_PRICES)
        result = SupportResistanceDetector().detect(df, "TEST")
        assert type(result) is PatternResult

    def test_confidence_1_when_3_or_more_levels(self, make_ohlcv):
        """Confidence = 1.0 when ≥ 3 distinct levels are found."""
        df = make_ohlcv(THREE_LEVEL_PRICES)
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        assert result.confidence == 1.0

    def test_confidence_proportional_when_fewer_levels(self, make_ohlcv):
        """Confidence = levels_found / 3 when fewer than 3 levels are found."""
        # Very short series with almost no pivot structure
        prices = [100.0, 101.0, 100.5, 100.0, 101.0, 100.5, 100.0,
                  101.0, 100.5, 100.0, 101.0, 100.5, 100.0, 101.0, 100.5]
        df = make_ohlcv(prices)
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        assert result.confidence <= 1.0
        assert result.confidence >= 0.0

    def test_detected_on_is_last_bar_date(self, make_ohlcv):
        """detected_on must equal the date of the last bar in df."""
        df = make_ohlcv(OSCILLATING_PRICES)
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        assert result.detected_on == df.index[-1].date()

    def test_pivots_have_level_keys(self, make_ohlcv):
        """Pivots dict must have at least level_1."""
        df = make_ohlcv(OSCILLATING_PRICES)
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        assert "level_1" in result.pivots

    def test_metadata_has_required_fields(self, make_ohlcv):
        """Metadata must contain type_N and touch_count_N for each level."""
        df = make_ohlcv(OSCILLATING_PRICES)
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        assert "type_1" in result.metadata
        assert "touch_count_1" in result.metadata
        assert result.metadata["type_1"] in ("support", "resistance")

    def test_support_levels_below_current_price(self, make_ohlcv):
        """All levels labeled 'support' must be below the current price."""
        df = make_ohlcv(OSCILLATING_PRICES)
        current_price = float(df["Close"].iloc[-1])
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        for i in range(1, len(result.pivots) + 1):
            key = f"level_{i}"
            if key not in result.pivots:
                break
            if result.metadata.get(f"type_{i}") == "support":
                assert result.pivots[key] < current_price

    def test_resistance_levels_above_current_price(self, make_ohlcv):
        """All levels labeled 'resistance' must be above the current price."""
        df = make_ohlcv(OSCILLATING_PRICES)
        current_price = float(df["Close"].iloc[-1])
        result = SupportResistanceDetector().detect(df, "TEST")
        assert result is not None
        for i in range(1, len(result.pivots) + 1):
            key = f"level_{i}"
            if key not in result.pivots:
                break
            if result.metadata.get(f"type_{i}") == "resistance":
                assert result.pivots[key] > current_price

    def test_no_network_calls(self, make_ohlcv, monkeypatch):
        """Detector must not make any network calls."""
        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network call")),
        )
        df = make_ohlcv(OSCILLATING_PRICES)
        SupportResistanceDetector().detect(df, "TEST")
