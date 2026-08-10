import pandas as pd

from brooks.config import BrooksConfig
from brooks.features import compute_features
from brooks.h1h2 import TriggerEvent, H1H2State
from brooks.extension import is_extended


def _quiet_then_bars(extra_rows: list[dict], n_quiet=25, start=100.0):
    rows = [
        {"Open": start + i * 0.1, "High": start + 0.5 + i * 0.1, "Low": start - 0.5 + i * 0.1, "Close": start + 0.2 + i * 0.1, "Volume": 1_000_000}
        for i in range(n_quiet)
    ]
    rows.extend(extra_rows)
    dates = pd.date_range("2025-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=dates)[["Open", "High", "Low", "Close", "Volume"]]


def _h1_state_with_trigger(trigger_date, trigger_price) -> H1H2State:
    trigger = TriggerEvent(
        signal_date=trigger_date, trigger_date=trigger_date, trigger_price=trigger_price,
        signal_bar_low=trigger_price - 1, signal_bar_high=trigger_price, pullback_leg_low=trigger_price - 1,
    )
    return H1H2State(
        h1=trigger, h2=None, h1_failed=False, h2_failed=False, h1_structural_failed=False,
        h2_structural_failed=False, days_since_h1_trigger=0, days_since_h2_trigger=None,
        forming=None, reset_from_failure=False, prior_failed_pattern=None,
    )


def test_extended_after_three_consecutive_strong_bull_bars_past_trigger():
    trigger_close = 100 + 24 * 0.1 + 0.2
    extra = [
        {"Open": trigger_close, "High": trigger_close + 0.05, "Low": trigger_close - 0.05, "Close": trigger_close + 0.04, "Volume": 1_000_000}
    ]
    for _ in range(3):
        c = extra[-1]["Close"]
        extra.append({"Open": c, "High": c + 2.0, "Low": c - 0.05, "Close": c + 1.9, "Volume": 2_000_000})
    df = _quiet_then_bars(extra)
    feat = compute_features(df, BrooksConfig())
    config = BrooksConfig()

    trigger_date = feat.index[25].date()
    h1h2_state = _h1_state_with_trigger(trigger_date, trigger_close)

    result = is_extended(feat, h1h2_state, breakout_event=None, config=config)

    assert result.is_extended is True
    assert result.reason == "consecutive_strong_bull_bars"


def test_not_extended_with_single_strong_bar():
    trigger_close = 100 + 24 * 0.1 + 0.2
    extra = [
        {"Open": trigger_close, "High": trigger_close + 0.3, "Low": trigger_close - 0.05, "Close": trigger_close + 0.25, "Volume": 1_000_000}
    ]
    df = _quiet_then_bars(extra)
    feat = compute_features(df, BrooksConfig())
    config = BrooksConfig()

    trigger_date = feat.index[25].date()
    h1h2_state = _h1_state_with_trigger(trigger_date, trigger_close)

    result = is_extended(feat, h1h2_state, breakout_event=None, config=config)

    assert result.is_extended is False
    assert result.reason is None


def test_not_extended_when_no_trigger_or_breakout_reference():
    df = _quiet_then_bars([])
    feat = compute_features(df, BrooksConfig())
    config = BrooksConfig()

    result = is_extended(feat, h1h2_state=None, breakout_event=None, config=config)

    assert result.is_extended is False
