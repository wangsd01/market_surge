import sqlite3

import pandas as pd
import pytest

from db import get_cached_price_history, get_invalid_tickers, has_cached_coverage, init_db, save_price_history
from fetcher import CacheMissError, fetch_data, fetch_data_cached_only


def _sample_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-04-01", "2026-04-02"]),
            "Ticker": ["AAPL", "AAPL"],
            "Open": [149.0, 150.0],
            "High": [151.0, 152.0],
            "Low": [148.0, 149.0],
            "Close": [150.0, 151.0],
            "Volume": [10_000_000, 11_000_000],
        }
    )


def _null_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-04-01", "2026-04-02"]),
            "Ticker": ["AAPL", "AAPL"],
            "Open": [None, None],
            "High": [None, None],
            "Low": [None, None],
            "Close": [None, None],
            "Volume": [None, None],
        }
    )


def _prices_with_symbol_specific_gap() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-11-07", "2025-11-10", "2025-11-11", "2025-11-13", "2025-11-14"])
    return pd.DataFrame(
        {
            "Date": dates,
            "Ticker": ["FISV"] * len(dates),
            "Open": [60.95, 63.91, 63.60, 64.85, 64.00],
            "High": [63.84, 64.18, 64.48, 66.95, 64.15],
            "Low": [60.95, 62.67, 62.84, 64.37, 63.02],
            "Close": [63.70, 63.80, 64.26, 64.53, 63.42],
            "Volume": [14_163_900, 8_431_600, 5_427_200, 9_274_500, 5_596_500],
        }
    )


