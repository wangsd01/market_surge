import pytest
from datetime import date

from patterns.base import PatternResult
from strategies import TradeSetup, strategy


def _result(pattern: str, pivots: dict, metadata: dict | None = None) -> PatternResult:
    return PatternResult(
        pattern=pattern,
        ticker="TEST",
        confidence=1.0,
        detected_on=date(2025, 3, 31),
        pivots=pivots,
        pivot_dates={k: date(2025, 3, 1) for k in pivots},
        metadata=metadata or {},
    )


CUP_RESULT = _result(
    "cup_handle",
    {"left_high": 110.0, "cup_low": 88.0, "right_high": 108.0,
     "handle_high": 107.0, "handle_low": 103.0},
)

DOUBLE_RESULT = _result(
    "double_bottom",
    {"first_trough": 80.0, "middle_high": 100.0, "second_trough": 81.0},
)

VCP_RESULT = _result(
    "vcp",
    {"high_1": 105.0, "low_1": 95.0, "high_2": 102.0, "low_2": 97.0, "high_3": 100.0},
)

FLAT_BASE_RESULT = _result(
    "flat_base",
    {"base_high": 120.0, "base_low": 108.0},
)

CHANNEL_RESULT = _result(
    "channel",
    {"channel_top": 115.0, "channel_bottom": 100.0},
    metadata={"upper_slope": 0.1, "lower_slope": 0.05,
              "channel_width_pct": 0.13, "price_position_pct": 0.5},
)

SR_RESULT = _result(
    "support_resistance",
    {"level_1": 95.0, "level_2": 105.0, "level_3": 115.0},
    metadata={"type_1": "support", "type_2": "resistance", "type_3": "resistance",
              "touch_count_1": 3, "touch_count_2": 2, "touch_count_3": 2},
)

INVALID_SR_RESULT = _result(
    "support_resistance",
    {"level_1": 90.0, "level_2": 95.0, "level_3": 100.0},
    metadata={"type_1": "support", "type_2": "support", "type_3": "support",
              "touch_count_1": 3, "touch_count_2": 2, "touch_count_3": 2},
)

HIGH2_RESULT = _result(
    "high2",
    {
        "prior_swing_high": 120.0,
        "pullback_low": 110.0,
        "h1_high": 118.0,
        "h2_high": 119.0,
        "h2_low": 114.0,
    },
    metadata={"prior_leg_height": 12.0},
)

HIGH2_NEAR_SWING_RESULT = _result(
    "high2",
    {
        "prior_swing_high": 119.0,
        "pullback_low": 110.0,
        "h1_high": 118.0,
        "h2_high": 118.95,
        "h2_low": 114.0,
    },
    metadata={"prior_leg_height": 12.0},
)


