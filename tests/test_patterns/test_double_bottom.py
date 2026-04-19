from __future__ import annotations

import urllib.request

import numpy as np
import pandas as pd
import pytest

from patterns.base import PatternResult
from patterns.double_bottom import DoubleBottomDetector


def _build_ohlcv(closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None, volumes: list[int] | None = None) -> pd.DataFrame:
    close_arr = np.array(closes, dtype=float)
    high_arr = np.array(highs if highs is not None else [price * 1.01 for price in closes], dtype=float)
    low_arr = np.array(lows if lows is not None else [price * 0.99 for price in closes], dtype=float)
    open_arr = np.roll(close_arr, 1)
    open_arr[0] = close_arr[0]
    volume_arr = np.array(volumes if volumes is not None else [1_000_000] * len(closes), dtype=int)
    dates = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "Open": open_arr,
            "High": high_arr,
            "Low": low_arr,
            "Close": close_arr,
            "Volume": volume_arr,
        },
        index=dates,
    )


def _ibd_confirmed_df() -> pd.DataFrame:
    closes = (
        [100, 99, 97, 95, 92, 89, 85, 82, 79, 77]
        + [76, 75, 76, 78, 80]
        + [82, 84, 86, 88, 89, 88, 87, 86, 85, 84, 83, 82]
        + [82, 80, 78, 77, 76, 75, 74, 73, 72, 73]
        + [75, 78, 80, 83, 85, 87, 89, 90, 92, 93]
    )
    highs = list(closes)
    lows = [price - 1.0 for price in closes]
    highs[0] = 100.0
    lows[11] = 74.0
    highs[19] = 90.0
    lows[35] = 71.0
    highs[45] = 93.0
    volumes = [1_100_000] * len(closes)
    for idx in range(10, 13):
        volumes[idx] = 1_500_000
    for idx in range(34, 37):
        volumes[idx] = 900_000
    volumes[45] = 1_700_000
    return _build_ohlcv(closes, highs=highs, lows=lows, volumes=volumes)


def _ibd_pre_breakout_df() -> pd.DataFrame:
    closes = (
        [100, 99, 97, 95, 92, 89, 85, 82, 79, 77]
        + [76, 75, 76, 78, 80]
        + [82, 84, 86, 88, 89, 88, 87, 86, 85, 84, 83, 82]
        + [82, 80, 78, 77, 76, 75, 74, 73, 72, 73]
        + [75, 77, 79, 81, 82, 83, 84, 84, 83, 82]
    )
    highs = list(closes)
    lows = [price - 1.0 for price in closes]
    highs[0] = 100.0
    lows[11] = 74.0
    highs[19] = 90.0
    lows[35] = 71.0
    volumes = [1_050_000] * len(closes)
    for idx in range(10, 13):
        volumes[idx] = 1_450_000
    for idx in range(34, 37):
        volumes[idx] = 900_000
    return _build_ohlcv(closes, highs=highs, lows=lows, volumes=volumes)


def _internal_w_but_later_base_df() -> pd.DataFrame:
    closes = (
        [100, 98, 96, 94, 90, 86, 82, 79, 76, 75]
        + [76, 79, 83, 86, 88, 87, 85, 82, 79, 76]
        + [74, 75, 78, 82, 86, 89, 87, 84, 81, 78, 77, 76, 75]
        + [75, 73, 72, 73, 75, 78, 81, 84, 86, 88]
        + [90, 91, 92, 93, 94, 95]
    )
    highs = list(closes)
    lows = [price - 1.0 for price in closes]
    highs[0] = 100.0
    lows[9] = 74.0
    highs[14] = 89.0
    lows[20] = 73.0
    highs[25] = 90.0
    lows[35] = 71.0
    highs[43] = 91.0
    volumes = [1_100_000] * len(closes)
    for idx in range(8, 11):
        volumes[idx] = 1_500_000
    for idx in range(34, 37):
        volumes[idx] = 850_000
    volumes[43] = 1_600_000
    return _build_ohlcv(closes, highs=highs, lows=lows, volumes=volumes)


def _no_undercut_df() -> pd.DataFrame:
    closes = (
        [100, 99, 97, 95, 92, 89, 85, 82, 79, 77]
        + [76, 75, 76, 78, 80]
        + [82, 84, 86, 88, 89, 88, 87, 86, 85, 84, 83, 82]
        + [82, 80, 79, 78, 77, 76, 75, 76, 77, 78]
        + [80, 82, 84, 86, 87, 88, 89, 90, 91, 92]
    )
    highs = list(closes)
    lows = [price - 1.0 for price in closes]
    highs[0] = 100.0
    lows[11] = 74.0
    highs[19] = 90.0
    lows[35] = 75.0
    highs[46] = 91.0
    return _build_ohlcv(closes, highs=highs, lows=lows)


