import pandas as pd
import pytest

from fetcher import (
    BIOTECH_SECTION,
    DEFAULT_SECTION,
    UniverseCacheMissError,
    _extract_ticker_metadata_from_info,
    get_sp500_tickers_cached_only,
    get_ticker_sections,
    get_tickers,
    reshape_download_frame,
)


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


def test_get_sp500_tickers_cached_only_reads_local_cache(tmp_path):
    cache_path = tmp_path / "sp500_tickers.txt"
    cache_path.write_text("MSFT\nAAPL\n")

    tickers = get_sp500_tickers_cached_only(cache_path)

    assert tickers == ["AAPL", "MSFT"]


def test_get_sp500_tickers_cached_only_raises_when_missing(tmp_path):
    with pytest.raises(UniverseCacheMissError):
        get_sp500_tickers_cached_only(tmp_path / "missing.txt")
