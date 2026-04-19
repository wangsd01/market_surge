import pytest
from patterns.cup_handle import CupHandleDetector
from patterns.base import PatternResult


# Canonical cup-with-handle price series:
#   - Days 0-4:  build-up to left_high=100
#   - Days 5-14: cup descent to cup_low=75 (25% depth)
#   - Days 15-24: hold at cup bottom (spans ≥10 days → not V-shape)
#   - Days 25-39: recovery to right_high=97 (within 5% of 100)
#   - Days 40-49: handle, 10-day pullback to 91 (decline=6, 24% of cup depth ≤50%)
#   - Days 50-54: post-handle close near right_high
VALID_PRICES = [
    90, 95, 100, 99, 98,                                      # 0-4
    96, 93, 90, 87, 84, 82, 79, 77, 76, 75,                  # 5-14
    75, 75, 75, 76, 77, 78, 79, 81, 83, 85,                  # 15-24
    87, 89, 91, 92, 93, 94, 95, 96, 97, 97,                  # 25-34
    97, 97, 97, 97, 97,                                       # 35-39
    96, 94, 93, 92, 91, 91, 92, 93, 94, 95,                  # 40-49
    96, 97, 97, 97, 97,                                       # 50-54
]

# Declining volumes during handle (days 40-49), flat elsewhere
VALID_VOLUMES = (
    [1_000_000] * 40
    + [900_000, 800_000, 700_000, 650_000, 600_000,
       580_000, 590_000, 600_000, 620_000, 650_000]
    + [1_000_000] * 5
)


class TestCupHandleDetector:

    def test_detects_valid_cup_handle(self, make_ohlcv):
        """A textbook cup with handle returns PatternResult with confidence > 0.5."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = CupHandleDetector().detect(df, "TEST")

        assert result is not None
        assert isinstance(result, PatternResult)
        assert result.pattern == "cup_handle"
        assert result.ticker == "TEST"
        assert result.confidence > 0.5

    def test_returns_pattern_result_not_dict(self, make_ohlcv):
        """When pattern is found, must return PatternResult, not a raw dict."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = CupHandleDetector().detect(df, "TEST")
        if result is not None:
            assert type(result) is PatternResult

    def test_pivots_contain_required_keys(self, make_ohlcv):
        """PatternResult.pivots must have all 5 required pivot names."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = CupHandleDetector().detect(df, "TEST")
        if result is not None:
            required = {"left_high", "cup_low", "right_high", "handle_low", "handle_high"}
            assert required.issubset(result.pivots.keys())
            assert required.issubset(result.pivot_dates.keys())

    def test_detected_on_is_last_bar_date(self, make_ohlcv):
        """detected_on must equal the date of the last bar in the input df."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = CupHandleDetector().detect(df, "TEST")
        if result is not None:
            assert result.detected_on == df.index[-1].date()

    def test_confidence_in_unit_interval(self, make_ohlcv):
        """Confidence must be in [0.0, 1.0]."""
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        result = CupHandleDetector().detect(df, "TEST")
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0

    def test_returns_none_for_short_df(self, make_ohlcv):
        """Returns None when df has fewer than 45 rows (lookback minimum)."""
        df = make_ohlcv([100.0] * 30)
        result = CupHandleDetector().detect(df, "TEST")
        assert result is None

    def test_returns_none_for_flat_prices(self, make_ohlcv):
        """Returns None for flat price series — no discernible cup shape."""
        df = make_ohlcv([100.0] * 60)
        result = CupHandleDetector().detect(df, "TEST")
        assert result is None

    def test_shallow_cup_fails_depth_condition(self, make_ohlcv):
        """Cup depth < 15% should fail condition 1, lowering confidence or returning None."""
        # left_high=100, cup_low=92 → depth=8% (too shallow)
        prices = [
            95, 98, 100, 99, 98,
            97, 96, 95, 94, 93, 92, 92, 92, 92, 92,
            92, 92, 92, 93, 94, 95, 96, 97, 97, 97,
            97, 97, 97, 97, 97, 97, 97, 97, 97, 97,
            97, 97, 97, 97, 97,
            96, 95, 95, 95, 95, 95, 96, 96, 97, 97,
            97, 97, 97, 97, 97,
        ]
        df = make_ohlcv(prices)
        result = CupHandleDetector().detect(df, "TEST")
        # Must either return None or report confidence < 1.0
        if result is not None:
            assert result.confidence < 1.0

    def test_v_shape_cup_fails_shape_condition(self, make_ohlcv):
        """A V-shape (bottom < 10 days) should fail condition 2."""
        # Very sharp bottom — only 2 days at the low
        prices = [
            90, 95, 100, 99, 98,
            92, 84, 75, 84, 92,                               # 5-day V-shape bottom
            97, 97, 97, 97, 97, 97, 97, 97, 97, 97,
            97, 97, 97, 97, 97, 97, 97, 97, 97, 97,
            97, 97, 97, 97, 97, 97, 97, 97, 97, 97,
            96, 95, 94, 93, 92, 92, 93, 94, 95, 96,
            97, 97, 97, 97, 97,
        ]
        df = make_ohlcv(prices)
        result = CupHandleDetector().detect(df, "TEST")
        if result is not None:
            assert result.confidence < 1.0

    def test_handle_must_form_in_upper_half_of_base(self, make_ohlcv):
        """A handle that undercuts the base midpoint should not qualify."""
        prices = [
            90, 95, 100, 99, 98,
            96, 93, 90, 87, 84, 82, 79, 77, 76, 75,
            75, 75, 75, 76, 77, 78, 79, 81, 83, 85,
            87, 89, 91, 92, 93, 94, 95, 96, 97, 97,
            97, 97, 97, 97, 97,
            95, 92, 88, 84, 80, 77, 78, 80, 82, 84,
            86, 88, 90, 92, 94,
        ]
        volumes = (
            [1_000_000] * 40
            + [900_000, 850_000, 800_000, 760_000, 720_000,
               680_000, 660_000, 650_000, 640_000, 630_000]
            + [1_000_000] * 5
        )
        df = make_ohlcv(prices, volumes)

        result = CupHandleDetector().detect(df, "TEST")

        assert result is None

    def test_no_network_calls(self, make_ohlcv, monkeypatch):
        """Detector must not make any network calls."""
        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network call detected")))
        df = make_ohlcv(VALID_PRICES, VALID_VOLUMES)
        # Should not raise AssertionError
        CupHandleDetector().detect(df, "TEST")


