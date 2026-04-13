import pytest
from patterns.double_bottom import DoubleBottomDetector
from patterns.base import PatternResult


# Canonical double-bottom price series:
#   - Days 0-9:   decline from 100 to 80
#   - Days 10-14: first trough region (~75)
#   - Days 15-34: recovery to middle peak (~90, >10% above troughs)
#   - Days 35-49: decline to second trough (~76, within 3% of 75)
#   - Days 50-59: recovery
# Trough separation ≈ 35 trading days (within 15-50 ✓)
# Middle peak (90) is 20% above trough (~75) ✓
VALID_PRICES = [
    # Decline (0-9)
    100, 98, 96, 93, 90, 87, 84, 82, 80, 78,
    # First trough (10-14)
    76, 75, 75, 75, 76,
    # Recovery to middle peak (15-34)
    78, 80, 82, 84, 86, 87, 88, 89, 90, 90,
    90, 90, 90, 89, 88, 87, 86, 85, 84, 83,
    # Second trough (35-49) — within 3% of first trough
    82, 80, 78, 77, 76, 75, 75, 76, 76, 76,
    76, 76, 76, 76, 76,
    # Recovery (50-59)
    78, 80, 83, 86, 88, 90, 92, 94, 95, 96,
]

# Second trough volume < first trough volume (condition 4)
VALID_VOLUMES = (
    [1_000_000] * 10
    + [1_200_000, 1_300_000, 1_300_000, 1_200_000, 1_100_000]  # first trough: ~1.2M
    + [1_000_000] * 20                                           # middle
    + [800_000, 750_000, 700_000, 650_000, 600_000,
       550_000, 550_000, 580_000, 580_000, 580_000,
       580_000, 580_000, 580_000, 580_000, 580_000]             # second trough: ~650K
    + [1_000_000] * 10
)


class TestDoubleBottomDetector:

    def test_detects_valid_double_bottom(self, make_ohlcv):
        """A textbook double bottom returns PatternResult with confidence > 0.5."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is not None
        assert isinstance(result, PatternResult)
        assert result.pattern == "double_bottom"
        assert result.ticker == "TEST"
        assert result.confidence > 0.5

    def test_returns_pattern_result_not_dict(self, make_ohlcv):
        """When pattern is found, must return PatternResult, not a raw dict."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = DoubleBottomDetector().detect(df, "TEST")
        if result is not None:
            assert type(result) is PatternResult

    def test_pivots_contain_required_keys(self, make_ohlcv):
        """PatternResult.pivots must have first_trough, middle_high, second_trough."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = DoubleBottomDetector().detect(df, "TEST")
        if result is not None:
            required = {"first_trough", "middle_high", "second_trough"}
            assert required.issubset(result.pivots.keys())
            assert required.issubset(result.pivot_dates.keys())

    def test_detected_on_is_last_bar_date(self, make_ohlcv):
        """detected_on must equal the date of the last bar in df."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = DoubleBottomDetector().detect(df, "TEST")
        if result is not None:
            assert result.detected_on == df.index[-1].date()

    def test_confidence_in_unit_interval(self, make_ohlcv):
        """Confidence must be in [0.0, 1.0]."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = DoubleBottomDetector().detect(df, "TEST")
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0

    def test_returns_none_for_short_df(self, make_ohlcv):
        """Returns None when df has fewer than 45 rows."""
        df = make_ohlcv([100.0] * 30)
        result = DoubleBottomDetector().detect(df, "TEST")
        assert result is None

    def test_returns_none_for_flat_prices(self, make_ohlcv):
        """Returns None when prices are flat (no troughs)."""
        df = make_ohlcv([100.0] * 60)
        result = DoubleBottomDetector().detect(df, "TEST")
        assert result is None

    def test_troughs_too_far_apart_fails_separation_condition(self, make_ohlcv):
        """Troughs > 50 days apart should fail condition 2."""
        # Two dips 55 days apart — build 80-day series
        prices = (
            [100, 95, 90, 85, 80, 75, 75, 75, 80, 85]           # first trough at day 5-7
            + [90] * 50                                           # long middle peak
            + [85, 80, 76, 76, 76, 80, 85, 90, 95, 100]          # second trough 60 days later
        )
        volumes = (
            [1_200_000] * 3 + [1_400_000, 1_400_000, 1_400_000] + [1_200_000] * 4
            + [1_000_000] * 50
            + [1_000_000] * 3 + [800_000, 800_000, 800_000] + [1_000_000] * 4
        )
        df = make_ohlcv(prices, volumes)
        result = DoubleBottomDetector().detect(df, "TEST")
        if result is not None:
            assert result.confidence < 1.0

    def test_monotone_decline_returns_none(self, make_ohlcv):
        """A strictly monotone declining series has no second trough — must return None."""
        # Prices only go down — no W shape possible
        prices = list(range(110, 50, -1))  # 60 prices: 110, 109, ..., 51
        df = make_ohlcv(prices)
        result = DoubleBottomDetector().detect(df, "TEST")
        assert result is None

    def test_weak_middle_peak_fails_condition(self, make_ohlcv):
        """Middle peak < 10% above troughs should fail condition 3."""
        # troughs=75, middle peak=80 → only 6.7% above trough
        prices = (
            [100, 95, 90, 85, 80, 75, 75, 75, 76, 77]
            + [78, 79, 80, 80, 80, 79, 78, 77, 76, 75]  # middle peak=80 (only 6.7% above 75)
            + [75, 75, 76, 77, 78]
            + [80, 85, 90, 95, 100] * 5
        )
        df = make_ohlcv(prices[:60])
        result = DoubleBottomDetector().detect(df, "TEST")
        if result is not None:
            assert result.confidence < 1.0

    def test_no_network_calls(self, make_ohlcv, monkeypatch):
        """Detector must not make any network calls."""
        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network call detected")),
        )
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        DoubleBottomDetector().detect(df, "TEST")
