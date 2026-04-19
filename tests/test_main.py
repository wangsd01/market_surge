from __future__ import annotations

import json
from pathlib import Path
from datetime import date

import pandas as pd

from actionability import ActionabilityAssessment
from decision_tickets import DecisionCandidate
from fetcher import CacheMissError, UniverseCacheMissError
from pipeline import ScreeningArtifacts
from patterns.base import PatternResult

import main


def _artifacts() -> ScreeningArtifacts:
    return ScreeningArtifacts(
        raw_df=pd.DataFrame(),
        summary_all=pd.DataFrame(),
        summary=pd.DataFrame(),
        benchmark_bounces={},
    )


def _candidate(ticker: str, screen_strength: float) -> DecisionCandidate:
    return DecisionCandidate(
        ticker=ticker,
        pattern="cup_handle",
        screen_strength=screen_strength,
        pattern_confidence=0.8,
        entry=10.0,
        stop=9.0,
        target=12.0,
        current_price=10.0,
        dollar_volume=100_000_000.0,
        summary_reason=f"{ticker} reason",
        invalidation_rule="invalid if price trades below stop",
    )


def _raw_df(ticker: str) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=5, freq="B")
    return pd.DataFrame(
        {
            "Date": dates,
            "Ticker": [ticker] * len(dates),
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "Volume": [1_000_000] * len(dates),
        }
    )


def _raw_df_many(tickers: list[str]) -> pd.DataFrame:
    return pd.concat([_raw_df(ticker) for ticker in tickers], ignore_index=True)


def _raw_df_long(ticker: str, periods: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=periods, freq="B")
    closes = [100.0 + i for i in range(periods)]
    return pd.DataFrame(
        {
            "Date": dates,
            "Ticker": [ticker] * len(dates),
            "Open": closes,
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [1_000_000] * len(dates),
        }
    )


def _pattern_result(ticker: str, pattern: str = "cup_handle") -> PatternResult:
    return PatternResult(
        pattern=pattern,
        ticker=ticker,
        confidence=0.9,
        detected_on=date(2025, 1, 7),
        pivots={"handle_high": 105.0, "handle_low": 100.0},
        pivot_dates={
            "handle_high": date(2025, 1, 6),
            "handle_low": date(2025, 1, 7),
        },
    )


def _handle_forming_cup_result(ticker: str) -> PatternResult:
    return PatternResult(
        pattern="cup_handle",
        ticker=ticker,
        confidence=0.9,
        detected_on=date(2025, 4, 10),
        pivots={
            "left_high": 110.0,
            "cup_low": 85.0,
            "right_high": 105.0,
            "handle_high": 100.0,
            "handle_low": 95.0,
        },
        pivot_dates={
            "left_high": date(2025, 3, 24),
            "cup_low": date(2025, 4, 1),
            "right_high": date(2025, 4, 7),
            "handle_high": date(2025, 4, 9),
            "handle_low": date(2025, 4, 10),
        },
        metadata={"state": "handle_forming", "actionable": False},
    )


def _stale_pattern_result(ticker: str, pattern: str = "double_bottom") -> PatternResult:
    return PatternResult(
        pattern=pattern,
        ticker=ticker,
        confidence=0.9,
        detected_on=date(2025, 2, 25),
        pivots={
            "first_trough": 90.0,
            "middle_high": 105.0,
            "second_trough": 91.0,
        },
        pivot_dates={
            "first_trough": date(2025, 1, 20),
            "middle_high": date(2025, 1, 28),
            "second_trough": date(2025, 2, 3),
        },
    )


def _recent_pattern_with_last_pivot(ticker: str, pivot_day: date, pattern: str = "double_bottom") -> PatternResult:
    return PatternResult(
        pattern=pattern,
        ticker=ticker,
        confidence=0.9,
        detected_on=pivot_day,
        pivots={
            "first_trough": 90.0,
            "middle_high": 105.0,
            "second_trough": 91.0,
        },
        pivot_dates={
            "first_trough": pivot_day,
            "middle_high": pivot_day,
            "second_trough": pivot_day,
        },
    )


