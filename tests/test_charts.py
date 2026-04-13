import numpy as np
import pytest
import plotly.graph_objects as go
from datetime import date

from patterns.base import PatternResult
from charts import chart


def _make_pattern(pattern: str = "cup_handle", confidence: float = 0.8) -> PatternResult:
    return PatternResult(
        pattern=pattern,
        ticker="TEST",
        confidence=confidence,
        detected_on=date(2025, 3, 31),
        pivots={"left_high": 110.0, "cup_low": 90.0, "handle_high": 108.0, "handle_low": 104.0},
        pivot_dates={
            "left_high": date(2025, 1, 10),
            "cup_low": date(2025, 2, 5),
            "handle_high": date(2025, 3, 20),
            "handle_low": date(2025, 3, 25),
        },
    )


def _make_sr_pattern() -> PatternResult:
    return PatternResult(
        pattern="support_resistance",
        ticker="TEST",
        confidence=1.0,
        detected_on=date(2025, 3, 31),
        pivots={"level_1": 95.0, "level_2": 105.0, "level_3": 115.0},
        pivot_dates={
            "level_1": date(2025, 3, 10),
            "level_2": date(2025, 3, 15),
            "level_3": date(2025, 3, 20),
        },
        metadata={"type_1": "support", "type_2": "resistance", "type_3": "resistance",
                  "touch_count_1": 3, "touch_count_2": 2, "touch_count_3": 2},
    )


class TestChart:

    def test_returns_figure(self, make_ohlcv):
        """chart() must return a plotly Figure."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        fig = chart("TEST", df, [], show=False)
        assert isinstance(fig, go.Figure)

    def test_has_at_least_two_traces(self, make_ohlcv):
        """Figure must have at least 2 traces: candlestick + volume."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        fig = chart("TEST", df, [], show=False)
        assert len(fig.data) >= 2

    def test_has_candlestick_trace(self, make_ohlcv):
        """First trace must be a Candlestick."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        fig = chart("TEST", df, [], show=False)
        trace_types = [type(t).__name__ for t in fig.data]
        assert "Candlestick" in trace_types

    def test_has_volume_bar_trace(self, make_ohlcv):
        """Figure must include a Bar trace for volume."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        fig = chart("TEST", df, [], show=False)
        trace_types = [type(t).__name__ for t in fig.data]
        assert "Bar" in trace_types

    def test_ticker_in_title(self, make_ohlcv):
        """Figure title must contain the ticker symbol."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        fig = chart("AAPL", df, [], show=False)
        title_text = fig.layout.title.text or ""
        assert "AAPL" in title_text

    def test_no_patterns_renders_without_annotations(self, make_ohlcv):
        """Empty patterns list must not crash and returns a valid figure."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        fig = chart("TEST", df, [], show=False)
        # Should still produce a complete figure
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 2

    def test_pattern_pivots_appear_in_annotations(self, make_ohlcv):
        """Annotations must contain pivot names from the pattern result."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        pattern = _make_pattern()
        fig = chart("TEST", df, [pattern], show=False)
        annotation_texts = [a.text for a in (fig.layout.annotations or [])]
        # At least one annotation should mention a pivot
        pivot_names = list(pattern.pivots.keys())
        found = any(
            any(pname in (txt or "") for pname in pivot_names)
            for txt in annotation_texts
        )
        assert found, f"No pivot name found in annotations: {annotation_texts}"

    def test_sr_levels_add_horizontal_lines(self, make_ohlcv):
        """S/R levels must be rendered as horizontal dashed lines (shapes or traces)."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        sr = _make_sr_pattern()
        fig = chart("TEST", df, [sr], show=False)
        # S/R levels can appear as shapes or as Scatter traces
        has_sr = len(fig.layout.shapes or []) > 0 or any(
            getattr(t, "name", "").startswith("level") for t in fig.data
        )
        assert has_sr, "No horizontal lines found for S/R levels"

    def test_show_false_does_not_call_show(self, make_ohlcv, monkeypatch):
        """show=False must not open a browser window."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        called = []
        monkeypatch.setattr(go.Figure, "show", lambda self, *a, **kw: called.append(1))
        chart("TEST", df, [], show=False)
        assert called == [], "fig.show() was called with show=False"

    def test_show_true_calls_show(self, make_ohlcv, monkeypatch):
        """show=True must call fig.show() exactly once."""
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        called = []
        monkeypatch.setattr(go.Figure, "show", lambda self, *a, **kw: called.append(1))
        chart("TEST", df, [], show=True)
        assert called == [1], "fig.show() was not called with show=True"

    def test_no_network_calls(self, make_ohlcv, monkeypatch):
        """chart() must not make any network calls."""
        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network call")),
        )
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = make_ohlcv(prices)
        chart("TEST", df, [], show=False)
