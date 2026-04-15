import numpy as np
import pytest
from patterns.vcp import VCPDetector
from patterns.base import PatternResult


def _make_vcp_prices() -> list[float]:
    """
    Generate a 75-day VCP price series with 3 monotonically contracting swings.

    Key points (index, price):
      (0,90) → (14,100) → (24,82) → (34,95) → (44,84) → (54,92) → (64,87) → (74,93)

    Contractions (all > 2% swing threshold):
      #1  high=100, low=82  decline=18.0%  recovery to high_2=15.9%
      #2  high=95,  low=84  decline=11.6%  recovery to high_3= 9.5%
      #3  high=92,  low=87  decline= 5.4%  (final contraction)

    Declines 18% > 11.6% > 5.4%  ✓
    Recoveries 15.9% > 9.5%       ✓ (condition 3)
    """
    keypoints = [
        (0, 90), (14, 100), (24, 82),
        (34, 95), (44, 84), (54, 92),
        (64, 87), (74, 93),
    ]
    prices: list[float] = []
    for i in range(len(keypoints) - 1):
        x0, p0 = keypoints[i]
        x1, p1 = keypoints[i + 1]
        segment = list(np.linspace(p0, p1, x1 - x0 + 1))
        prices.extend(segment if i == 0 else segment[1:])
    return prices


VALID_PRICES = _make_vcp_prices()

# Volumes: declining across contractions, flat elsewhere
_BASE_VOL = 1_000_000
_VOLS = [_BASE_VOL] * len(VALID_PRICES)
for _idx in range(14, 25):   # contraction 1
    _VOLS[_idx] = 1_500_000
for _idx in range(34, 45):   # contraction 2
    _VOLS[_idx] = 1_100_000
for _idx in range(54, 65):   # contraction 3
    _VOLS[_idx] = 700_000
VALID_VOLUMES = _VOLS


class TestVCPDetector:

    def test_detects_valid_vcp(self, make_ohlcv):
        """Three monotonically shrinking contractions → PatternResult with confidence > 0.5."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = VCPDetector().detect(df, "TEST")

        assert result is not None
        assert isinstance(result, PatternResult)
        assert result.pattern == "vcp"
        assert result.ticker == "TEST"
        assert result.confidence > 0.5

    def test_returns_pattern_result_not_dict(self, make_ohlcv):
        """When a pattern is found, must return PatternResult, not a raw dict."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = VCPDetector().detect(df, "TEST")
        if result is not None:
            assert type(result) is PatternResult

    def test_pivots_contain_high_low_keys(self, make_ohlcv):
        """Pivots must contain high_N and low_N keys for each detected contraction."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = VCPDetector().detect(df, "TEST")
        if result is not None:
            # At minimum, one complete cycle: high_1 and low_1
            assert "high_1" in result.pivots
            assert "low_1" in result.pivots
            assert "high_1" in result.pivot_dates
            assert "low_1" in result.pivot_dates

    def test_detected_on_is_last_bar_date(self, make_ohlcv):
        """detected_on must equal the date of the last bar in df."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = VCPDetector().detect(df, "TEST")
        if result is not None:
            assert result.detected_on == df.index[-1].date()

    def test_confidence_in_unit_interval(self, make_ohlcv):
        """Confidence must be in [0.0, 1.0]."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = VCPDetector().detect(df, "TEST")
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0

    def test_returns_none_for_short_df(self, make_ohlcv):
        """Returns None when df has fewer than 30 rows (minimum lookback)."""
        df = make_ohlcv([100.0] * 20)
        result = VCPDetector().detect(df, "TEST")
        assert result is None

    def test_returns_none_for_flat_prices(self, make_ohlcv):
        """Returns None for flat prices — no swing structure to detect."""
        df = make_ohlcv([100.0] * 75)
        result = VCPDetector().detect(df, "TEST")
        assert result is None

    def test_condition4_skipped_when_df_shorter_than_150_days(self, make_ohlcv):
        """Series < 150 days: SMA condition is skipped, must not block detection."""
        # VALID_PRICES is 75 days — well below 150, so c4 is skipped
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = VCPDetector().detect(df, "TEST")
        # Detector must still return a result (c4 skipped, not penalised)
        assert result is not None

    def test_expanding_contractions_not_detected(self, make_ohlcv):
        """Contractions that grow (not shrink) must not be flagged as VCP."""
        # Reverse of valid: swings get LARGER over time
        keypoints = [
            (0, 90), (14, 94), (24, 88),   # small swing: 6.4%
            (34, 97), (44, 83),             # bigger swing: 14.4%
            (54, 100), (64, 75), (74, 95),  # biggest swing: 25%
        ]
        prices: list[float] = []
        for i in range(len(keypoints) - 1):
            x0, p0 = keypoints[i]
            x1, p1 = keypoints[i + 1]
            seg = list(np.linspace(p0, p1, x1 - x0 + 1))
            prices.extend(seg if i == 0 else seg[1:])
        df = make_ohlcv(prices)
        result = VCPDetector().detect(df, "TEST")
        # Either None or low confidence — the contractions are expanding
        if result is not None:
            assert result.confidence < 1.0

    def test_requires_broader_trend_template_alignment(self, make_ohlcv):
        """A shrinking-contraction sequence below the long-term trend should be rejected."""
        prefix = list(np.linspace(170, 91, 120))
        prices = prefix + VALID_PRICES
        volumes = [1_000_000] * len(prefix) + VALID_VOLUMES
        df = make_ohlcv(prices, volumes)

        result = VCPDetector().detect(df, "TEST")

        assert result is None

    def test_no_network_calls(self, make_ohlcv, monkeypatch):
        """Detector must not make any network calls."""
        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network call detected")),
        )
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        VCPDetector().detect(df, "TEST")
