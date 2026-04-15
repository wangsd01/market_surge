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
        """_slice_for_patterns must return at most the configured pattern lookback."""
        raw_df = _make_raw_df(["AAPL"], n_days=screener.PATTERN_LOOKBACK_DAYS + 30)
        result = screener._slice_for_patterns("AAPL", raw_df)
        assert result is not None
        assert len(result) <= screener.PATTERN_LOOKBACK_DAYS

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


# ---------------------------------------------------------------------------
# _handle_chart helper
# ---------------------------------------------------------------------------

class TestHandleChart:

    def test_returns_figure_for_known_ticker(self):
        """_handle_chart must return a plotly Figure for a ticker in raw_df."""
        import plotly.graph_objects as go
        raw_df = _make_raw_df(["AAPL"])
        fig = screener._handle_chart("AAPL", raw_df, show=False)
        assert isinstance(fig, go.Figure)

    def test_returns_none_for_unknown_ticker(self):
        """_handle_chart returns None when ticker not in raw_df."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._handle_chart("MISSING", raw_df, show=False)
        assert result is None

    def test_show_false_does_not_open_browser(self, monkeypatch):
        """_handle_chart(show=False) must not call fig.show()."""
        import plotly.graph_objects as go
        called = []
        monkeypatch.setattr(go.Figure, "show", lambda self, *a, **kw: called.append(1))
        raw_df = _make_raw_df(["AAPL"])
        screener._handle_chart("AAPL", raw_df, show=False)
        assert called == []


# ---------------------------------------------------------------------------
# _handle_strategy helper
# ---------------------------------------------------------------------------

class TestHandleStrategy:

    def test_returns_list_for_known_ticker(self):
        """_handle_strategy must return a list for a ticker in raw_df."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._handle_strategy("AAPL", raw_df)
        assert isinstance(result, list)

    def test_returns_empty_list_for_unknown_ticker(self):
        """_handle_strategy returns [] when ticker not in raw_df."""
        raw_df = _make_raw_df(["AAPL"])
        result = screener._handle_strategy("MISSING", raw_df)
        assert result == []

    def test_each_item_is_trade_setup(self):
        """Each item in the result list must be a TradeSetup."""
        from strategies import TradeSetup
        raw_df = _make_raw_df(["AAPL"])
        result = screener._handle_strategy("AAPL", raw_df)
        for item in result:
            assert isinstance(item, TradeSetup)

    def test_invalid_support_resistance_setup_is_skipped(self, monkeypatch):
        """Invalid S/R patterns should not crash strategy rendering."""
        raw_df = _make_raw_df(["AAPL"])
        invalid_sr = PatternResult(
            pattern="support_resistance",
            ticker="AAPL",
            confidence=1.0,
            detected_on=date(2025, 3, 31),
            pivots={"level_1": 90.0, "level_2": 95.0, "level_3": 100.0},
            pivot_dates={
                "level_1": date(2025, 3, 1),
                "level_2": date(2025, 3, 2),
                "level_3": date(2025, 3, 3),
            },
            metadata={"type_1": "support", "type_2": "support", "type_3": "support"},
        )
        monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [invalid_sr])

        result = screener._handle_strategy("AAPL", raw_df)

        assert result == []


# ---------------------------------------------------------------------------
# run() dispatch tests (monkeypatched fetch_data)
# ---------------------------------------------------------------------------

def _fake_fetch_data(*args, **kwargs):
    return _make_raw_df(["AAPL", "MSFT"])


def _make_run_args(**overrides):
    """Build a minimal Namespace that run() accepts."""
    import argparse
    defaults = dict(
        low_start="2025-01-01", low_end="2025-04-30",
        min_price=5.0, min_dollar_vol=1.0, top=5,
        universe="all", refresh=False, schedule=False,
        output=None, sort="bounce", benchmark_mode="any",
        exclude_sections="none", min_pct_of_52wk_high=0.0,
        patterns=False, chart=None, strategy=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestRunDispatch:

    def test_chart_flag_calls_handle_chart(self, monkeypatch, tmp_path):
        """run(--chart AAPL) must call _handle_chart with the right ticker."""
        called = []
        monkeypatch.setattr(screener, "_select_universe", lambda _universe: [])
        monkeypatch.setattr(screener, "fetch_data", _fake_fetch_data)
        monkeypatch.setattr(screener, "_handle_chart",
                            lambda ticker, raw_df, show=True: called.append(ticker) or None)
        args = _make_run_args(chart="AAPL")
        screener.run(args)
        assert "AAPL" in called

    def test_strategy_flag_calls_handle_strategy(self, monkeypatch):
        """run(--strategy AAPL) must call _handle_strategy with the right ticker."""
        called = []
        monkeypatch.setattr(screener, "_select_universe", lambda _universe: [])
        monkeypatch.setattr(screener, "fetch_data", _fake_fetch_data)
        monkeypatch.setattr(screener, "_handle_strategy",
                            lambda ticker, raw_df: called.append(ticker) or [])
        args = _make_run_args(strategy="AAPL")
        screener.run(args)
        assert "AAPL" in called

    def test_patterns_flag_calls_run_patterns(self, monkeypatch):
        """run(--patterns) must call _run_patterns after screening."""
        called = []
        monkeypatch.setattr(screener, "_select_universe", lambda _universe: [])
        monkeypatch.setattr(screener, "fetch_data", _fake_fetch_data)
        monkeypatch.setattr(screener, "_run_patterns",
                            lambda tickers, raw_df: called.append(tickers) or {t: [] for t in tickers})
        args = _make_run_args(patterns=True)
        screener.run(args)
        assert called, "_run_patterns was not called"
