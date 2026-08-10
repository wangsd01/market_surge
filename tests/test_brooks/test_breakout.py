import numpy as np
import pandas as pd

from brooks.config import BrooksConfig
from brooks.features import compute_features
from brooks.breakout import strong_bull_bar, extreme_bull_breakout, find_latest_breakout, follow_through


def _ohlcv(rows: list[dict]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=dates)[["Open", "High", "Low", "Close", "Volume"]]


def test_strong_bull_bar_true_for_wide_range_close_near_high():
    # 25 quiet bars (range 1, ATR settles at 1.0) then one wide, strong-close bull bar.
    rows = [
        {"Open": 100 + i * 0.1, "High": 100.5 + i * 0.1, "Low": 99.5 + i * 0.1, "Close": 100.2 + i * 0.1, "Volume": 1_000_000}
        for i in range(25)
    ]
    last_close = rows[-1]["Close"]
    rows.append({"Open": last_close, "High": last_close + 2.0, "Low": last_close - 0.1, "Close": last_close + 1.9, "Volume": 1_000_000})
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())

    assert strong_bull_bar(feat.iloc[-1], BrooksConfig()) is True


def test_strong_bull_bar_false_for_weak_close():
    rows = [
        {"Open": 100 + i * 0.1, "High": 100.5 + i * 0.1, "Low": 99.5 + i * 0.1, "Close": 100.2 + i * 0.1, "Volume": 1_000_000}
        for i in range(25)
    ]
    last_close = rows[-1]["Close"]
    # wide range but closes near the middle, not near the high
    rows.append({"Open": last_close, "High": last_close + 2.0, "Low": last_close - 2.0, "Close": last_close + 0.1, "Volume": 1_000_000})
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())

    assert strong_bull_bar(feat.iloc[-1], BrooksConfig()) is False


def test_extreme_bull_breakout_requires_clearing_recent_high():
    rows = [
        {"Open": 100 + i * 0.1, "High": 100.5 + i * 0.1, "Low": 99.5 + i * 0.1, "Close": 100.2 + i * 0.1, "Volume": 1_000_000}
        for i in range(25)
    ]
    last_close = rows[-1]["Close"]
    # extreme range/close-location bar, but it does NOT clear the recent 20d high
    rows.append({"Open": last_close - 5, "High": last_close, "Low": last_close - 5.2, "Close": last_close - 0.1, "Volume": 1_000_000})
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())

    assert extreme_bull_breakout(feat.iloc[-1], BrooksConfig()) is False


def _quiet_bars(n=25, start=100.0):
    return [
        {"Open": start + i * 0.1, "High": start + 0.5 + i * 0.1, "Low": start - 0.5 + i * 0.1, "Close": start + 0.2 + i * 0.1, "Volume": 1_000_000}
        for i in range(n)
    ]


def test_find_latest_breakout_picks_most_recent_qualifying_bar():
    rows = _quiet_bars()
    last_close = rows[-1]["Close"]
    breakout_row = {"Open": last_close, "High": last_close + 3.0, "Low": last_close - 0.1, "Close": last_close + 2.9, "Volume": 3_000_000}
    rows.append(breakout_row)
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())

    event = find_latest_breakout(feat, BrooksConfig())

    assert event is not None
    assert event.idx == len(feat) - 1
    assert event.is_strong is True


def test_find_latest_breakout_none_when_nothing_qualifies():
    rows = _quiet_bars()
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())

    assert find_latest_breakout(feat, BrooksConfig()) is None


def test_follow_through_positive_for_continued_strength():
    rows = _quiet_bars()
    last_close = rows[-1]["Close"]
    rows.append({"Open": last_close, "High": last_close + 3.0, "Low": last_close - 0.1, "Close": last_close + 2.9, "Volume": 3_000_000})
    breakout_close = rows[-1]["Close"]
    # Two small bull-closing bars that hold near the breakout bar's high without
    # exceeding it -- if they exceeded it, find_latest_breakout would (correctly)
    # pick one of them as a fresh breakout instead of the original bar.
    rows.append({"Open": breakout_close, "High": breakout_close + 0.05, "Low": breakout_close - 0.15, "Close": breakout_close + 0.03, "Volume": 500_000})
    rows.append({"Open": rows[-1]["Close"], "High": rows[-1]["Close"] + 0.05, "Low": rows[-1]["Close"] - 0.05, "Close": rows[-1]["Close"] + 0.04, "Volume": 500_000})
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())
    config = BrooksConfig()

    event = find_latest_breakout(feat, config)
    assert event is not None and event.idx == 25  # the breakout bar, not the confirmation bars
    result = follow_through(feat, event, config)

    assert result.follow_through_score is not None
    assert result.follow_through_score > 0
    assert result.retracement_pct < config.shallow_retracement_max


def test_follow_through_negative_and_full_retracement_for_hard_reversal():
    rows = _quiet_bars()
    last_close = rows[-1]["Close"]
    rows.append({"Open": last_close, "High": last_close + 3.0, "Low": last_close - 0.1, "Close": last_close + 2.9, "Volume": 3_000_000})
    breakout_close = rows[-1]["Close"]
    breakout_low = rows[-1]["Low"]
    # a large bear bar erasing the entire breakout bar's range and then some
    rows.append({"Open": breakout_close, "High": breakout_close + 0.1, "Low": breakout_low - 1.0, "Close": breakout_low - 0.9, "Volume": 3_000_000})
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())
    config = BrooksConfig()

    event = find_latest_breakout(feat, config)
    assert event is not None
    result = follow_through(feat, event, config)

    assert result.follow_through_score is not None
    assert result.follow_through_score < 0
    assert result.retracement_pct >= 1.0


def test_follow_through_score_none_when_breakout_is_todays_bar():
    rows = _quiet_bars()
    last_close = rows[-1]["Close"]
    rows.append({"Open": last_close, "High": last_close + 3.0, "Low": last_close - 0.1, "Close": last_close + 2.9, "Volume": 3_000_000})
    df = _ohlcv(rows)
    feat = compute_features(df, BrooksConfig())
    config = BrooksConfig()

    event = find_latest_breakout(feat, config)
    assert event is not None and event.idx == len(feat) - 1
    result = follow_through(feat, event, config)

    assert result.follow_through_score is None
    assert result.retracement_pct == 0.0  # always populated, even with no bars since breakout