def _confirmed_double_bottom_result(ticker: str, breakout_day: date) -> PatternResult:
    return PatternResult(
        pattern="double_bottom",
        ticker=ticker,
        confidence=0.95,
        detected_on=breakout_day,
        pivots={
            "left_high": 120.0,
            "first_trough": 90.0,
            "middle_high": 105.0,
            "second_trough": 88.0,
            "breakout": 106.0,
        },
        pivot_dates={
            "left_high": date(2025, 1, 10),
            "first_trough": date(2025, 1, 24),
            "middle_high": date(2025, 2, 18),
            "second_trough": date(2025, 3, 12),
            "breakout": breakout_day,
        },
        metadata={"state": "confirmed", "buy_point": 105.0},
    )


def _active_pre_breakout_double_bottom_result(
    ticker: str,
    *,
    active_zone_pct_below_buy_point: float,
) -> PatternResult:
    return PatternResult(
        pattern="double_bottom",
        ticker=ticker,
        confidence=0.88,
        detected_on=date(2025, 4, 14),
        pivots={
            "left_high": 120.0,
            "first_trough": 90.0,
            "middle_high": 105.0,
            "second_trough": 88.0,
        },
        pivot_dates={
            "left_high": date(2025, 1, 10),
            "first_trough": date(2025, 1, 24),
            "middle_high": date(2025, 2, 18),
            "second_trough": date(2025, 3, 12),
        },
        metadata={
            "state": "active_pre_breakout",
            "buy_point": 105.0,
            "active_zone_pct_below_buy_point": active_zone_pct_below_buy_point,
        },
    )


def _high2_pattern_result(ticker: str, pivot_day: date) -> PatternResult:
    return PatternResult(
        pattern="high2",
        ticker=ticker,
        confidence=0.88,
        detected_on=pivot_day,
        pivots={
            "prior_swing_high": 120.0,
            "pullback_low": 110.0,
            "h1_high": 118.0,
            "h2_high": 119.0,
            "h2_low": 114.0,
        },
        pivot_dates={
            "prior_swing_high": date(2025, 4, 1),
            "pullback_low": date(2025, 4, 8),
            "h1_high": date(2025, 4, 9),
            "h2_high": pivot_day,
            "h2_low": pivot_day,
        },
        metadata={"prior_leg_height": 12.0},
    )


def test_build_parser_supports_decision_ticket_flags():
    parser = main.build_parser()
    args = parser.parse_args(
        [
            "--account-size",
            "10000",
            "--risk-pct",
            "0.01",
            "--max-loss-pct",
            "0.05",
            "--max-position-dollars",
            "5000",
            "--format",
            "json",
            "--universe",
            "sp500",
            "--debug",
        ]
    )

    assert args.account_size == 10_000.0
    assert args.risk_pct == 0.01
    assert args.max_loss_pct == 0.05
    assert args.max_position_dollars == 5_000.0
    assert args.format == "json"
    assert args.universe == "sp500"
    assert args.debug is True


def test_build_parser_defaults_to_sp500_for_timed_cli():
    parser = main.build_parser()
    args = parser.parse_args(["--account-size", "10000", "--risk-pct", "0.01"])

    assert args.universe == "sp500"
    assert args.max_loss_pct == 0.08


def test_run_json_emits_empty_list_for_no_valid_setups(monkeypatch, capsys):
    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: _artifacts())
    monkeypatch.setattr("main.build_candidates", lambda artifacts, args: [])

    args = main.build_parser().parse_args(
        ["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20", "--format", "json"]
    )

    tickets = main.run(args)
    out = capsys.readouterr().out.strip()

    assert tickets == []
    assert json.loads(out) == []


def test_run_json_emits_only_available_tickets_in_rank_order(monkeypatch, capsys):
    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: _artifacts())
    monkeypatch.setattr(
        "main.build_candidates",
        lambda artifacts, args: [_candidate("AAA", 0.9), _candidate("BBB", 0.8)],
    )

    args = main.build_parser().parse_args(
        ["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20", "--format", "json"]
    )

    tickets = main.run(args)
    out = json.loads(capsys.readouterr().out)

    assert [ticket.ticker for ticket in tickets] == ["AAA", "BBB"]
    assert [item["ticker"] for item in out] == ["AAA", "BBB"]
    assert len(out) == 2


