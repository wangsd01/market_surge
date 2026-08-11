import numpy as np
import pandas as pd

from brooks.breakout import BreakoutEvent
from brooks.config import BrooksConfig
from brooks.h1h2 import TriggerEvent, H1H2State
from brooks.stops_targets import compute_stops, compute_targets


def _h1_state(signal_bar_low, pullback_leg_low) -> H1H2State:
    trigger = TriggerEvent(
        signal_date=pd.Timestamp("2025-01-10").date(),
        trigger_date=pd.Timestamp("2025-01-11").date(),
        trigger_price=105.0,
        signal_bar_low=signal_bar_low,
        signal_bar_high=104.5,
        pullback_leg_low=pullback_leg_low,
    )
    return H1H2State(
        h1=trigger, h2=None, h1_failed=False, h2_failed=False, h1_structural_failed=False,
        h2_structural_failed=False, days_since_h1_trigger=0, days_since_h2_trigger=None,
        forming=None, reset_from_failure=False, prior_failed_pattern=None,
    )


def test_structural_stop_uses_pullback_leg_low_not_signal_bar_low():
    config = BrooksConfig()
    h1h2_state = _h1_state(signal_bar_low=100.0, pullback_leg_low=97.0)

    stops = compute_stops(h1h2_state, breakout_event=None, config=config)

    assert stops.tight_stop == 100.0 * (1 - config.stop_buffer_pct)
    assert stops.structural_stop == 97.0 * (1 - config.stop_buffer_pct)
    assert stops.structural_stop < stops.tight_stop


def _ohlcv_with_resistance_shelf():
    # A clear untouched swing high (108) sits above a later pullback/consolidation
    # near 102-103, so nearest_resistance above current price should land on 108.
    rows = []
    for i in range(20):
        c = 100 + i * 0.4
        rows.append({"Open": c, "High": c + 0.5, "Low": c - 0.5, "Close": c, "Volume": 1_000_000})
    # sharp swing high
    rows.append({"Open": 107, "High": 108, "Low": 106.5, "Close": 107.5, "Volume": 1_000_000})
    for i in range(15):
        c = 107.5 - i * 0.35
        rows.append({"Open": c, "High": c + 0.4, "Low": c - 0.4, "Close": c, "Volume": 1_000_000})
    dates = pd.date_range("2025-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=dates)[["Open", "High", "Low", "Close", "Volume"]]


def test_nearest_resistance_delegates_to_support_resistance_detector():
    df = _ohlcv_with_resistance_shelf()
    config = BrooksConfig()
    current_price = float(df["Close"].iloc[-1])
    entry = current_price * 1.0005
    structural_stop = current_price * 0.95

    targets = compute_targets(df, ticker="TEST", current_price=current_price, structural_stop=structural_stop, entry=entry, config=config)

    assert targets.nearest_resistance is not None
    assert targets.nearest_resistance > current_price
    assert targets.target_1 == targets.nearest_resistance


def test_low_reward_risk_setup_flagged_below_min_plausible_rr():
    df = _ohlcv_with_resistance_shelf()
    config = BrooksConfig()
    current_price = float(df["Close"].iloc[-1])
    # entry sits just below the resistance shelf (~108) and the stop is far away,
    # so target_1 (the resistance) barely clears entry relative to the wide risk.
    entry = 107.9
    structural_stop = 95.0

    targets = compute_targets(df, ticker="TEST", current_price=current_price, structural_stop=structural_stop, entry=entry, config=config)

    assert targets.rr_target_1 < config.min_plausible_rr


def _breakout_event(breakout_level, low, prior_high=None, true_gap_up=False):
    return BreakoutEvent(
        idx=10, date=pd.Timestamp("2025-01-10").date(), breakout_score=0.7, is_strong=True, is_extreme=False,
        breakout_level=breakout_level, low=low, prior_high=prior_high, gap_pct=0.02,
        true_gap_up=true_gap_up, volume_ratio=1.6,
    )


def test_breakout_bar_stop_uses_the_bars_actual_low_not_breakout_level():
    # breakout_level (the resistance cleared) sits far above the breakout
    # bar's own low -- a real chart, not the pathological case where they'd
    # coincidentally be close.
    config = BrooksConfig()
    breakout_event = _breakout_event(breakout_level=150.0, low=95.0)

    stops = compute_stops(h1h2_state=None, breakout_event=breakout_event, config=config)

    assert stops.breakout_bar_stop == 95.0 * (1 - config.stop_buffer_pct)
    assert stops.structural_stop == stops.breakout_bar_stop
    # the bug this guards against: stop must not be derived from
    # breakout_level, which sits right next to the entry (also derived from
    # breakout_level) and produces a near-zero, meaningless risk distance.
    assert stops.breakout_bar_stop != 150.0 * (1 - config.stop_buffer_pct)


def test_breakout_only_setup_has_meaningful_risk_not_near_zero():
    config = BrooksConfig()
    breakout_event = _breakout_event(breakout_level=150.0, low=95.0)
    entry = breakout_event.breakout_level * (1 + config.signal_bar_break_buffer_pct)

    stops = compute_stops(h1h2_state=None, breakout_event=breakout_event, config=config)
    risk_pct = (entry - stops.structural_stop) / entry

    assert risk_pct > 0.10  # a real structural stop, not the ~0.1% the bug produced


def test_gap_failure_stop_uses_prior_bar_high_not_breakout_level():
    config = BrooksConfig()
    breakout_event = _breakout_event(breakout_level=150.0, low=95.0, prior_high=120.0, true_gap_up=True)

    stops = compute_stops(h1h2_state=None, breakout_event=breakout_event, config=config)

    assert stops.gap_failure_stop == 120.0 * (1 - config.stop_buffer_pct)
