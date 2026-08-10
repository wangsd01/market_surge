import numpy as np
import pandas as pd

from brooks.config import BrooksConfig
from brooks.features import compute_features
from brooks.market_cycle import classify_market_cycle

_DATES = pd.date_range("2025-01-01", periods=45, freq="B")


def _sawtooth(n, start, up_step=2.0, up_bars=3, down_step=2.5, down_bars=2, direction=1):
    """3-up/2-down cycle: deep enough pullback for argrelextrema(order=3) to find
    genuine swing highs/lows even while the trend keeps climbing (a shallow 1-bar
    dip gets swallowed by the next leg's rise within the comparison window)."""
    closes = [start]
    cycle_len = up_bars + down_bars
    cycle_pos = 0
    while len(closes) < n:
        step = up_step if cycle_pos < up_bars else -down_step
        closes.append(closes[-1] + direction * step)
        cycle_pos = (cycle_pos + 1) % cycle_len
    return closes[:n]


def _flat_range(n, level, amp=2.0, period=8):
    return [level + amp * np.sin(i * 2 * np.pi / period) for i in range(n)]


def _build_df(closes, dates=_DATES):
    closes = np.array(closes)
    highs = closes * 1.01
    lows = closes * 0.99
    opens = [closes[i - 1] if i > 0 else closes[0] for i in range(len(closes))]
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": [1_000_000] * len(closes)},
        index=dates[: len(closes)],
    )


def _classify(closes, dates=_DATES):
    cfg = BrooksConfig()
    feat = compute_features(_build_df(closes, dates), cfg)
    return classify_market_cycle(feat, cfg), cfg


def test_zigzag_uptrend_classifies_bullish():
    result, _ = _classify(_sawtooth(45, start=100.0, direction=1))
    assert result.current_cycle in {"STRONG_BULL_TREND", "BULL_TREND"}


def test_zigzag_downtrend_classifies_bearish():
    result, _ = _classify(_sawtooth(45, start=150.0, direction=-1))
    assert result.current_cycle in {"STRONG_BEAR_TREND", "BEAR_TREND"}


def test_flat_oscillation_classifies_trading_range():
    result, _ = _classify(_flat_range(45, level=100.0))
    assert result.current_cycle in {"TRADING_RANGE", "BULLISH_TRADING_RANGE", "BEARISH_TRADING_RANGE"}


def test_mature_trading_range_discounts_bear_relevance_more_than_short():
    dates = pd.date_range("2025-01-01", periods=105, freq="B")

    bear_leg = _sawtooth(60, start=200.0, direction=-1)
    short_closes = bear_leg + _flat_range(8, level=bear_leg[-1])
    short_result, cfg = _classify(short_closes, dates[: len(short_closes)])

    long_closes = bear_leg + _flat_range(45, level=bear_leg[-1])
    long_result, _ = _classify(long_closes, dates[: len(long_closes)])

    assert short_result.prior_trend in {"BEAR_TREND", "STRONG_BEAR_TREND"}
    assert long_result.prior_trend in {"BEAR_TREND", "STRONG_BEAR_TREND"}
    assert short_result.bear_relevance == 1.0
    assert long_result.bear_relevance == cfg.mature_tr_bear_relevance_floor
    assert long_result.bear_relevance < short_result.bear_relevance
