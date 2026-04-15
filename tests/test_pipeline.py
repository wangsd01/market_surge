from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipeline import ScreeningArtifacts, build_screening_artifacts


def _make_raw_df(prices_by_ticker: dict[str, list[float]]) -> pd.DataFrame:
    dates = pd.date_range("2026-03-20", periods=len(next(iter(prices_by_ticker.values()))), freq="B")
    rows: list[dict[str, object]] = []
    for ticker, prices in prices_by_ticker.items():
        for date, close in zip(dates, prices, strict=True):
            rows.append(
                {
                    "Ticker": ticker,
                    "Date": date,
                    "Open": close,
                    "High": close * 1.005,
                    "Low": close * 0.995,
                    "Close": close,
                    "Volume": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def test_build_screening_artifacts_returns_shared_stage1_bundle(monkeypatch, tmp_path):
    raw_df = _make_raw_df(
        {
            "AAA": [10.0, 10.5, 11.0, 11.5, 12.0],
            "QLD": [10.0, 10.1, 10.2, 10.3, 10.4],
            "TQQQ": [10.0, 10.05, 10.1, 10.15, 10.2],
        }
    )
    seen: dict[str, object] = {}

    def _fake_fetch_data(**kwargs):
        seen.update(kwargs)
        return raw_df.copy()

    monkeypatch.setattr("pipeline._today_market_date", lambda: pd.Timestamp("2026-04-12").date())
    monkeypatch.setattr("pipeline.get_tickers", lambda: ["AAA"])
    monkeypatch.setattr("pipeline.fetch_data", _fake_fetch_data)
    monkeypatch.setattr(
        "pipeline.get_ticker_metadata",
        lambda tickers, db_path, refresh: {
            "AAA": {"sector": "Technology", "industry": "Software"},
            "QLD": {"sector": "ETF", "industry": "Leveraged Equity"},
            "TQQQ": {"sector": "ETF", "industry": "Leveraged Equity"},
        },
    )

    artifacts = build_screening_artifacts(
        universe="all",
        low_start="2026-03-20",
        low_end="2026-04-11",
        refresh=False,
        benchmark_mode="all",
        needs_pattern_history=False,
        cache_dir=tmp_path / "cache",
        db_path=tmp_path / "market_surge.db",
    )

    assert isinstance(artifacts, ScreeningArtifacts)
    assert set(artifacts.raw_df["Ticker"]) == {"AAA", "QLD", "TQQQ"}
    assert set(artifacts.summary_all["Ticker"]) == {"AAA", "QLD", "TQQQ"}
    assert list(artifacts.summary["Ticker"]) == ["AAA"]
    assert artifacts.benchmark_bounces["QLD"] == pytest.approx(4.522613065326644)
    assert artifacts.summary_all.loc[artifacts.summary_all["Ticker"] == "AAA", "sector"].iloc[0] == "Technology"
    assert seen["tickers"] == ["AAA", "QLD", "TQQQ"]
    assert seen["low_start"] == "2026-03-20"
    assert seen["end_date"] == "2026-04-12"
    assert seen["cache_dir"] == Path(tmp_path / "cache")
    assert seen["db_path"] == Path(tmp_path / "market_surge.db")


def test_build_screening_artifacts_extends_fetch_start_for_pattern_history(monkeypatch, tmp_path):
    seen: dict[str, object] = {}

    def _fake_fetch_data(**kwargs):
        seen.update(kwargs)
        return pd.DataFrame(
            columns=["Ticker", "Date", "Open", "High", "Low", "Close", "Volume"]
        )

    monkeypatch.setattr("pipeline._today_market_date", lambda: pd.Timestamp("2026-04-12").date())
    monkeypatch.setattr("pipeline.get_sp500_tickers", lambda **_kwargs: ["AAA"])
    monkeypatch.setattr("pipeline.fetch_data", _fake_fetch_data)
    monkeypatch.setattr("pipeline.get_ticker_metadata", lambda tickers, db_path, refresh: {})

    build_screening_artifacts(
        universe="sp500",
        low_start="2026-03-30",
        low_end="2026-04-11",
        refresh=False,
        benchmark_mode="any",
        needs_pattern_history=True,
        cache_dir=tmp_path / "cache",
        db_path=tmp_path / "market_surge.db",
    )

    assert seen["low_start"] == "2025-08-05"
