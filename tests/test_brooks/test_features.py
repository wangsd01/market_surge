import numpy as np
import pandas as pd

from brooks.config import BrooksConfig
from brooks.features import compute_features


def _ohlcv(rows: list[dict]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=dates)[["Open", "High", "Low", "Close", "Volume"]]


def test_gap_pct_and_true_gap_up():
    df = _ohlcv(
        [
            {"Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 1_000_000},
            {"Open": 105, "High": 106, "Low": 104, "Close": 105, "Volume": 1_000_000},
            {"Open": 105, "High": 107, "Low": 103, "Close": 106, "Volume": 1_000_000},
        ]
    )

    out = compute_features(df, BrooksConfig())

    assert np.isnan(out["gap_pct"].iloc[0])
    assert out["true_gap_up"].iloc[0] == False  # noqa: E712

    assert out["gap_pct"].iloc[1] == 0.05
    assert out["true_gap_up"].iloc[1] == True  # noqa: E712

    assert out["gap_pct"].iloc[2] == 0.0
    assert out["true_gap_up"].iloc[2] == False  # noqa: E712


def test_zero_range_bar_produces_nan_not_crash():
    df = _ohlcv(
        [
            {"Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1_000_000},
            {"Open": 100, "High": 102, "Low": 98, "Close": 101, "Volume": 1_000_000},
        ]
    )

    out = compute_features(df, BrooksConfig())

    assert np.isnan(out["body_pct"].iloc[0])
    assert np.isnan(out["close_location"].iloc[0])
    assert out["body_pct"].iloc[1] == 0.25
    assert out["close_location"].iloc[1] == 0.75


def test_atr_and_range_atr_ratio():
    closes = [100, 101] * 8  # alternating -> constant true_range == 2 after bar 0
    rows = [
        {"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1_000_000}
        for c in closes
    ]
    df = _ohlcv(rows)

    out = compute_features(df, BrooksConfig())

    assert np.isnan(out["atr14"].iloc[12])  # fewer than 14 true_range values so far
    assert out["atr14"].iloc[14] == 2.0
    assert out["range_atr_ratio"].iloc[14] == 1.0


def test_recent_high_excludes_current_bar():
    highs = [100, 105, 103, 102, 110]
    rows = [
        {"Open": h - 2, "High": h, "Low": h - 3, "Close": h - 1, "Volume": 1_000_000}
        for h in highs
    ]
    df = _ohlcv(rows)

    out = compute_features(df, BrooksConfig())

    # recent_high_20 at the last bar (High=110) must be 105 (max of bars 0-3),
    # not 110 (its own high) -- otherwise a breakout bar could never clear it.
    assert out["recent_high_20"].iloc[4] == 105
    assert np.isnan(out["recent_high_20"].iloc[0])  # no prior bars yet
