from __future__ import annotations

import pandas as pd

from brooks.config import BrooksConfig


def compute_features(df: pd.DataFrame, config: BrooksConfig) -> pd.DataFrame:
    out = df.copy()
    prior_close = out["Close"].shift(1)
    prior_high = out["High"].shift(1)

    out["daily_return"] = out["Close"].pct_change()
    out["gap_pct"] = (out["Open"] - prior_close) / prior_close
    out["true_gap_up"] = out["Low"] > prior_high

    bar_range = (out["High"] - out["Low"]).replace(0, float("nan"))
    body = (out["Close"] - out["Open"]).abs()
    out["body_pct"] = body / bar_range
    out["close_location"] = (out["Close"] - out["Low"]) / bar_range
    out["upper_tail_pct"] = (out["High"] - out[["Open", "Close"]].max(axis=1)) / bar_range
    out["lower_tail_pct"] = (out[["Open", "Close"]].min(axis=1) - out["Low"]) / bar_range

    true_range = pd.concat(
        [
            out["High"] - out["Low"],
            (out["High"] - prior_close).abs(),
            (out["Low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = true_range.rolling(config.atr_period, min_periods=config.atr_period).mean()
    out["range_atr_ratio"] = bar_range / out["atr14"]

    out["vol_sma20"] = out["Volume"].rolling(config.vol_avg_period, min_periods=config.vol_avg_period).mean()
    out["vol_ratio"] = out["Volume"] / out["vol_sma20"]

    out["ema20"] = out["Close"].ewm(span=config.ema_short, adjust=False).mean()
    out["ema50"] = out["Close"].ewm(span=config.ema_long, adjust=False).mean()
    out["dist_ema20_pct"] = (out["Close"] - out["ema20"]) / out["ema20"]
    out["dist_ema50_pct"] = (out["Close"] - out["ema50"]) / out["ema50"]

    for window in (20, 50, 252):
        recent_high = out["High"].shift(1).rolling(window, min_periods=1).max()
        out[f"recent_high_{window}"] = recent_high
    out["dist_from_20d_high_pct"] = (out["Close"] - out["recent_high_20"]) / out["recent_high_20"]
    out["dist_from_50d_high_pct"] = (out["Close"] - out["recent_high_50"]) / out["recent_high_50"]

    out["slope_20"] = _rolling_slope(out["Close"], config.slope_window_short)
    out["slope_50"] = _rolling_slope(out["Close"], config.slope_window_long)

    return out


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    def _slope(values):
        mean = values.mean()
        if mean == 0:
            return float("nan")
        x = range(len(values))
        slope = pd.Series(values).cov(pd.Series(x)) / pd.Series(x).var()
        return slope / mean

    return series.rolling(window, min_periods=window).apply(_slope, raw=True)