def test_run_json_truncates_to_top_ten(monkeypatch, capsys):
    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: _artifacts())
    monkeypatch.setattr(
        "main.build_candidates",
        lambda artifacts, args: [_candidate(chr(ord("A") + i) * 3, 0.95 - i * 0.05) for i in range(12)],
    )
    monkeypatch.setattr("main._save_ticket_charts", lambda *args, **kwargs: [])

    args = main.build_parser().parse_args(
        ["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20", "--format", "json"]
    )

    tickets = main.run(args)
    out = json.loads(capsys.readouterr().out)

    assert len(tickets) == 10
    assert len(out) == 10


def test_run_table_uses_ticket_renderer(monkeypatch):
    called: dict[str, object] = {}

    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: _artifacts())
    monkeypatch.setattr("main.build_candidates", lambda artifacts, args: [_candidate("AAA", 0.9)])
    monkeypatch.setattr("main._save_ticket_charts", lambda *args, **kwargs: [])

    def _fake_show_decision_tickets(tickets, plain):
        called["tickers"] = [ticket.ticker for ticket in tickets]
        called["plain"] = plain

    monkeypatch.setattr("main.show_decision_tickets", _fake_show_decision_tickets)

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])

    main.run(args)

    assert called == {"tickers": ["AAA"], "plain": False}


def test_run_passes_max_loss_pct_to_ticket_builder(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: _artifacts())
    monkeypatch.setattr("main.build_candidates", lambda artifacts, args: [_candidate("AAA", 0.9)])
    monkeypatch.setattr("main._save_ticket_charts", lambda *args, **kwargs: [])

    def _fake_build_decision_tickets(candidates, **kwargs):
        captured["candidates"] = candidates
        captured.update(kwargs)
        return []

    monkeypatch.setattr("main.build_decision_tickets", _fake_build_decision_tickets)

    args = main.build_parser().parse_args(
        ["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.06"]
    )

    main.run(args)

    assert captured["max_loss_pct"] == 0.06


def test_build_candidates_filters_out_stale_patterns(monkeypatch):
    raw_df = _raw_df_long("AAA", periods=80)
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "current_price": [120.0],
            "bounce_pct": [30.0],
            "avg_vol_50d": [1_000_000.0],
            "fifty_two_week_high": [140.0],
            "sector": ["Technology"],
            "industry": ["Semiconductors"],
        }
    )
    artifacts = ScreeningArtifacts(
        raw_df=raw_df,
        summary_all=summary,
        summary=summary,
        benchmark_bounces={},
    )

    monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [_stale_pattern_result(ticker)])
    monkeypatch.setattr(
        "strategies.strategy",
        lambda result: type(
            "Setup",
            (),
            {
                "entry": 105.05,
                "stop": 91.0,
                "target": 133.15,
                "risk_reward": 2.0,
                "invalidation_rule": "invalid if price trades below stop",
            },
        )(),
    )

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])

    candidates = main.build_candidates(artifacts, args)

    assert candidates == []


def test_build_candidates_includes_recent_high2_patterns(monkeypatch):
    raw_df = _raw_df_long("AAA", periods=80)
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "current_price": [120.0],
            "bounce_pct": [30.0],
            "avg_vol_50d": [1_000_000.0],
            "fifty_two_week_high": [140.0],
            "sector": ["Technology"],
            "industry": ["Semiconductors"],
        }
    )
    artifacts = ScreeningArtifacts(
        raw_df=raw_df,
        summary_all=summary,
        summary=summary,
        benchmark_bounces={},
    )

    monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [_high2_pattern_result(ticker, date(2025, 4, 10))])
    monkeypatch.setattr(
        "actionability.assess_actionability",
        lambda result, current_price: ActionabilityAssessment(
            is_actionable=True,
            reason="post_breakout_pullback",
            entry=119.0,
            stop=110.0,
        ),
    )

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])

    candidates = main.build_candidates(artifacts, args)

    assert len(candidates) == 1
    assert candidates[0].pattern == "high2"


