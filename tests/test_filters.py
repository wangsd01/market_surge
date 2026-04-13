import logging

import numpy as np
import pandas as pd

from filters import apply_dollar_vol_filter, apply_price_filter, compute_bounce


def test_compute_bounce_happy_path():
    df_window = pd.DataFrame({"Low": [140.0, 100.0, 120.0]})
    bounce_pct = compute_bounce(df_window, current_close=160.0)
    assert bounce_pct == 60.0


def test_compute_bounce_zero_low_skips():
    df_window = pd.DataFrame({"Low": [120.0, 0.0, 80.0]})
    bounce_pct = compute_bounce(df_window, current_close=160.0)
    assert np.isnan(bounce_pct)


def test_compute_bounce_nan_current_skips():
    df_window = pd.DataFrame({"Low": [120.0, 100.0, 80.0]})
    bounce_pct = compute_bounce(df_window, current_close=np.nan)
    assert np.isnan(bounce_pct)


def test_compute_bounce_no_data_in_window():
    df_window = pd.DataFrame({"Low": []})
    bounce_pct = compute_bounce(df_window, current_close=160.0)
    assert np.isnan(bounce_pct)


def test_price_filter_drops_under_threshold():
    df = pd.DataFrame({"Ticker": ["AAA"], "current_price": [4.99]})
    filtered = apply_price_filter(df, min_price=5.0)
    assert filtered.empty


def test_price_filter_keeps_above_threshold():
    df = pd.DataFrame({"Ticker": ["AAA"], "current_price": [5.01]})
    filtered = apply_price_filter(df, min_price=5.0)
    assert list(filtered["Ticker"]) == ["AAA"]


def test_dollar_vol_filter_keeps_above_threshold():
    df = pd.DataFrame(
        {"Ticker": ["AAA"], "current_price": [3.0], "avg_vol_50d": [20_000_000]}
    )
    filtered = apply_dollar_vol_filter(df, min_dollar_vol=50_000_000)
    assert list(filtered["Ticker"]) == ["AAA"]


def test_dollar_vol_filter_drops_below_threshold():
    df = pd.DataFrame(
        {"Ticker": ["AAA"], "current_price": [4.0], "avg_vol_50d": [10_000_000]}
    )
    filtered = apply_dollar_vol_filter(df, min_dollar_vol=50_000_000)
    assert filtered.empty


def test_dollar_vol_insufficient_history():
    dates = pd.date_range("2026-04-01", periods=10, freq="D")
    df = pd.DataFrame(
        {
            "Date": dates,
            "Ticker": ["AAA"] * 10,
            "Volume": [5_000_000] * 10,
            "current_price": [12.0] * 10,
        }
    )
    filtered = apply_dollar_vol_filter(df, min_dollar_vol=50_000_000)
    assert list(filtered["Ticker"]) == ["AAA"]
    assert filtered["dollar_vol"].iloc[0] == 60_000_000


def test_sanity_check_extreme_bounce_logs_warning(caplog):
    df_window = pd.DataFrame({"Low": [100.0, 110.0], "Ticker": ["MOON", "MOON"]})

    with caplog.at_level(logging.WARNING):
        bounce_pct = compute_bounce(df_window, current_close=700.0)

    assert bounce_pct == 600.0
    assert any("MOON" in message for message in caplog.messages)
    assert any("extreme bounce" in message.lower() for message in caplog.messages)