# ---------------------------------------------------------------------------
# POWL real-world case: cup 02/12/26–03/25/26, handle 03/25/26–04/07/26
# ---------------------------------------------------------------------------
# Approximate price structure (trading days, not calendar days):
#   10 days pre-cup  → left_high = 200
#   10 days descent  → 200 → 162
#    8 days bottom   → flat ~158–162  (rounded base, not V-shape)
#   10 days recovery → 162 → 196     (right_high = 196, within 2% of 200)
#    9 days handle   → 196 → 186 low → 193  (decline ~24% of cup depth)
#    9 days breakout → 193 → 210     (post-handle; price exceeds left_high)
_POWL_PRE_CUP  = [196, 197, 199, 200, 199, 198, 199, 200, 199, 200]
_POWL_CUP_DOWN = [197, 193, 189, 185, 181, 177, 173, 169, 165, 162]
_POWL_CUP_BOT  = [160, 159, 158, 158, 159, 160, 161, 162]
_POWL_CUP_UP   = [165, 169, 173, 177, 181, 185, 189, 193, 195, 196]
_POWL_HANDLE   = [194, 191, 188, 186, 186, 187, 189, 191, 193]
_POWL_BREAKOUT = [196, 199, 202, 205, 208, 210, 208, 209, 210]

_POWL_PRICES = (
    _POWL_PRE_CUP + _POWL_CUP_DOWN + _POWL_CUP_BOT + _POWL_CUP_UP + _POWL_HANDLE
)
_POWL_PRICES_WITH_BREAKOUT = _POWL_PRICES + _POWL_BREAKOUT

# Volumes decline through the handle, spike on breakout
_POWL_VOLS = (
    [2_000_000] * 38
    + [1_800_000, 1_600_000, 1_400_000, 1_200_000, 1_100_000,
       1_000_000, 1_050_000, 1_100_000, 1_150_000]
)
_POWL_VOLS_WITH_BREAKOUT = _POWL_VOLS + [3_000_000] * 9


class TestPOWLCupHandle:
    """POWL real-world case: cup 02/12/26–03/25/26, handle 03/25/26–04/07/26."""

    def test_detected_when_df_ends_at_handle_end(self, make_ohlcv):
        """Pattern is found when df ends at 04/07 — the last handle bar."""
        df = make_ohlcv(_POWL_PRICES, _POWL_VOLS)
        result = CupHandleDetector().detect(df, "POWL")

        assert result is not None
        assert result.pattern == "cup_handle"
        assert result.confidence >= 5 / 7
        assert abs(result.pivots["left_high"] - 200) < 2
        assert abs(result.pivots["right_high"] - 196) < 2
        assert abs(result.pivots["handle_low"] - 186) < 2

    def test_handle_geometry_is_valid_at_handle_end(self, make_ohlcv):
        """handle_low must be below handle_high (handle is a pullback, not a breakout)."""
        df = make_ohlcv(_POWL_PRICES, _POWL_VOLS)
        result = CupHandleDetector().detect(df, "POWL")
        if result is not None:
            assert result.pivots["handle_low"] < result.pivots["handle_high"]

    def test_detected_correctly_with_post_breakout_data(self, make_ohlcv):
        """Detector finds the real handle even when df includes post-breakout bars."""
        df = make_ohlcv(_POWL_PRICES_WITH_BREAKOUT, _POWL_VOLS_WITH_BREAKOUT)
        result = CupHandleDetector().detect(df, "POWL")

        assert result is not None, "should detect the 03/25 right lip, not the breakout bar"
        assert result.pivots["handle_low"] < result.pivots["handle_high"], (
            "handle_low > handle_high — detector mistook the breakout for right_high "
            "and has no real downward handle remaining"
        )