def test_build_candidates_skips_detected_patterns_that_are_not_actionable(monkeypatch):
    raw_df = _raw_df_long("AAA", periods=80)
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "current_price": [89.0],
            "bounce_pct": [30.0],
            "avg_vol_50d": [1_000_000.0],
            "fifty_two_week_high": [120.0],
            "sector": ["Technology"],
            "industry": ["Semiconductors"],
        }
    )
    artifacts = ScreeningArtifacts(
        raw_df=raw_df,
        summary_all=summary,
        summary=summary,
        benchmark_bounces={},
    )

    monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [_handle_forming_cup_result(ticker)])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])

    candidates = main.build_candidates(artifacts, args)

    assert candidates == []


def test_build_candidates_includes_pre_breakout_patterns_when_actionable(monkeypatch):
    raw_df = _raw_df_long("AAA", periods=80)
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "current_price": [92.1],
            "bounce_pct": [30.0],
            "avg_vol_50d": [1_000_000.0],
            "fifty_two_week_high": [120.0],
            "sector": ["Technology"],
            "industry": ["Semiconductors"],
        }
    )
    artifacts = ScreeningArtifacts(
        raw_df=raw_df,
        summary_all=summary,
        summary=summary,
        benchmark_bounces={},
    )

    monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [_handle_forming_cup_result(ticker)])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])

    candidates = main.build_candidates(artifacts, args)

    assert len(candidates) == 1
    assert candidates[0].pattern == "cup_handle"


def test_is_recent_pattern_result_keeps_patterns_within_ten_trading_days():
    latest_date = date(2025, 4, 14)
    pattern_result = _recent_pattern_with_last_pivot("AAA", date(2025, 3, 31))

    assert main._is_recent_pattern_result(pattern_result, latest_date=latest_date) is True


def test_is_recent_pattern_result_rejects_patterns_older_than_ten_trading_days():
    latest_date = date(2025, 4, 14)
    pattern_result = _recent_pattern_with_last_pivot("AAA", date(2025, 3, 28))

    assert main._is_recent_pattern_result(pattern_result, latest_date=latest_date) is False


def test_is_recent_pattern_result_uses_breakout_date_for_confirmed_double_bottom():
    latest_date = date(2025, 4, 14)
    pattern_result = _confirmed_double_bottom_result("AAA", date(2025, 4, 3))

    assert main._is_recent_pattern_result(pattern_result, latest_date=latest_date) is True


def test_is_recent_pattern_result_treats_active_pre_breakout_double_bottom_as_current():
    latest_date = date(2025, 4, 14)
    pattern_result = _active_pre_breakout_double_bottom_result(
        "AAA",
        active_zone_pct_below_buy_point=0.08,
    )

    assert main._is_recent_pattern_result(pattern_result, latest_date=latest_date) is True


def test_is_recent_pattern_result_keeps_active_pre_breakout_double_bottom_focused_on_freshness_only():
    latest_date = date(2025, 4, 14)
    pattern_result = _active_pre_breakout_double_bottom_result(
        "AAA",
        active_zone_pct_below_buy_point=0.12,
    )

    assert main._is_recent_pattern_result(pattern_result, latest_date=latest_date) is True


def test_run_saves_chart_files_for_ranked_tickets(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tickers = ["AAA", "BBB"]
    artifacts = ScreeningArtifacts(
        raw_df=_raw_df_many(tickers),
        summary_all=pd.DataFrame(),
        summary=pd.DataFrame(),
        benchmark_bounces={},
    )
    chart_calls: list[dict[str, object]] = []

    class _FakeFigure:
        def write_html(self, path: str) -> None:
            chart_calls[-1]["path"] = path

    def _fake_chart(ticker, df, patterns, setup=None, ticket=None, show=True):
        chart_calls.append(
            {
                "ticker": ticker,
                "patterns": patterns,
                "setup": setup,
                "ticket": ticket,
                "show": show,
            }
        )
        return _FakeFigure()

    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: artifacts)
    monkeypatch.setattr(
        "main.build_candidates",
        lambda artifacts, args: [_candidate("AAA", 0.9), _candidate("BBB", 0.8)],
    )
    monkeypatch.setattr("charts.chart", _fake_chart)
    monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [_pattern_result(ticker)])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])

    tickets = main.run(args)

    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    ts = run_dirs[0].name
    assert [ticket.ticker for ticket in tickets] == ["AAA", "BBB"]
    assert [call["ticker"] for call in chart_calls] == ["AAA", "BBB"]
    assert all(call["show"] is False for call in chart_calls)
    assert all(call["setup"] is not None for call in chart_calls)
    assert [call["ticket"].ticker for call in chart_calls] == ["AAA", "BBB"]
    assert [Path(call["path"]) for call in chart_calls] == [
        Path("runs") / ts / "charts" / "01_AAA_cup_handle.html",
        Path("runs") / ts / "charts" / "02_BBB_cup_handle.html",
    ]
    assert all(call["patterns"][0].pattern == "cup_handle" for call in chart_calls)