def test_fetch_data_uses_sqlite_cache_without_download(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    save_price_history(conn, _sample_prices())
    conn.close()

    called = {"downloaded": False}

    def _should_not_download(*_args, **_kwargs):
        called["downloaded"] = True
        raise AssertionError("Download should not run when SQLite cache has data")

    monkeypatch.setattr("fetcher._download_all_batches", _should_not_download)

    out = fetch_data(
        tickers=["AAPL"],
        low_start="2026-04-01",
        end_date="2026-04-03",
        cache_dir=tmp_path,
        refresh=False,
    )

    assert not called["downloaded"]
    assert len(out) == 2
    assert list(out["Ticker"].unique()) == ["AAPL"]


def test_fetch_data_cached_only_uses_sqlite_cache_without_download(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    save_price_history(conn, _sample_prices())
    conn.close()

    called = {"downloaded": False}

    def _should_not_download(*_args, **_kwargs):
        called["downloaded"] = True
        raise AssertionError("Cache-only fetch must not download")

    monkeypatch.setattr("fetcher._download_all_batches", _should_not_download)

    out = fetch_data_cached_only(
        tickers=["AAPL"],
        low_start="2026-04-01",
        end_date="2026-04-03",
        cache_dir=tmp_path,
    )

    assert not called["downloaded"]
    assert len(out) == 2
    assert list(out["Ticker"].unique()) == ["AAPL"]


def test_fetch_data_cached_only_raises_cache_miss_without_download(tmp_path, monkeypatch):
    called = {"downloaded": False}

    def _should_not_download(*_args, **_kwargs):
        called["downloaded"] = True
        raise AssertionError("Cache-only fetch must not download")

    monkeypatch.setattr("fetcher._download_all_batches", _should_not_download)

    with pytest.raises(CacheMissError) as excinfo:
        fetch_data_cached_only(
            tickers=["AAPL"],
            low_start="2026-04-01",
            end_date="2026-04-03",
            cache_dir=tmp_path,
        )

    assert not called["downloaded"]
    assert excinfo.value.missing_tickers == ["AAPL"]


def test_fetch_data_cached_only_raises_on_partial_range_without_download(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    save_price_history(conn, _sample_prices().iloc[:1].copy())
    conn.close()

    called = {"downloaded": False}

    def _should_not_download(*_args, **_kwargs):
        called["downloaded"] = True
        raise AssertionError("Cache-only fetch must not download")

    monkeypatch.setattr("fetcher._download_all_batches", _should_not_download)

    with pytest.raises(CacheMissError) as excinfo:
        fetch_data_cached_only(
            tickers=["AAPL"],
            low_start="2026-04-01",
            end_date="2026-04-03",
            cache_dir=tmp_path,
        )

    assert not called["downloaded"]
    assert excinfo.value.missing_tickers == ["AAPL"]


def test_fetch_data_cache_miss_downloads_and_persists_sqlite(tmp_path, monkeypatch):
    sample = _sample_prices()

    def _mock_download(*_args, **_kwargs):
        return sample.copy(), []

    monkeypatch.setattr("fetcher._download_all_batches", _mock_download)

    out = fetch_data(
        tickers=["AAPL"],
        low_start="2026-04-01",
        end_date="2026-04-03",
        cache_dir=tmp_path,
        refresh=False,
    )
    assert len(out) == 2

    db_path = tmp_path / "raw_cache.db"
    conn = sqlite3.connect(db_path)
    cached = get_cached_price_history(conn, ["AAPL"], "2026-04-01", "2026-04-03")
    conn.close()

    assert len(cached) == 2
    assert cached.loc[cached["Ticker"] == "AAPL", "Close"].iloc[0] == 150.0


def test_has_cached_coverage_rejects_null_only_rows(tmp_path):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    save_price_history(conn, _null_prices())
    assert has_cached_coverage(conn, ["AAPL"], "2026-04-01", "2026-04-03") is False
    conn.close()


def test_has_cached_coverage_rejects_partial_ranges(tmp_path):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    save_price_history(conn, _sample_prices().iloc[:1].copy())
    assert has_cached_coverage(conn, ["AAPL"], "2026-04-01", "2026-04-03") is False
    conn.close()


def test_has_cached_coverage_ignores_market_holidays(tmp_path):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    dates = pd.to_datetime(
        ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-06"]
    )
    save_price_history(
        conn,
        pd.DataFrame(
            {
                "Date": dates,
                "Ticker": ["AAPL"] * len(dates),
                "Open": [149.0] * len(dates),
                "High": [151.0] * len(dates),
                "Low": [148.0] * len(dates),
                "Close": [150.0] * len(dates),
                "Volume": [10_000_000] * len(dates),
            }
        ),
    )

    assert has_cached_coverage(conn, ["AAPL"], "2026-03-30", "2026-04-07") is True
    conn.close()


def test_has_cached_coverage_accepts_tickers_that_start_trading_after_range_start(tmp_path):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    dates = pd.to_datetime(["2026-04-02", "2026-04-06"])
    save_price_history(
        conn,
        pd.DataFrame(
            {
                "Date": dates,
                "Ticker": ["NEW"] * len(dates),
                "Open": [20.0] * len(dates),
                "High": [21.0] * len(dates),
                "Low": [19.0] * len(dates),
                "Close": [20.5] * len(dates),
                "Volume": [1_000_000] * len(dates),
            }
        ),
    )

    assert has_cached_coverage(conn, ["NEW"], "2026-03-30", "2026-04-07") is True
    conn.close()


def test_fetch_data_downloads_when_cache_contains_only_null_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    save_price_history(conn, _null_prices())
    conn.close()

    called = {"downloaded": False}

    def _mock_download(*_args, **_kwargs):
        called["downloaded"] = True
        return _sample_prices().copy(), []

    monkeypatch.setattr("fetcher._download_all_batches", _mock_download)

    out = fetch_data(
        tickers=["AAPL"],
        low_start="2026-04-01",
        end_date="2026-04-03",
        cache_dir=tmp_path,
        refresh=False,
    )

    assert called["downloaded"] is True
    assert len(out) == 2
    assert out["Close"].notna().all()


def test_fetch_data_downloads_when_cache_has_partial_range_for_ticker(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    save_price_history(conn, _sample_prices().iloc[:1].copy())
    conn.close()

    seen = {"tickers": None}

    def _mock_download(tickers, *_args, **_kwargs):
        seen["tickers"] = list(tickers)
        return _sample_prices().copy(), []

    monkeypatch.setattr("fetcher._download_all_batches", _mock_download)

    out = fetch_data(
        tickers=["AAPL"],
        low_start="2026-04-01",
        end_date="2026-04-03",
        cache_dir=tmp_path,
        refresh=False,
    )

    assert seen["tickers"] == ["AAPL"]
    assert list(out["Date"].dt.strftime("%Y-%m-%d")) == ["2026-04-01", "2026-04-02"]


def test_fetch_data_does_not_redownload_provider_confirmed_symbol_specific_gap(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    calls = {"downloaded": 0}

    def _mock_download(tickers, low_start, end_date):
        calls["downloaded"] += 1
        assert tickers == ["FISV"]
        assert low_start == "2025-11-07"
        assert end_date == "2025-11-15"
        return _prices_with_symbol_specific_gap(), []

    monkeypatch.setattr("fetcher._download_all_batches", _mock_download)

    first = fetch_data(
        tickers=["FISV"],
        low_start="2025-11-07",
        end_date="2025-11-15",
        cache_dir=tmp_path,
        refresh=False,
        db_path=db_path,
    )

    def _should_not_download(*_args, **_kwargs):
        raise AssertionError("Provider-confirmed missing sessions should not redownload")

    monkeypatch.setattr("fetcher._download_all_batches", _should_not_download)
    second = fetch_data(
        tickers=["FISV"],
        low_start="2025-11-07",
        end_date="2025-11-15",
        cache_dir=tmp_path,
        refresh=False,
        db_path=db_path,
    )

    assert calls["downloaded"] == 1
    assert len(first) == 5
    assert len(second) == 5


def test_fetch_data_skips_known_invalid_tickers_before_download(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    from datetime import UTC, datetime

    now = datetime.now(UTC).replace(microsecond=0).isoformat(sep=" ")
    conn.execute(
        "INSERT INTO invalid_tickers (ticker, source, reason, detected_at) VALUES ('BAD', 'yfinance', 'no data', ?)",
        (now,),
    )
    conn.commit()
    conn.close()

    seen = {"tickers": None}

    def _mock_download(tickers, *_args, **_kwargs):
        seen["tickers"] = list(tickers)
        return _sample_prices().copy(), []

    monkeypatch.setattr("fetcher._download_all_batches", _mock_download)

    out = fetch_data(
        tickers=["BAD", "AAPL"],
        low_start="2026-04-01",
        end_date="2026-04-03",
        cache_dir=tmp_path,
        refresh=True,
    )

    assert seen["tickers"] == ["AAPL"]
    assert list(out["Ticker"].unique()) == ["AAPL"]


def test_fetch_data_persists_new_invalid_tickers(tmp_path, monkeypatch):
    def _mock_download(*_args, **_kwargs):
        return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]), ["BAD"]

    monkeypatch.setattr("fetcher._download_all_batches", _mock_download)

    out = fetch_data(
        tickers=["BAD"],
        low_start="2026-04-01",
        end_date="2026-04-03",
        cache_dir=tmp_path,
        refresh=True,
    )

    assert out.empty
    conn = sqlite3.connect(tmp_path / "raw_cache.db")
    invalid = get_invalid_tickers(conn, "yfinance")
    conn.close()
    assert invalid == {"BAD"}


def test_fetch_data_does_not_store_or_return_today_rows(tmp_path, monkeypatch):
    sample = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-04-11", "2026-04-12"]),
            "Ticker": ["AAPL", "AAPL"],
            "Open": [149.0, 150.0],
            "High": [151.0, 152.0],
            "Low": [148.0, 149.0],
            "Close": [150.0, 151.0],
            "Volume": [10_000_000, 11_000_000],
        }
    )

    def _mock_download(*_args, **_kwargs):
        return sample.copy(), []

    monkeypatch.setattr("fetcher._download_all_batches", _mock_download)
    monkeypatch.setattr("fetcher._today_market_date", lambda: pd.Timestamp("2026-04-12").date())

    out = fetch_data(
        tickers=["AAPL"],
        low_start="2026-04-11",
        end_date="2026-04-13",
        cache_dir=tmp_path,
        refresh=True,
    )

    assert list(out["Date"].dt.strftime("%Y-%m-%d")) == ["2026-04-11"]

    conn = sqlite3.connect(tmp_path / "raw_cache.db")
    cached = get_cached_price_history(conn, ["AAPL"], "2026-04-11", "2026-04-13")
    conn.close()

    assert list(cached["Date"].dt.strftime("%Y-%m-%d")) == ["2026-04-11"]
