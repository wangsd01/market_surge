import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import fetcher
from db import get_ticker_metadata as get_cached_ticker_metadata, init_db, save_ticker_metadata
from fetcher import (
    BIOTECH_SECTION,
    DEFAULT_SECTION,
    UniverseCacheMissError,
    _extract_ticker_metadata_from_info,
    _fetch_cutoff_date,
    _market_has_closed_today,
    _yfinance_end_date,
    fetch_data,
    get_sp500_tickers_cached_only,
    get_ticker_metadata,
    get_ticker_sections,
    get_tickers,
    reshape_download_frame,
)

_ET = ZoneInfo("America/New_York")


def _mock_multiindex_df():
    dates = pd.to_datetime(["2026-04-01"])
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "AAPL"),
            ("High", "AAPL"),
            ("Low", "AAPL"),
            ("Close", "AAPL"),
            ("Volume", "AAPL"),
            ("Open", "MSFT"),
            ("High", "MSFT"),
            ("Low", "MSFT"),
            ("Close", "MSFT"),
            ("Volume", "MSFT"),
        ],
        names=["Field", "Ticker"],
    )
    return pd.DataFrame(
        [[149.0, 151.0, 148.0, 150.0, 10_000_000, 299.0, 301.0, 298.0, 300.0, 9_000_000]],
        index=dates,
        columns=columns,
    )


def test_multiindex_reshape_columns():
    raw_df = _mock_multiindex_df()
    shaped = reshape_download_frame(raw_df)
    assert list(shaped.columns) == ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]


def test_multiindex_reshape_values():
    raw_df = _mock_multiindex_df()
    shaped = reshape_download_frame(raw_df)
    aapl_close = shaped.loc[shaped["Ticker"] == "AAPL", "Close"].iloc[0]
    assert aapl_close == 150.0


def test_get_tickers_without_sic_field_keeps_valid_tickers(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1, "NVIDIA", "NVDA", "Nasdaq"],
                    [2, "WarrantCo", "ABCDW", "NYSE"],
                ],
            }

    monkeypatch.setattr("fetcher.requests.get", lambda *_args, **_kwargs: _Resp())
    tickers = get_tickers()
    assert tickers == ["NVDA"]


def test_get_tickers_with_sic_field_applies_sic_filter(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange", "sic"],
                "data": [
                    [1, "FinTrust", "FTRS", "NYSE", 6700],
                    [2, "Industrial", "INDS", "NYSE", 2000],
                ],
            }

    monkeypatch.setattr("fetcher.requests.get", lambda *_args, **_kwargs: _Resp())
    tickers = get_tickers()
    assert tickers == ["INDS"]


def test_get_tickers_ignores_otc_exchange(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1, "On Exchange", "NORM", "Nasdaq"],
                    [2, "OTC Name", "OTCT", "OTCQX"],
                ],
            }

    monkeypatch.setattr("fetcher.requests.get", lambda *_args, **_kwargs: _Resp())
    tickers = get_tickers()
    assert tickers == ["NORM"]


def test_get_tickers_excludes_dash_class_share_symbols(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1, "Normal Co", "NORM", "NYSE"],
                    [2, "Class Share Co", "BF-B", "NYSE"],
                ],
            }

    monkeypatch.setattr("fetcher.requests.get", lambda *_args, **_kwargs: _Resp())
    tickers = get_tickers()
    assert tickers == ["NORM"]


def test_get_tickers_excludes_missing_exchange(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1, "Listed", "NORM", "Nasdaq"],
                    [2, "Unlisted", "UNLS", None],
                ],
            }

    monkeypatch.setattr("fetcher.requests.get", lambda *_args, **_kwargs: _Resp())
    tickers = get_tickers()
    assert tickers == ["NORM"]


def test_get_ticker_sections_marks_biotech_from_company_name(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1, "Alpha Therapeutics Inc.", "ALPH", "Nasdaq"],
                    [2, "Normal Industrial Co", "NORM", "NYSE"],
                ],
            }

    monkeypatch.setattr("fetcher.requests.get", lambda *_args, **_kwargs: _Resp())
    sections = get_ticker_sections(["ALPH", "NORM"])
    assert sections == {"ALPH": BIOTECH_SECTION, "NORM": DEFAULT_SECTION}


def test_get_ticker_sections_marks_biotech_from_sic(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange", "sic"],
                "data": [
                    [1, "Neutral Name", "BIO1", "Nasdaq", 2836],
                    [2, "Another Name", "NORM", "NYSE", 2000],
                ],
            }

    monkeypatch.setattr("fetcher.requests.get", lambda *_args, **_kwargs: _Resp())
    sections = get_ticker_sections(["BIO1", "NORM"])
    assert sections == {"BIO1": BIOTECH_SECTION, "NORM": DEFAULT_SECTION}