def test_run_debug_saves_all_valid_setups_before_top_ten(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tickers = [f"T{i:02d}" for i in range(12)]
    artifacts = ScreeningArtifacts(
        raw_df=_raw_df_many(tickers),
        summary_all=pd.DataFrame(),
        summary=pd.DataFrame(),
        benchmark_bounces={},
    )
    saved_paths: list[Path] = []

    class _FakeFigure:
        def write_html(self, path: str) -> None:
            saved_paths.append(Path(path))

    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: artifacts)
    monkeypatch.setattr(
        "main.build_candidates",
        lambda artifacts, args: [_candidate(ticker, 1.0 - i * 0.01) for i, ticker in enumerate(tickers)],
    )
    monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [_pattern_result(ticker)])
    monkeypatch.setattr("charts.chart", lambda *args, **kwargs: _FakeFigure())

    args = main.build_parser().parse_args(
        ["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20", "--debug"]
    )

    tickets = main.run(args)

    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    ts = run_dirs[0].name
    assert len(tickets) == 10
    assert len(saved_paths) == 12
    assert saved_paths[0] == Path("runs") / ts / "charts" / "01_T00_cup_handle.html"
    assert saved_paths[-1] == Path("runs") / ts / "charts" / "12_T11_cup_handle.html"


def test_main_returns_cache_miss_status(monkeypatch, capsys):
    def _raise_cache_miss(_args):
        raise CacheMissError(["AAPL"], low_start="2026-04-01", end_date="2026-04-12")

    monkeypatch.setattr("main.run", _raise_cache_miss)

    status = main.main(["--account-size", "10000", "--risk-pct", "0.01"])
    captured = capsys.readouterr()

    assert status == 2
    assert "CACHE_MISS" in captured.err


