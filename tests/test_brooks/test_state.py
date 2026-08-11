from brooks.config import BrooksConfig
from brooks.market_cycle import MarketCycleResult
from brooks.breakout import BreakoutEvent, FollowThroughResult
from brooks.h1h2 import TriggerEvent, H1H2State
from brooks.extension import ExtensionResult
from brooks.state import resolve_state

CONFIG = BrooksConfig()
LATEST_IDX = 100


def _cycle(cycle="TRADING_RANGE"):
    return MarketCycleResult(current_cycle=cycle, prior_trend=None, trading_range_length=0, bear_relevance=1.0)


def _breakout(idx=LATEST_IDX, **kwargs):
    defaults = dict(
        date=None, breakout_score=0.9, is_strong=True, is_extreme=True,
        breakout_level=100.0, low=99.0, prior_high=98.5, gap_pct=0.05, true_gap_up=True, volume_ratio=2.0,
    )
    defaults.update(kwargs)
    return BreakoutEvent(idx=idx, **defaults)


def _follow_through(**kwargs):
    defaults = dict(follow_through_score=0.5, retracement_pct=0.2, gap_still_open=True)
    defaults.update(kwargs)
    return FollowThroughResult(**defaults)


def _trigger(trigger_date="triggered"):
    return TriggerEvent(
        signal_date="signal", trigger_date=trigger_date, trigger_price=105.0,
        signal_bar_low=100.0, signal_bar_high=104.0, pullback_leg_low=99.0,
    )


def _h1h2(**kwargs):
    defaults = dict(
        h1=None, h2=None, h1_failed=False, h2_failed=False, h1_structural_failed=False,
        h2_structural_failed=False, days_since_h1_trigger=None, days_since_h2_trigger=None,
        forming=None, reset_from_failure=False, prior_failed_pattern=None,
    )
    defaults.update(kwargs)
    return H1H2State(**defaults)


def _resolve(**overrides):
    defaults = dict(
        market_cycle=_cycle(),
        breakout_event=None,
        follow_through=None,
        h1h2_state=None,
        extension=ExtensionResult(False, None),
        entry_quality_score=5.0,
        latest_idx=LATEST_IDX,
        config=CONFIG,
    )
    defaults.update(overrides)
    return resolve_state(**defaults)


def test_failed_h2():
    h1h2 = _h1h2(h1=_trigger(), h2=_trigger(), h2_failed=True)
    assert _resolve(h1h2_state=h1h2) == "FAILED_H2"


def test_failed_h1():
    h1h2 = _h1h2(h1=_trigger(), h1_failed=True)
    assert _resolve(h1h2_state=h1h2) == "FAILED_H1"


def test_failed_generic_breakout_retraced():
    assert (
        _resolve(
            breakout_event=_breakout(idx=50),
            follow_through=_follow_through(follow_through_score=-0.5, retracement_pct=1.2),
        )
        == "FAILED_H1"
    )


def test_extended_after_h2():
    h1h2 = _h1h2(h1=_trigger(), h2=_trigger(), days_since_h2_trigger=2)
    assert _resolve(h1h2_state=h1h2, extension=ExtensionResult(True, "atr_distance")) == "EXTENDED_AFTER_H2"


def test_extended_after_breakout():
    assert _resolve(extension=ExtensionResult(True, "ema20_distance")) == "EXTENDED_AFTER_BREAKOUT"


def test_h2_triggered_today():
    h1h2 = _h1h2(h1=_trigger(), h2=_trigger(), days_since_h2_trigger=0)
    assert _resolve(h1h2_state=h1h2) == "H2_TRIGGERED_TODAY"


def test_h2_triggered_recently():
    h1h2 = _h1h2(h1=_trigger(), h2=_trigger(), days_since_h2_trigger=2)
    assert _resolve(h1h2_state=h1h2) == "H2_TRIGGERED_RECENTLY"


def test_h2_forming():
    h1h2 = _h1h2(h1=_trigger(), forming="h2")
    assert _resolve(h1h2_state=h1h2) == "H2_FORMING"


def test_h1_triggered_today():
    h1h2 = _h1h2(h1=_trigger(), days_since_h1_trigger=0)
    assert _resolve(h1h2_state=h1h2) == "H1_TRIGGERED_TODAY"


def test_h1_triggered_recently():
    h1h2 = _h1h2(h1=_trigger(), days_since_h1_trigger=2)
    assert _resolve(h1h2_state=h1h2) == "H1_TRIGGERED_RECENTLY"


def test_breakout_pullback():
    h1h2 = _h1h2(forming="h1")
    assert (
        _resolve(
            h1h2_state=h1h2,
            breakout_event=_breakout(idx=LATEST_IDX - 2),
            follow_through=_follow_through(retracement_pct=0.3),
        )
        == "BREAKOUT_PULLBACK"
    )


def test_h1_forming():
    h1h2 = _h1h2(forming="h1")
    assert _resolve(h1h2_state=h1h2) == "H1_FORMING"


def test_strong_breakout_today():
    assert _resolve(breakout_event=_breakout(idx=LATEST_IDX)) == "STRONG_BREAKOUT"


def test_strong_breakout_follow_through():
    assert (
        _resolve(
            breakout_event=_breakout(idx=LATEST_IDX - 2),
            follow_through=_follow_through(follow_through_score=0.6),
        )
        == "STRONG_BREAKOUT_FOLLOW_THROUGH"
    )


def test_wait_first_pullback():
    assert _resolve(market_cycle=_cycle("BULL_TREND"), entry_quality_score=3.0) == "WAIT_FIRST_PULLBACK"


def test_trading_range_fallback():
    assert _resolve() == "TRADING_RANGE"


def test_none_h1h2_state_and_none_breakout_do_not_crash():
    # every rule that touches h1h2_state/breakout_event must short-circuit
    # cleanly when either is None, rather than raise AttributeError.
    assert _resolve(h1h2_state=None, breakout_event=None, follow_through=None) == "TRADING_RANGE"


def test_triggered_h1_outranks_strong_breakout_follow_through():
    # Both conditions can be true at once (H1 triggers inside the
    # follow-through window) -- the more specific H1 signal must win.
    h1h2 = _h1h2(h1=_trigger(), days_since_h1_trigger=0)
    result = _resolve(
        h1h2_state=h1h2,
        breakout_event=_breakout(idx=LATEST_IDX - 2),
        follow_through=_follow_through(follow_through_score=0.6),
    )
    assert result == "H1_TRIGGERED_TODAY"