def test_extract_ticker_metadata_from_equity_info():
    metadata = _extract_ticker_metadata_from_info(
        {
            "sectorDisp": "Technology",
            "industryDisp": "Semiconductors",
            "quoteType": "EQUITY",
        }
    )

    assert metadata == {"sector": "Technology", "industry": "Semiconductors", "fifty_two_week_high": None}


def test_extract_ticker_metadata_from_etf_info_uses_type_and_category():
    metadata = _extract_ticker_metadata_from_info(
        {
            "quoteType": "ETF",
            "typeDisp": "ETF",
            "category": "Trading--Leveraged Equity",
            "fundFamily": "ProShares",
        }
    )

    assert metadata == {"sector": "ETF", "industry": "Trading--Leveraged Equity", "fifty_two_week_high": None}


def test_get_ticker_metadata_reuses_cached_null_high(tmp_path, monkeypatch):
    db_path = tmp_path / "metadata.db"
    conn = init_db(db_path)
    save_ticker_metadata(
        conn,
        {
            "NULL": {
                "sector": "Technology",
                "industry": "Software",
                "fifty_two_week_high": None,
            }
        },
    )
    conn.close()

    def unexpected_fetch(_ticker):
        raise AssertionError("cached ticker should not be fetched")

    monkeypatch.setattr("fetcher._fetch_ticker_metadata_for_ticker", unexpected_fetch)

    result = get_ticker_metadata(["NULL"], db_path=db_path)

    assert result["NULL"]["fifty_two_week_high"] is None


def test_get_ticker_metadata_saves_successes_and_warns_on_failures(tmp_path, monkeypatch, caplog):
    db_path = tmp_path / "metadata.db"
    good = {
        "sector": "Technology",
        "industry": "Semiconductors",
        "fifty_two_week_high": 150.0,
    }

    def fetch(ticker):
        if ticker in {"ZZZ", "AAA"}:
            raise RuntimeError("Too Many Requests")
        return ticker, good

    monkeypatch.setattr("fetcher._fetch_ticker_metadata_for_ticker", fetch)

    with caplog.at_level(logging.WARNING, logger="fetcher"):
        result = get_ticker_metadata(["ZZZ", "GOOD", "AAA"], db_path=db_path)

    assert result == {"GOOD": good}
    assert caplog.messages == ["Yahoo metadata unavailable for 2 tickers: AAA, ZZZ"]

    conn = init_db(db_path)
    persisted = get_cached_ticker_metadata(conn, ["GOOD", "AAA", "ZZZ"])
    conn.close()
    assert persisted == {"GOOD": good}


def test_get_ticker_metadata_refreshes_cached_ticker(tmp_path, monkeypatch):
    db_path = tmp_path / "metadata.db"
    conn = init_db(db_path)
    save_ticker_metadata(
        conn,
        {
            "AAA": {
                "sector": "Old",
                "industry": "Old",
                "fifty_two_week_high": None,
            }
        },
    )
    conn.close()
    refreshed = {
        "sector": "Technology",
        "industry": "Software",
        "fifty_two_week_high": 200.0,
    }
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        return ticker, refreshed

    monkeypatch.setattr("fetcher._fetch_ticker_metadata_for_ticker", fetch)

    result = get_ticker_metadata(["AAA"], db_path=db_path, refresh=True)

    assert calls == ["AAA"]
    assert result == {"AAA": refreshed}


def test_get_ticker_metadata_refetches_stale_cache_entry(tmp_path, monkeypatch):
    db_path = tmp_path / "metadata.db"
    conn = init_db(db_path)
    save_ticker_metadata(
        conn,
        {
            "AAA": {
                "sector": "Technology",
                "industry": "Software",
                "fifty_two_week_high": 100.0,
            }
        },
    )
    conn.execute(
        "UPDATE ticker_metadata SET updated_at = ? WHERE ticker = ?",
        ("2020-01-01 00:00:00+00:00", "AAA"),
    )
    conn.commit()
    conn.close()

    refreshed = {
        "sector": "Technology",
        "industry": "Software",
        "fifty_two_week_high": 200.0,
    }
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        return ticker, refreshed

    monkeypatch.setattr("fetcher._fetch_ticker_metadata_for_ticker", fetch)

    result = get_ticker_metadata(["AAA"], db_path=db_path)

    assert calls == ["AAA"]
    assert result == {"AAA": refreshed}