class TestTradeSetup:

    def test_returns_trade_setup_dataclass(self):
        """strategy() must return a TradeSetup dataclass."""
        result = strategy(CUP_RESULT)
        assert isinstance(result, TradeSetup)

    def test_ticker_and_pattern_preserved(self):
        """TradeSetup must carry the ticker and pattern name from PatternResult."""
        result = strategy(CUP_RESULT)
        assert result.ticker == "TEST"
        assert result.pattern == "cup_handle"

    def test_entry_is_ten_cents_above_cup_handle_buy_point(self):
        """Cup-handle buy point = handle high + $0.10."""
        result = strategy(CUP_RESULT)
        expected_entry = 107.10
        assert abs(result.entry - expected_entry) < 0.001

    def test_target_equals_entry_plus_rr_times_risk(self):
        """Target = entry + (entry - stop) * risk_reward."""
        result = strategy(CUP_RESULT)
        expected_target = result.entry + (result.entry - result.stop) * result.risk_reward
        assert abs(result.target - expected_target) < 0.001

    def test_risk_pct_equals_entry_minus_stop_over_entry(self):
        """risk_pct = (entry - stop) / entry."""
        result = strategy(CUP_RESULT)
        expected_risk_pct = (result.entry - result.stop) / result.entry
        assert abs(result.risk_pct - expected_risk_pct) < 0.0001

    def test_risk_per_share_equals_entry_minus_stop(self):
        """risk_per_share = entry - stop."""
        result = strategy(CUP_RESULT)
        expected_risk_per_share = result.entry - result.stop
        assert abs(result.risk_per_share - expected_risk_per_share) < 0.0001

    def test_invalidation_rule_is_price_below_stop(self):
        """The v1 invalidation rule is fixed and price-based."""
        result = strategy(CUP_RESULT)
        assert result.invalidation_rule == "invalid if price trades below stop"

    def test_cup_handle_uses_handle_high_as_breakout(self):
        """Cup-handle entry uses the handle high plus the standard ten-cent buffer."""
        result = strategy(CUP_RESULT)
        assert abs(result.entry - (CUP_RESULT.pivots["handle_high"] + 0.10)) < 0.001

    def test_cup_handle_uses_handle_low_as_stop(self):
        """Cup-handle stop = handle_low."""
        result = strategy(CUP_RESULT)
        assert abs(result.stop - CUP_RESULT.pivots["handle_low"]) < 0.001

    def test_double_bottom_uses_middle_high_as_breakout(self):
        """Double-bottom buy point = middle_high + $0.10."""
        result = strategy(DOUBLE_RESULT)
        assert abs(result.entry - 100.10) < 0.001

    def test_double_bottom_uses_second_trough_as_stop(self):
        """Double-bottom stop = second_trough."""
        result = strategy(DOUBLE_RESULT)
        assert abs(result.stop - DOUBLE_RESULT.pivots["second_trough"]) < 0.001

    def test_vcp_uses_last_high_as_breakout(self):
        """VCP breakout = last high_N pivot (highest N)."""
        result = strategy(VCP_RESULT)
        last_high = VCP_RESULT.pivots["high_3"]
        assert abs(result.entry - last_high * 1.0005) < 0.001

    def test_flat_base_uses_base_high_plus_ten_cents(self):
        """Flat-base buy point = base_high + $0.10."""
        result = strategy(FLAT_BASE_RESULT)
        assert abs(result.entry - 120.10) < 0.001

    def test_flat_base_uses_base_low_as_stop(self):
        """Flat-base stop = base_low."""
        result = strategy(FLAT_BASE_RESULT)
        assert abs(result.stop - 108.0) < 0.001

    def test_channel_uses_channel_top_as_breakout(self):
        """Channel breakout = channel_top."""
        result = strategy(CHANNEL_RESULT)
        assert abs(result.entry - CHANNEL_RESULT.pivots["channel_top"] * 1.0005) < 0.001

    def test_channel_uses_channel_bottom_as_stop(self):
        """Channel stop = channel_bottom."""
        result = strategy(CHANNEL_RESULT)
        assert abs(result.stop - CHANNEL_RESULT.pivots["channel_bottom"]) < 0.001

    def test_sr_uses_nearest_resistance_as_breakout(self):
        """S/R breakout = nearest resistance level above current price.

        SR_RESULT has resistance at 105 and 115, support at 95.
        Nearest resistance above 95 is 105.
        """
        result = strategy(SR_RESULT)
        assert abs(result.entry - 105.0 * 1.0005) < 0.001

    def test_sr_uses_nearest_support_as_stop(self):
        """S/R stop = nearest support level below current price."""
        result = strategy(SR_RESULT)
        assert abs(result.stop - 95.0) < 0.001

    def test_sr_requires_resistance_above_and_support_below(self):
        """An S/R pattern without a real breakout level should be rejected."""
        with pytest.raises(ValueError, match="support/resistance"):
            strategy(INVALID_SR_RESULT)

    def test_risk_reward_matches_pattern_table(self):
        """Risk/reward ratio must match the RISK_REWARD lookup table."""
        from strategies import RISK_REWARD
        for pr in [CUP_RESULT, DOUBLE_RESULT, VCP_RESULT, FLAT_BASE_RESULT, CHANNEL_RESULT, SR_RESULT, HIGH2_RESULT]:
            result = strategy(pr)
            assert result.risk_reward == RISK_REWARD[pr.pattern]

    def test_entry_always_above_stop(self):
        """Entry must always be above stop for all patterns."""
        for pr in [CUP_RESULT, DOUBLE_RESULT, VCP_RESULT, FLAT_BASE_RESULT, CHANNEL_RESULT, SR_RESULT, HIGH2_RESULT]:
            result = strategy(pr)
            assert result.entry > result.stop, f"entry <= stop for {pr.pattern}"

    def test_target_always_above_entry(self):
        """Target must always be above entry for all patterns."""
        for pr in [CUP_RESULT, DOUBLE_RESULT, VCP_RESULT, FLAT_BASE_RESULT, CHANNEL_RESULT, SR_RESULT, HIGH2_RESULT]:
            result = strategy(pr)
            assert result.target > result.entry, f"target <= entry for {pr.pattern}"

    def test_high2_uses_h2_high_as_breakout(self):
        result = strategy(HIGH2_RESULT)
        assert abs(result.entry - (119.0 * 1.0005)) < 0.001

    def test_high2_uses_pullback_low_as_stop(self):
        result = strategy(HIGH2_RESULT)
        assert result.stop == 110.0

    def test_high2_uses_custom_target_branch(self):
        result = strategy(HIGH2_RESULT)
        expected_entry = 119.0 * 1.0005
        expected_risk = expected_entry - 110.0
        expected_target = max(120.0, expected_entry + expected_risk * 2.0, expected_entry + 12.0)
        assert abs(result.target - expected_target) < 0.001

    def test_high2_excludes_prior_swing_target_when_too_close_to_entry(self):
        result = strategy(HIGH2_NEAR_SWING_RESULT)
        expected_entry = 118.95 * 1.0005
        expected_risk = expected_entry - 110.0
        expected_target = max(expected_entry + expected_risk * 2.0, expected_entry + 12.0)
        assert abs(result.target - expected_target) < 0.001

    def test_high2_realized_reward_to_risk_is_at_least_two(self):
        result = strategy(HIGH2_RESULT)
        realized_rr = (result.target - result.entry) / (result.entry - result.stop)
        assert realized_rr >= 2.0 - 1e-9
