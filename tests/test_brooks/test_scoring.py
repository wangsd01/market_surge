from brooks.config import BrooksConfig
from brooks.market_cycle import MarketCycleResult
from brooks.breakout import BreakoutEvent, FollowThroughResult
from brooks.h1h2 import TriggerEvent, H1H2State
from brooks.extension import ExtensionResult
from brooks.stops_targets import TargetSet
from brooks.scoring import compute_scores


def _market_cycle(cycle="BULL_TREND", prior_trend=None, bear_relevance=1.0):
    return MarketCycleResult(current_cycle=cycle, prior_trend=prior_trend, trading_range_length=0, bear_relevance=bear_relevance)


def _breakout(score=0.9, is_strong=True, is_extreme=True, true_gap_up=True, volume_ratio=2.0):
    return BreakoutEvent(
        idx=10, date=None, breakout_score=score, is_strong=is_strong, is_extreme=is_extreme,
        breakout_level=100.0, gap_pct=0.05, true_gap_up=true_gap_up, volume_ratio=volume_ratio,
    )


def _h2_state():
    trigger = TriggerEvent(
        signal_date=None, trigger_date=None, trigger_price=105.0,
        signal_bar_low=100.0, signal_bar_high=104.0, pullback_leg_low=99.0,
    )
    return H1H2State(
        h1=trigger, h2=trigger, h1_failed=False, h2_failed=False, h1_structural_failed=False,
        h2_structural_failed=False, days_since_h1_trigger=3, days_since_h2_trigger=1,
        forming=None, reset_from_failure=False, prior_failed_pattern=None,
    )


def test_setup_quality_and_entry_quality_scale_zero_to_ten():
    config = BrooksConfig()
    market_cycle = _market_cycle("STRONG_BULL_TREND")
    breakout_event = _breakout(score=1.0, is_strong=True, is_extreme=True)
    follow_through = FollowThroughResult(follow_through_score=1.0, retracement_pct=0.0, gap_still_open=True)
    h1h2_state = _h2_state()
    extension = ExtensionResult(is_extended=False, reason=None)
    targets = TargetSet(nearest_resistance=115.0, target_1=115.0, target_2=110.0, rr_target_1=3.0, rr_target_2=2.0)

    scores = compute_scores(
        market_cycle=market_cycle, breakout_event=breakout_event, follow_through=follow_through,
        h1h2_state=h1h2_state, extension=extension, targets=targets, dollar_vol=100_000_000, config=config,
    )

    assert 0.0 <= scores.setup_quality_score <= 10.0
    assert 0.0 <= scores.entry_quality_score <= 10.0
    assert 0.0 <= scores.trade_score <= 10.0
    # everything maxed out -> both composite scores should be at (or very near) the top
    assert scores.setup_quality_score > 8.0
    assert scores.entry_quality_score > 8.0


def test_extended_breakout_has_high_setup_quality_but_low_entry_quality():
    config = BrooksConfig()
    market_cycle = _market_cycle("STRONG_BULL_TREND")
    breakout_event = _breakout(score=1.0, is_strong=True, is_extreme=True)
    follow_through = FollowThroughResult(follow_through_score=1.0, retracement_pct=0.0, gap_still_open=True)
    extension = ExtensionResult(is_extended=True, reason="consecutive_strong_bull_bars")
    # no clean entry available: no h1h2 trigger, target barely above entry
    targets = TargetSet(nearest_resistance=101.0, target_1=101.0, target_2=110.0, rr_target_1=0.3, rr_target_2=2.0)

    scores = compute_scores(
        market_cycle=market_cycle, breakout_event=breakout_event, follow_through=follow_through,
        h1h2_state=None, extension=extension, targets=targets, dollar_vol=100_000_000, config=config,
    )

    assert scores.setup_quality_score > 8.0
    assert scores.entry_quality_score < 5.0
    assert scores.entry_quality_score < scores.setup_quality_score


def test_penalty_rule_large_upper_tail_reduces_breakout_quality():
    config = BrooksConfig()
    market_cycle = _market_cycle("BULL_TREND")
    strong_breakout = _breakout(score=0.9)
    weak_close_breakout = _breakout(score=0.9, is_strong=False)
    follow_through = FollowThroughResult(follow_through_score=0.0, retracement_pct=0.2, gap_still_open=True)
    targets = TargetSet(nearest_resistance=110.0, target_1=110.0, target_2=110.0, rr_target_1=2.0, rr_target_2=2.0)

    scores_strong = compute_scores(
        market_cycle=market_cycle, breakout_event=strong_breakout, follow_through=follow_through,
        h1h2_state=None, extension=ExtensionResult(False, None), targets=targets, dollar_vol=100_000_000, config=config,
    )
    scores_weak_close = compute_scores(
        market_cycle=market_cycle, breakout_event=weak_close_breakout, follow_through=follow_through,
        h1h2_state=None, extension=ExtensionResult(False, None), targets=targets, dollar_vol=100_000_000, config=config,
    )

    assert scores_weak_close.breakout_quality < scores_strong.breakout_quality