def test_get_sp500_tickers_cached_only_reads_local_cache(tmp_path):
    cache_path = tmp_path / "sp500_tickers.txt"
    cache_path.write_text("MSFT\nAAPL\n")

    tickers = get_sp500_tickers_cached_only(cache_path)

    assert tickers == ["AAPL", "MSFT"]


def test_get_sp500_tickers_cached_only_raises_when_missing(tmp_path):
    with pytest.raises(UniverseCacheMissError):
        get_sp500_tickers_cached_only(tmp_path / "missing.txt")


def test_market_has_closed_today_before_close():
    now = datetime(2026, 8, 10, 14, 30, tzinfo=_ET)  # 2:30pm ET
    assert _market_has_closed_today(now) is False


def test_market_has_closed_today_after_close():
    now = datetime(2026, 8, 10, 16, 30, tzinfo=_ET)  # 4:30pm ET
    assert _market_has_closed_today(now) is True


def test_fetch_cutoff_date_excludes_today_before_close():
    now = datetime(2026, 8, 10, 14, 30, tzinfo=_ET)
    assert _fetch_cutoff_date(now).isoformat() == "2026-08-10"


def test_fetch_cutoff_date_includes_today_after_close():
    now = datetime(2026, 8, 10, 16, 30, tzinfo=_ET)
    assert _fetch_cutoff_date(now).isoformat() == "2026-08-11"


def test_yfinance_end_date_bumps_todays_request_after_close():
    now = datetime(2026, 8, 10, 16, 30, tzinfo=_ET)
    assert _yfinance_end_date("2026-08-10", now) == "2026-08-11"


def test_yfinance_end_date_leaves_todays_request_alone_before_close():
    now = datetime(2026, 8, 10, 14, 30, tzinfo=_ET)
    assert _yfinance_end_date("2026-08-10", now) == "2026-08-10"


def test_yfinance_end_date_leaves_historical_request_alone_after_close():
    now = datetime(2026, 8, 10, 16, 30, tzinfo=_ET)
    assert _yfinance_end_date("2026-07-01", now) == "2026-07-01"


class _FixedDatetime(datetime):
    """Patches fetcher.datetime.now(...) to a fixed instant for fetch_data tests."""

    _fixed_now: datetime

    @classmethod
    def now(cls, tz=None):
        return cls._fixed_now.astimezone(tz) if tz else cls._fixed_now


def _mock_download_including_today(requested, start, end, **_kwargs):
    # Ignores the requested `end` bound entirely, simulating yfinance having
    # already posted today's now-closed bar -- this isolates fetch_data's own
    # post-download filter as the thing under test, independent of whatever
    # end value was actually sent to yfinance.
    dates = pd.to_datetime(["2026-08-07", "2026-08-10"])
    columns = pd.MultiIndex.from_tuples(
        [(field, "AAPL") for field in ("Open", "High", "Low", "Close", "Volume")],
        names=["Field", "Ticker"],
    )
    return pd.DataFrame(
        [[100.0, 101.0, 99.0, 100.5, 1_000_000], [102.0, 103.0, 101.0, 102.5, 1_100_000]],
        index=dates,
        columns=columns,
    )


def test_fetch_data_excludes_todays_bar_before_close(tmp_path, monkeypatch):
    fixed_now = datetime(2026, 8, 10, 14, 30, tzinfo=_ET)  # 2:30pm ET, market open
    _FixedDatetime._fixed_now = fixed_now
    monkeypatch.setattr(fetcher, "datetime", _FixedDatetime)
    monkeypatch.setattr(fetcher.yf, "download", _mock_download_including_today)

    result = fetch_data(
        tickers=["AAPL"], low_start="2026-08-01", end_date="2026-08-10",
        cache_dir=tmp_path, db_path=tmp_path / "test.db",
    )

    assert set(pd.to_datetime(result["Date"]).dt.date.astype(str)) == {"2026-08-07"}


def test_fetch_data_includes_todays_bar_after_close(tmp_path, monkeypatch):
    fixed_now = datetime(2026, 8, 10, 16, 30, tzinfo=_ET)  # 4:30pm ET, market closed
    _FixedDatetime._fixed_now = fixed_now
    monkeypatch.setattr(fetcher, "datetime", _FixedDatetime)
    monkeypatch.setattr(fetcher.yf, "download", _mock_download_including_today)

    result = fetch_data(
        tickers=["AAPL"], low_start="2026-08-01", end_date="2026-08-10",
        cache_dir=tmp_path, db_path=tmp_path / "test.db",
    )

    assert set(pd.to_datetime(result["Date"]).dt.date.astype(str)) == {"2026-08-07", "2026-08-10"}
