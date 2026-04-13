"""Integration tests for Phase 5: --patterns, --chart, --strategy CLI flags.

Tests cover the new helper functions added to screener.py without making
any network calls (uses make_ohlcv fixture and monkeypatching).
"""
import numpy as np
import pytest
import pandas as pd
from datetime import date

from patterns.base import PatternResult
import screener


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_df(tickers: list[str], n_days: int = 90, make_ohlcv_fn=None) -> pd.DataFrame:
    """Build a fake raw_df with multiple tickers in long format."""
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    rows = []
    for ticker in tickers:
        prices = [100.0 + i * 0.1 for i in range(n_days)]
        for i, d in enumerate(dates):
            rows.append({
                "Ticker": ticker,
                "Date": d,
                "Open": prices[i],
                "High": prices[i] * 1.005,
                "Low": prices[i] * 0.995,
                "Close": prices[i],
                "Volume": 1_000_000,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParserNewFlags:

    def test_patterns_flag_exists(self):
        """--patterns flag must be registered in the argument parser."""
        parser = screener.build_parser()
        args = parser.parse_args(["--patterns"])
        assert args.patterns is True

    def test_patterns_flag_default_false(self):
        """--patterns must default to False when not supplied."""
        parser = screener.build_parser()
        args = parser.parse_args([])
        assert args.patterns is False

    def test_chart_flag_exists(self):
        """--chart TICKER flag must be registered."""
        parser = screener.build_parser()
        args = parser.parse_args(["--chart", "AAPL"])
        assert args.chart == "AAPL"

    def test_chart_flag_default_none(self):
        """--chart must default to None when not supplied."""
        parser = screener.build_parser()
        args = parser.parse_args([])
        assert args.chart is None

    def test_strategy_flag_exists(self):
        """--strategy TICKER flag must be registered."""
        parser = screener.build_parser()
        args = parser.parse_args(["--strategy", "AAPL"])
        assert args.strategy == "AAPL"

    def test_strategy_flag_default_none(self):
        """--strategy must default to None when not supplied."""
        parser = screener.build_parser()
        args = parser.parse_args([])
        assert args.strategy is None


# ---------------------------------------------------------------------------
# _slice_for_patterns helper
# ---------------------------------------------------------------------------

class TestSliceForPatterns:

    def test_returns_dataframe_for_known_ticker(self):
        """_slice_for_patterns must return a DataFrame for a ticker in raw_df."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._slice_for_patterns("AAPL", raw_df)
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_returns_none_for_unknown_ticker(self):
        """_slice_for_patterns returns None when ticker not in raw_df."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._slice_for_patterns("MSFT", raw_df)
        assert result is None

    def test_slices_to_at_most_90_days(self):
        """_slice_for_patterns must return at most 90 rows."""
        raw_df = _make_raw_df(["AAPL"], n_days=120)
        result = screener._slice_for_patterns("AAPL", raw_df)
        assert result is not None
        assert len(result) <= 90

    def test_result_has_ohlcv_columns(self):
        """Returned DataFrame must have Open, High, Low, Close, Volume columns."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._slice_for_patterns("AAPL", raw_df)
        assert result is not None
        for col in ("Open", "High", "Low", "Close", "Volume"):
            assert col in result.columns, f"missing column: {col}"

    def test_result_has_datetime_index(self):
        """Returned DataFrame must have a DatetimeIndex."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._slice_for_patterns("AAPL", raw_df)
        assert result is not None
        assert isinstance(result.index, pd.DatetimeIndex)


# ---------------------------------------------------------------------------
# _run_patterns helper
# ---------------------------------------------------------------------------

class TestRunPatterns:

    def test_returns_dict_keyed_by_ticker(self):
        """_run_patterns must return a dict mapping ticker -> list[PatternResult]."""
        raw_df = _make_raw_df(["AAPL", "MSFT"])
        result = screener._run_patterns(["AAPL", "MSFT"], raw_df)
        assert isinstance(result, dict)
        assert "AAPL" in result
        assert "MSFT" in result

    def test_each_value_is_list(self):
        """Each dict value must be a list (possibly empty)."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._run_patterns(["AAPL"], raw_df)
        assert isinstance(result["AAPL"], list)

    def test_pattern_results_are_pattern_result_instances(self):
        """Any detected patterns must be PatternResult instances."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._run_patterns(["AAPL"], raw_df)
        for pr in result["AAPL"]:
            assert isinstance(pr, PatternResult)

    def test_missing_ticker_returns_empty_list(self):
        """Ticker not in raw_df should return an empty list (not crash)."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._run_patterns(["MISSING"], raw_df)
        assert result["MISSING"] == []

    def test_no_network_calls(self, monkeypatch):
        """_run_patterns must not make any network calls."""
        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network call")),
        )
        raw_df = _make_raw_df(["AAPL"])
        screener._run_patterns(["AAPL"], raw_df)
