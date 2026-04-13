import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _resolve_price_column(df: pd.DataFrame) -> str:
    for candidate in ("current_price", "Current", "Close"):
        if candidate in df.columns:
            return candidate
    raise KeyError("No price column found. Expected one of: current_price, Current, Close")


def _extract_ticker(df_window: pd.DataFrame) -> Optional[str]:
    if "Ticker" not in df_window.columns or df_window.empty:
        return None
    value = df_window["Ticker"].iloc[0]
    if pd.isna(value):
        return None
    return str(value)


def compute_bounce(df_window: pd.DataFrame, current_close: float) -> float:
    if df_window is None or df_window.empty:
        return np.nan
    if pd.isna(current_close):
        return np.nan
    if "Low" not in df_window.columns:
        return np.nan

    min_low = pd.to_numeric(df_window["Low"], errors="coerce").min()
    if pd.isna(min_low) or float(min_low) == 0.0:
        return np.nan

    bounce_pct = (float(current_close) - float(min_low)) / float(min_low) * 100.0
    if bounce_pct > 500.0:
        ticker = _extract_ticker(df_window)
        if ticker:
            logger.warning("Extreme bounce detected for %s: %.1f%%", ticker, bounce_pct)
        else:
            logger.warning("Extreme bounce detected: %.1f%%", bounce_pct)
    return float(bounce_pct)


def apply_price_filter(df: pd.DataFrame, min_price: float) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy()
    price_col = _resolve_price_column(df)
    return df.loc[df[price_col] > min_price].copy()


def _aggregate_dollar_volume(df: pd.DataFrame) -> pd.DataFrame:
    if "avg_vol_50d" in df.columns:
        price_col = _resolve_price_column(df)
        out = df.copy()
        out["dollar_vol"] = pd.to_numeric(out["avg_vol_50d"], errors="coerce") * pd.to_numeric(
            out[price_col], errors="coerce"
        )
        return out

    if "Ticker" not in df.columns or "Volume" not in df.columns:
        raise KeyError("Expected Ticker and Volume columns for history-based dollar volume.")

    price_col = _resolve_price_column(df)
    working = df.copy()
    if "Date" in working.columns:
        working = working.sort_values(["Ticker", "Date"])

    rows = []
    for ticker, group in working.groupby("Ticker", sort=False):
        recent = group.tail(50)
        avg_vol = pd.to_numeric(recent["Volume"], errors="coerce").mean()
        current_price = pd.to_numeric(recent[price_col], errors="coerce").iloc[-1]
        dollar_vol = avg_vol * current_price
        rows.append(
            {
                "Ticker": ticker,
                "current_price": float(current_price),
                "avg_vol_50d": float(avg_vol),
                "dollar_vol": float(dollar_vol),
            }
        )
    return pd.DataFrame(rows)


def apply_dollar_vol_filter(df: pd.DataFrame, min_dollar_vol: float) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy()
    aggregated = _aggregate_dollar_volume(df)
    return aggregated.loc[aggregated["dollar_vol"] >= float(min_dollar_vol)].copy()
