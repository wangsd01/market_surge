import math

import pandas as pd

from screener import _apply_benchmark_filter, _apply_section_filter, _attach_metadata, _compute_benchmark_bounces, build_parser
from screener import _build_csv_ranking
from screener import PATTERN_LOOKBACK_DAYS
from screener import _with_reference_tickers
from screener import _format_csv_ranking_for_output
from screener import _parse_excluded_sections
from screener import run


def test_compute_benchmark_bounces_for_default_reference_etfs():
    raw_df = pd.DataFrame(
        {
            "Date": pd.to_datetime(
                [
                    "2026-03-20",
                    "2026-04-10",
                    "2026-03-20",
                    "2026-04-10",
                    "2026-03-20",
                    "2026-04-10",
                ]
            ),
            "Ticker": ["QQQ", "QQQ", "QLD", "QLD", "TQQQ", "TQQQ"],
            "Low": [100.0, 110.0, 50.0, 60.0, 20.0, 30.0],
            "Close": [110.0, 120.0, 55.0, 70.0, 25.0, 35.0],
            "Volume": [1_000_000] * 6,
        }
    )

    bounces = _compute_benchmark_bounces(raw_df, low_start="2026-03-15", low_end="2026-04-05")

    assert set(bounces.keys()) == {"QLD", "TQQQ"}
    assert bounces["QLD"] == 40.0
    assert bounces["TQQQ"] == 75.0


def test_apply_benchmark_filter_keeps_only_stronger_than_strictest_reference():
    df = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB", "CCC", "QQQ"],
            "bounce_pct": [80.0, 76.0, 75.0, 20.0],
        }
    )
    benchmark_bounces = {"QLD": 40.0, "TQQQ": 75.0}

    filtered = _apply_benchmark_filter(df, benchmark_bounces, mode="all")

    assert list(filtered["Ticker"]) == ["AAA", "BBB"]


def test_apply_benchmark_filter_with_no_valid_reference_is_noop():
    df = pd.DataFrame({"Ticker": ["AAA", "BBB"], "bounce_pct": [10.0, 20.0]})
    benchmark_bounces = {"QLD": math.nan, "TQQQ": math.nan}

    filtered = _apply_benchmark_filter(df, benchmark_bounces, mode="all")

    pd.testing.assert_frame_equal(filtered.reset_index(drop=True), df.reset_index(drop=True))


def test_apply_benchmark_filter_any_mode_uses_weakest_reference():
    df = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB", "CCC", "DDD"],
            "bounce_pct": [19.0, 21.0, 41.0, 80.0],
        }
    )
    benchmark_bounces = {"QLD": 40.0, "TQQQ": 75.0}

    filtered = _apply_benchmark_filter(df, benchmark_bounces, mode="any")

    assert list(filtered["Ticker"]) == ["CCC", "DDD"]


def test_apply_benchmark_filter_specific_mode_uses_selected_reference():
    df = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB", "CCC"],
            "bounce_pct": [39.0, 41.0, 80.0],
        }
    )
    benchmark_bounces = {"QLD": 40.0, "TQQQ": 75.0}

    filtered = _apply_benchmark_filter(df, benchmark_bounces, mode="qld")

    assert list(filtered["Ticker"]) == ["BBB", "CCC"]


def test_build_parser_supports_benchmark_mode_arg():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.benchmark_mode == "any"
    assert args.output == "ranking_all.csv"
    assert args.exclude_sections == "biotechnology"

    args = parser.parse_args(["--benchmark-mode", "qld"])
    assert args.benchmark_mode == "qld"


def test_parse_excluded_sections_supports_none():
    assert _parse_excluded_sections("none") == set()
    assert _parse_excluded_sections(" biotechnology , healthcare ") == {"biotechnology", "healthcare"}


def test_apply_section_filter_drops_excluded_section_case_insensitive():
    df = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB", "CCC"],
            "sector": ["Healthcare", "Technology", "Healthcare"],
            "industry": ["Biotechnology", "Software", "biotechnology"],
            "bounce_pct": [50.0, 45.0, 60.0],
        }
    )
    filtered = _apply_section_filter(df, {"biotechnology"})
    assert list(filtered["Ticker"]) == ["BBB"]


def test_attach_metadata_fills_sector_and_industry():
    df = pd.DataFrame({"Ticker": ["AAA", "BBB"]})
    metadata = {
        "AAA": {"sector": "Technology", "industry": "Software"},
        "BBB": {"sector": "Healthcare", "industry": "Biotechnology"},
    }

    out = _attach_metadata(df, metadata)

    assert list(out["sector"]) == ["Technology", "Healthcare"]
    assert list(out["industry"]) == ["Software", "Biotechnology"]


def test_build_csv_ranking_includes_reference_tickers_and_sorts_desc():
    filtered = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB"],
            "bounce_pct": [80.0, 76.0],
            "current_price": [10.0, 11.0],
        }
    )
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB", "QLD", "TQQQ"],
            "bounce_pct": [80.0, 76.0, 40.0, 75.0],
            "current_price": [10.0, 11.0, 70.0, 35.0],
        }
    )

    ranked = _build_csv_ranking(filtered, summary)
    assert list(ranked["Ticker"]) == ["AAA", "BBB", "TQQQ", "QLD"]