def test_run_sp500_auto_warms_missing_cached_universe(monkeypatch, capsys):
    calls: list[dict[str, object]] = []

    def _fake_build_screening_artifacts(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise UniverseCacheMissError("sp500", "cache/sp500_tickers.txt")
        return _artifacts()

    monkeypatch.setattr("main.build_screening_artifacts", _fake_build_screening_artifacts)
    monkeypatch.setattr("main.build_candidates", lambda artifacts, args: [])
    monkeypatch.setattr("main._save_ticket_charts", lambda *args, **kwargs: [])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01"])

    tickets = main.run(args)
    captured = capsys.readouterr()

    assert tickets == []
    assert len(calls) == 2
    assert calls[0]["fetch_data_fn"] is main.fetch_data_cached_only
    assert calls[1]["fetch_data_fn"] is main.fetch_data
    assert calls[0]["select_universe_fn"] is main._select_universe_for_timed_cli
    assert calls[1]["select_universe_fn"] is main._select_universe_for_default_cli
    assert "CACHE_MISS cached universe 'sp500' at cache/sp500_tickers.txt" in captured.err
    assert "DOWNLOADING sp500 universe to cache/sp500_tickers.txt and market data as needed" in captured.err


def test_run_sp500_auto_warms_missing_price_cache(monkeypatch, capsys):
    calls: list[dict[str, object]] = []

    def _fake_build_screening_artifacts(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise CacheMissError(["AAA"], low_start="2026-04-01", end_date="2026-04-12")
        return _artifacts()

    monkeypatch.setattr("main.build_screening_artifacts", _fake_build_screening_artifacts)
    monkeypatch.setattr("main.build_candidates", lambda artifacts, args: [])
    monkeypatch.setattr("main._save_ticket_charts", lambda *args, **kwargs: [])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01"])

    tickets = main.run(args)
    captured = capsys.readouterr()

    assert tickets == []
    assert len(calls) == 2
    assert calls[0]["fetch_data_fn"] is main.fetch_data_cached_only
    assert calls[1]["fetch_data_fn"] is main.fetch_data
    assert calls[0]["select_universe_fn"] is main._select_universe_for_timed_cli
    assert calls[1]["select_universe_fn"] is main._select_universe_for_default_cli
    assert "CACHE_MISS missing price history for AAA in requested range 2026-04-01..2026-04-12" in captured.err
    assert "DOWNLOADING price history for AAA in requested range 2026-04-01..2026-04-12" in captured.err


def test_main_py_has_cli_shebang():
    first_line = Path("main.py").read_text().splitlines()[0]
    assert first_line == "#!/usr/bin/env python3"


# --- timestamped run folder tests ---

def test_run_creates_timestamped_run_folder(monkeypatch, tmp_path):
    import re

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: _artifacts())
    monkeypatch.setattr("main.build_candidates", lambda artifacts, args: [])
    monkeypatch.setattr("main._save_ticket_charts", lambda *args, **kwargs: [])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])
    main.run(args)

    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    assert re.match(r"\d{8}_\d{6}", run_dirs[0].name)


def test_run_saves_charts_inside_run_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tickers = ["AAA", "BBB"]
    artifacts = ScreeningArtifacts(
        raw_df=_raw_df_many(tickers),
        summary_all=pd.DataFrame(),
        summary=pd.DataFrame(),
        benchmark_bounces={},
    )
    chart_calls: list[dict[str, object]] = []

    class _FakeFigure:
        def write_html(self, path: str) -> None:
            chart_calls[-1]["path"] = path

    def _fake_chart(ticker, df, patterns, setup=None, ticket=None, show=True):
        chart_calls.append({"ticker": ticker, "show": show, "setup": setup, "ticket": ticket, "patterns": patterns})
        return _FakeFigure()

    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: artifacts)
    monkeypatch.setattr(
        "main.build_candidates",
        lambda artifacts, args: [_candidate("AAA", 0.9), _candidate("BBB", 0.8)],
    )
    monkeypatch.setattr("charts.chart", _fake_chart)
    monkeypatch.setattr("patterns.detect_all", lambda df, ticker: [_pattern_result(ticker)])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])
    main.run(args)

    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    ts = run_dirs[0].name
    assert [Path(call["path"]) for call in chart_calls] == [
        Path("runs") / ts / "charts" / "01_AAA_cup_handle.html",
        Path("runs") / ts / "charts" / "02_BBB_cup_handle.html",
    ]


def test_run_saves_screened_ranking_csv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    summary = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB"],
            "current_price": [50.0, 60.0],
            "bounce_pct": [15.0, 20.0],
            "avg_vol_50d": [2_000_000.0, 3_000_000.0],
            "fifty_two_week_high": [60.0, 70.0],
            "sector": ["Technology", "Healthcare"],
            "industry": ["Software", "Biotech"],
        }
    )
    artifacts = ScreeningArtifacts(
        raw_df=pd.DataFrame(),
        summary_all=summary,
        summary=summary,
        benchmark_bounces={},
    )
    monkeypatch.setattr("main.build_screening_artifacts", lambda **_kwargs: artifacts)
    monkeypatch.setattr("main.build_candidates", lambda artifacts, args: [])
    monkeypatch.setattr("main._save_ticket_charts", lambda *args, **kwargs: [])

    args = main.build_parser().parse_args(["--account-size", "10000", "--risk-pct", "0.01", "--max-loss-pct", "0.20"])
    main.run(args)

    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    csv_path = run_dirs[0] / "screened_ranking.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    # sorted by bounce_pct descending
    assert list(df["Ticker"]) == ["BBB", "AAA"]
