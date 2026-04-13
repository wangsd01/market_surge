from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


def init_db(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screening_runs (
            id INTEGER PRIMARY KEY,
            run_at TIMESTAMP NOT NULL,
            low_start DATE NOT NULL,
            low_end DATE NOT NULL,
            min_price FLOAT NOT NULL,
            min_dollar_vol FLOAT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_screening_runs_run_date ON screening_runs(date(run_at))"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            run_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            low_date DATE,
            low_price FLOAT,
            current_price FLOAT,
            bounce_pct FLOAT,
            dollar_vol FLOAT,
            sector TEXT,
            industry TEXT,
            PRIMARY KEY (run_id, ticker),
            FOREIGN KEY (run_id) REFERENCES screening_runs(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_ticker ON results(ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_bounce ON results(bounce_pct DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_price_history (
            date DATE NOT NULL,
            ticker TEXT NOT NULL,
            open FLOAT,
            high FLOAT,
            low FLOAT,
            close FLOAT,
            volume FLOAT,
            PRIMARY KEY (date, ticker)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_price_ticker_date ON raw_price_history(ticker, date)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invalid_tickers (
            ticker TEXT NOT NULL,
            source TEXT NOT NULL,
            reason TEXT,
            detected_at TIMESTAMP NOT NULL,
            PRIMARY KEY (ticker, source)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ticker_metadata (
            ticker TEXT PRIMARY KEY,
            sector TEXT,
            industry TEXT,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )
    _migrate_screening_runs_max_to_min_price(conn)
    _migrate_results_add_industry(conn)
    return conn


def _migrate_screening_runs_max_to_min_price(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(screening_runs)").fetchall()}
    if "min_price" in cols:
        return
    if "max_price" in cols:
        conn.execute("ALTER TABLE screening_runs ADD COLUMN min_price FLOAT")
        conn.execute("UPDATE screening_runs SET min_price = max_price WHERE min_price IS NULL")


def _migrate_results_add_industry(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(results)").fetchall()}
    if "industry" not in cols:
        conn.execute("ALTER TABLE results ADD COLUMN industry TEXT")


def _pick(df: pd.DataFrame, idx: int, *candidates: str) -> Any:
    for candidate in candidates:
        if candidate in df.columns:
            value = df.iloc[idx][candidate]
            if pd.isna(value):
                return None
            return value
    return None


def save_run(conn: sqlite3.Connection, params: dict[str, Any], results_df: pd.DataFrame) -> int:
    run_at = params.get("run_at") or datetime.now(UTC).replace(microsecond=0).isoformat(sep=" ")
    low_start = params["low_start"]
    low_end = params["low_end"]
    min_price = float(params["min_price"])
    min_dollar_vol = float(params["min_dollar_vol"])

    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO screening_runs
            (run_at, low_start, low_end, min_price, min_dollar_vol)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_at, low_start, low_end, min_price, min_dollar_vol),
        )

        run_id_row = conn.execute(
            "SELECT id FROM screening_runs WHERE date(run_at) = date(?) ORDER BY id DESC LIMIT 1",
            (run_at,),
        ).fetchone()
        if run_id_row is None:
            raise RuntimeError("Failed to resolve run id after saving screening_runs row.")
        run_id = int(run_id_row[0])

        records = []
        if results_df is not None and not results_df.empty:
            for idx in range(len(results_df)):
                records.append(
                    (
                        run_id,
                        _pick(results_df, idx, "ticker", "Ticker"),
                        _pick(results_df, idx, "low_date", "Low Date"),
                        _pick(results_df, idx, "low_price", "Low", "low"),
                        _pick(results_df, idx, "current_price", "Current", "Close"),
                        _pick(results_df, idx, "bounce_pct", "Bounce %"),
                        _pick(results_df, idx, "dollar_vol", "Vol*Price"),
                        _pick(results_df, idx, "sector", "Sector"),
                        _pick(results_df, idx, "industry", "Industry"),
                    )
                )

        conn.execute("DELETE FROM results WHERE run_id = ?", (run_id,))
        if records:
            conn.executemany(
                """
                INSERT OR REPLACE INTO results
                (run_id, ticker, low_date, low_price, current_price, bounce_pct, dollar_vol, sector, industry)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

    return run_id


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, run_at, low_start, low_end, min_price, min_dollar_vol
        FROM screening_runs
        WHERE id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"No screening run found for id={run_id}")
    return {
        "id": row[0],
        "run_at": row[1],
        "low_start": row[2],
        "low_end": row[3],
        "min_price": row[4],
        "min_dollar_vol": row[5],
    }


def save_price_history(conn: sqlite3.Connection, price_df: pd.DataFrame) -> None:
    if price_df is None or price_df.empty:
        return

    working = price_df.copy()
    working["Date"] = pd.to_datetime(working["Date"]).dt.date.astype(str)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in working.columns:
            working[col] = pd.to_numeric(working[col], errors="coerce")
    price_cols = [col for col in ("Open", "High", "Low", "Close", "Volume") if col in working.columns]
    if price_cols:
        working = working.loc[~working[price_cols].isna().all(axis=1)].copy()
    working = working.loc[working["Ticker"].notna()].copy()
    if working.empty:
        return

    records = []
    for _, row in working.iterrows():
        records.append(
            (
                row.get("Date"),
                row.get("Ticker"),
                row.get("Open"),
                row.get("High"),
                row.get("Low"),
                row.get("Close"),
                row.get("Volume"),
            )
        )

    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO raw_price_history
            (date, ticker, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )


def delete_price_history_for_date(conn: sqlite3.Connection, target_date: str) -> None:
    with conn:
        conn.execute("DELETE FROM raw_price_history WHERE date = ?", (target_date,))


def get_cached_price_history(
    conn: sqlite3.Connection,
    tickers: list[str],
    low_start: str,
    end_date: str,
) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame(columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])

    placeholders = ",".join("?" for _ in tickers)
    params: list[Any] = [*tickers, low_start, end_date]
    query = f"""
        SELECT
            date AS Date,
            ticker AS Ticker,
            open AS Open,
            high AS High,
            low AS Low,
            close AS Close,
            volume AS Volume
        FROM raw_price_history
        WHERE ticker IN ({placeholders})
          AND date >= ?
          AND date < ?
          AND low IS NOT NULL
          AND close IS NOT NULL
          AND volume IS NOT NULL
        ORDER BY date ASC, ticker ASC
    """
    df = pd.read_sql_query(query, conn, params=params)
    if df.empty:
        return df
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def has_cached_coverage(
    conn: sqlite3.Connection,
    tickers: list[str],
    low_start: str,
    end_date: str,
) -> bool:
    if not tickers:
        return True

    placeholders = ",".join("?" for _ in tickers)
    params: list[Any] = [*tickers, low_start, end_date]
    query = f"""
        SELECT ticker, COUNT(*) AS row_count
        FROM raw_price_history
        WHERE ticker IN ({placeholders})
          AND date >= ?
          AND date < ?
          AND low IS NOT NULL
          AND close IS NOT NULL
          AND volume IS NOT NULL
        GROUP BY ticker
    """
    rows = conn.execute(query, params).fetchall()
    seen = {row[0] for row in rows if int(row[1]) > 0}
    return seen == set(tickers)


def get_invalid_tickers(conn: sqlite3.Connection, source: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT ticker
        FROM invalid_tickers
        WHERE source = ?
        """,
        (source,),
    ).fetchall()
    return {str(row[0]).upper() for row in rows if row and row[0]}


def save_invalid_tickers(
    conn: sqlite3.Connection,
    tickers: list[str],
    source: str,
    reason: str,
) -> None:
    normalized = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
    if not normalized:
        return

    detected_at = datetime.now(UTC).replace(microsecond=0).isoformat(sep=" ")
    records = [(ticker, source, reason, detected_at) for ticker in normalized]
    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO invalid_tickers
            (ticker, source, reason, detected_at)
            VALUES (?, ?, ?, ?)
            """,
            records,
        )


def delete_invalid_tickers(conn: sqlite3.Connection, tickers: list[str], source: str) -> None:
    normalized = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
    if not normalized:
        return

    placeholders = ",".join("?" for _ in normalized)
    params: list[Any] = [source, *normalized]
    with conn:
        conn.execute(
            f"""
            DELETE FROM invalid_tickers
            WHERE source = ?
              AND ticker IN ({placeholders})
            """,
            params,
        )


def get_ticker_metadata(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, dict[str, str]]:
    normalized = [str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()]
    if not normalized:
        return {}

    placeholders = ",".join("?" for _ in normalized)
    rows = conn.execute(
        f"""
        SELECT ticker, sector, industry
        FROM ticker_metadata
        WHERE ticker IN ({placeholders})
        """,
        normalized,
    ).fetchall()
    return {
        str(ticker).upper(): {
            "sector": "" if sector is None else str(sector),
            "industry": "" if industry is None else str(industry),
        }
        for ticker, sector, industry in rows
    }


def save_ticker_metadata(conn: sqlite3.Connection, metadata_by_ticker: dict[str, dict[str, str]]) -> None:
    if not metadata_by_ticker:
        return

    updated_at = datetime.now(UTC).replace(microsecond=0).isoformat(sep=" ")
    records = [
        (
            str(ticker).strip().upper(),
            str(values.get("sector", "")).strip(),
            str(values.get("industry", "")).strip(),
            updated_at,
        )
        for ticker, values in metadata_by_ticker.items()
        if str(ticker).strip()
    ]
    if not records:
        return

    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO ticker_metadata
            (ticker, sector, industry, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            records,
        )