def test_build_csv_ranking_last_row_is_least_bounced_reference():
    filtered = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "bounce_pct": [120.0],
        }
    )
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA", "QLD", "TQQQ"],
            "bounce_pct": [120.0, 40.0, 75.0],
        }
    )

    ranked = _build_csv_ranking(filtered, summary)
    assert ranked.iloc[-1]["Ticker"] == "QLD"


def test_build_csv_ranking_fills_reference_dollar_vol_from_avg_and_price():
    filtered = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "bounce_pct": [120.0],
            "current_price": [20.0],
            "avg_vol_50d": [2_000_000.0],
            "dollar_vol": [40_000_000.0],
        }
    )
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA", "QLD", "TQQQ"],
            "bounce_pct": [120.0, 40.0, 75.0],
            "current_price": [20.0, 50.0, 30.0],
            "avg_vol_50d": [2_000_000.0, 500_000.0, 300_000.0],
        }
    )

    ranked = _build_csv_ranking(filtered, summary)
    qld_row = ranked.loc[ranked["Ticker"] == "QLD"].iloc[0]
    assert qld_row["dollar_vol"] == 25_000_000.0
    assert qld_row["avg_vol_50d"] == 0.5


def test_with_reference_tickers_adds_missing_benchmarks():
    out = _with_reference_tickers(["AAA", "BBB"])
    assert out[-2:] == ["QLD", "TQQQ"]
    assert "AAA" in out and "BBB" in out


def test_format_csv_ranking_renames_avg_volume_and_rounds_fraction():
    ranked = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "avg_vol_50d": [7.6756842105],
            "bounce_pct": [12.34567],
            "dollar_vol": [12_345_678.901],
            "low_price": [10.9876],
            "current_price": [20.1234],
        }
    )

    out = _format_csv_ranking_for_output(ranked)

    assert "avg_vol_50d_m" in out.columns
    assert "avg_vol_50d" not in out.columns
    assert out.loc[0, "avg_vol_50d_m"] == 7.68
    assert "dollar_vol_m" in out.columns
    assert "dollar_vol" not in out.columns
    assert out.loc[0, "dollar_vol_m"] == 12.35
    assert out.loc[0, "bounce_pct"] == 12.35
    assert out.loc[0, "low_price"] == 10.99
    assert out.loc[0, "current_price"] == 20.12


def test_run_fetches_only_finished_days(monkeypatch, tmp_path):
    parser = build_parser()
    args = parser.parse_args(["--output", str(tmp_path / "ranking.csv")])
    captured = {"end_date": None}

    def _mock_fetch_data(*, tickers, low_start, end_date, cache_dir, refresh, db_path):
        captured["end_date"] = end_date
        return pd.DataFrame(columns=["Date", "Ticker", "Low", "Close", "Volume"])

    monkeypatch.setattr("screener._today_market_date", lambda: pd.Timestamp("2026-04-12").date())
    monkeypatch.setattr("screener._select_universe", lambda _universe: [])
    monkeypatch.setattr("screener.fetch_data", _mock_fetch_data)
    monkeypatch.setattr("screener.get_ticker_metadata", lambda *args, **kwargs: {})
    monkeypatch.setattr("screener.show_results", lambda *args, **kwargs: None)
    monkeypatch.setattr("screener.save_run", lambda *args, **kwargs: 1)

    run(args)

    assert captured["end_date"] == "2026-04-12"


def test_run_extends_fetch_history_for_pattern_modes(monkeypatch, tmp_path):
    parser = build_parser()
    args = parser.parse_args(
        [
            "--low-start",
            "2026-04-01",
            "--patterns",
            "--output",
            str(tmp_path / "ranking.csv"),
        ]
    )
    captured = {"low_start": None}

    def _mock_fetch_data(*, tickers, low_start, end_date, cache_dir, refresh, db_path):
        captured["low_start"] = low_start
        return pd.DataFrame(columns=["Date", "Ticker", "Low", "Close", "Volume"])

    monkeypatch.setattr("screener._today_market_date", lambda: pd.Timestamp("2026-04-12").date())
    monkeypatch.setattr("screener._select_universe", lambda _universe: [])
    monkeypatch.setattr("screener.fetch_data", _mock_fetch_data)
    monkeypatch.setattr("screener.get_ticker_metadata", lambda *args, **kwargs: {})
    monkeypatch.setattr("screener.show_results", lambda *args, **kwargs: None)
    monkeypatch.setattr("screener.save_run", lambda *args, **kwargs: 1)

    run(args)

    expected = (
        pd.Timestamp("2026-04-12")
        - pd.offsets.BDay(PATTERN_LOOKBACK_DAYS - 1)
    ).date().isoformat()
    assert captured["low_start"] == expected
