import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from db import get_fifty_two_week_high, get_invalid_tickers, init_db, save_invalid_tickers


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    c = init_db(str(db_path))
    yield c
    c.close()


def _insert_invalid(conn: sqlite3.Connection, ticker: str, source: str, days_ago: float) -> None:
    detected_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(sep=" ")
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO invalid_tickers (ticker, source, reason, detected_at) VALUES (?, ?, ?, ?)",
            (ticker, source, "Yahoo returned no data for requested range 2026-03-30..2026-04-14", detected_at),
        )


def test_get_invalid_tickers_excludes_entries_older_than_ttl(conn):
    _insert_invalid(conn, "STALE", "yfinance", days_ago=8)
    _insert_invalid(conn, "FRESH", "yfinance", days_ago=2)

    result = get_invalid_tickers(conn, "yfinance", max_age_days=7)

    assert "FRESH" in result
    assert "STALE" not in result


def test_get_invalid_tickers_includes_entry_exactly_at_boundary(conn):
    _insert_invalid(conn, "EDGE", "yfinance", days_ago=6)

    result = get_invalid_tickers(conn, "yfinance", max_age_days=7)

    assert "EDGE" in result


def test_get_invalid_tickers_excludes_all_when_all_stale(conn):
    _insert_invalid(conn, "OLD1", "yfinance", days_ago=10)
    _insert_invalid(conn, "OLD2", "yfinance", days_ago=30)

    result = get_invalid_tickers(conn, "yfinance", max_age_days=7)

    assert result == set()


def test_get_invalid_tickers_respects_source_filter(conn):
    _insert_invalid(conn, "AAPL", "yfinance", days_ago=1)
    _insert_invalid(conn, "AAPL", "other_source", days_ago=1)

    result = get_invalid_tickers(conn, "yfinance", max_age_days=7)

    assert "AAPL" in result
    assert len(result) == 1


def _insert_bar(conn: sqlite3.Connection, ticker: str, date_str: str, high: float) -> None:
    with conn:
        conn.execute(
            "INSERT INTO raw_price_history (date, ticker, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date_str, ticker, high, high, high, high, 1_000_000),
        )


def test_get_fifty_two_week_high_returns_max_high_within_window(conn):
    _insert_bar(conn, "AAA", "2026-01-10", 10.0)
    _insert_bar(conn, "AAA", "2026-06-15", 25.0)

    result = get_fifty_two_week_high(conn, ["AAA"], as_of_date="2026-08-24")

    assert result == {"AAA": 25.0}


def test_get_fifty_two_week_high_excludes_bars_older_than_lookback(conn):
    _insert_bar(conn, "AAA", "2026-06-15", 25.0)
    _insert_bar(conn, "AAA", "2024-01-01", 999.0)

    result = get_fifty_two_week_high(conn, ["AAA"], as_of_date="2026-08-24")

    assert result == {"AAA": 25.0}


def test_get_fifty_two_week_high_only_returns_requested_tickers(conn):
    _insert_bar(conn, "AAA", "2026-06-15", 25.0)
    _insert_bar(conn, "BBB", "2026-06-15", 999.0)

    result = get_fifty_two_week_high(conn, ["AAA"], as_of_date="2026-08-24")

    assert result == {"AAA": 25.0}


def test_get_fifty_two_week_high_returns_empty_for_ticker_with_no_history(conn):
    result = get_fifty_two_week_high(conn, ["NOPE"], as_of_date="2026-08-24")

    assert result == {}
