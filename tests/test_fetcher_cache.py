import sqlite3

import pandas as pd

from db import get_cached_price_history, get_invalid_tickers, has_cached_coverage, init_db, save_price_history
from fetcher import fetch_data


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


def test_fetch_data_skips_known_invalid_tickers_before_download(tmp_path, monkeypatch):
    db_path = tmp_path / "raw_cache.db"
    conn = init_db(db_path)
    conn.execute(
        """
        INSERT INTO invalid_tickers (ticker, source, reason, detected_at)
        VALUES ('BAD', 'yfinance', 'no data', '2026-04-12 00:00:00')
        """
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