def _shallow_base_df() -> pd.DataFrame:
    closes = (
        [100, 99, 98, 97, 96, 95, 93, 91, 90, 89]
        + [88, 89, 90, 91, 92]
        + [93, 94, 95, 96, 97, 96, 95, 94, 93, 92]
        + [91, 90, 89, 88, 89, 90, 91, 92, 93, 94]
        + [95, 96, 97, 98, 99, 100, 101, 102, 103, 104]
    )
    highs = list(closes)
    lows = [price - 1.0 for price in closes]
    highs[0] = 100.0
    lows[10] = 87.0
    highs[19] = 97.0
    lows[30] = 87.5
    highs[40] = 98.0
    return _build_ohlcv(closes, highs=highs, lows=lows)


def _deep_base_df() -> pd.DataFrame:
    closes = (
        [100, 97, 93, 89, 84, 79, 74, 70, 66, 63]
        + [61, 60, 62, 65, 69]
        + [73, 77, 80, 83, 86, 84, 82, 79, 76, 73]
        + [70, 67, 65, 63, 61, 60, 59, 58, 57, 58]
        + [61, 65, 69, 73, 77, 81, 85, 88, 91, 93]
    )
    highs = list(closes)
    lows = [price - 1.0 for price in closes]
    highs[0] = 100.0
    lows[11] = 59.0
    highs[19] = 87.0
    lows[38] = 56.0
    highs[43] = 89.0
    return _build_ohlcv(closes, highs=highs, lows=lows)


def _short_base_df() -> pd.DataFrame:
    closes = (
        [100, 97, 93, 88, 84, 80, 77, 75]
        + [77, 80, 84, 88, 86, 83, 79, 75]
        + [72, 74, 78, 82, 86, 89, 91, 92]
    )
    highs = list(closes)
    lows = [price - 1.0 for price in closes]
    highs[0] = 100.0
    lows[7] = 74.0
    highs[11] = 89.0
    lows[16] = 71.0
    highs[22] = 90.0
    return _build_ohlcv(closes, highs=highs, lows=lows)


class TestDoubleBottomDetector:
    def test_detects_valid_ibd_confirmed_double_bottom(self):
        df = _ibd_confirmed_df()

        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is not None
        assert isinstance(result, PatternResult)
        assert result.pattern == "double_bottom"
        assert result.pivots["left_high"] == 100.0
        assert result.pivots["first_trough"] == 74.0
        assert result.pivots["middle_high"] == 90.0
        assert result.pivots["second_trough"] == 71.0
        assert "breakout" in result.pivots
        assert result.pivot_dates["breakout"] == df.index[45].date()
        assert result.metadata["state"] == "confirmed"
        assert result.metadata["buy_point"] == 90.0
        assert result.metadata["base_length_bdays"] >= 35
        assert result.metadata["base_depth_pct"] == pytest.approx(0.29, rel=1e-3)
        assert result.metadata["undercut_pct"] == pytest.approx((74.0 - 71.0) / 74.0, rel=1e-3)

    def test_detects_active_pre_breakout_double_bottom_within_ten_percent_of_buy_point(self):
        df = _ibd_pre_breakout_df()

        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is not None
        assert result.metadata["state"] == "active_pre_breakout"
        assert result.pivots["middle_high"] == 90.0
        assert "breakout" not in result.pivots
        assert result.metadata["active_zone_pct_below_buy_point"] == pytest.approx((90.0 - 82.0) / 90.0, rel=1e-3)

    def test_prefers_later_broader_base_over_internal_w(self):
        df = _internal_w_but_later_base_df()

        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is not None
        assert result.pivots["first_trough"] == 74.0
        assert result.pivots["middle_high"] == 90.0
        assert result.pivots["second_trough"] == 71.0
        assert result.pivot_dates["second_trough"] == df.index[35].date()

    def test_rejects_second_trough_that_does_not_undercut_first(self):
        df = _no_undercut_df()

        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is None

    def test_rejects_base_that_is_too_shallow(self):
        df = _shallow_base_df()

        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is None

    def test_rejects_base_that_is_too_deep(self):
        df = _deep_base_df()

        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is None

    def test_rejects_base_shorter_than_seven_weeks(self):
        df = _short_base_df()

        result = DoubleBottomDetector().detect(df, "TEST")

        assert result is None

    def test_no_network_calls(self, monkeypatch):
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call detected")),
        )

        DoubleBottomDetector().detect(_ibd_confirmed_df(), "TEST")
