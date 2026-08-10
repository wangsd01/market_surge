"""End-to-end synthetic scenarios for the full brooks_screener pipeline.

Each scenario builds an explicit OHLCV price path (no network, no real
tickers) through a shared quiet-uptrend base plus a hand-choreographed tail,
matching the 7 scenarios required by the design doc: H1 only, clean H2, H2
already extended, failed H2, strong continuation with no H2, breakout with
poor follow-through, and strong breakout but bad reward/risk.
"""
import pandas as pd

import brooks_screener
from brooks.config import BrooksConfig


def _quiet_uptrend(n=55, start=100.0, step=0.15):
    rows = []
    for i in range(n):
        c = start + i * step
        rows.append({"Open": c - 0.05, "High": c + 0.3, "Low": c - 0.3, "Close": c + 0.1, "Volume": 1_000_000})
    return rows


def _to_df(rows):
    dates = pd.date_range("2024-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=dates)[["Open", "High", "Low", "Close", "Volume"]]


def _h1_h2_tail(c):
    """A (swing high/resistance) -> B,C (pullback, C=H1 signal) -> D (H1 trigger)
    -> E (continuation, stays below A's high so it can't re-trigger a fresh
    breakout) -> F (second pullback, H2 signal) -> G (H2 trigger)."""
    return [
        {"Open": c, "High": c + 1.5, "Low": c - 0.2, "Close": c + 1.4, "Volume": 1_100_000},
        {"Open": c + 1.4, "High": c + 1.0, "Low": c + 0.5, "Close": c + 0.7, "Volume": 1_000_000},
        {"Open": c + 0.7, "High": c + 0.6, "Low": c + 0.2, "Close": c + 0.4, "Volume": 1_000_000},
        {"Open": c + 0.4, "High": c + 1.1, "Low": c + 0.3, "Close": c + 1.0, "Volume": 1_100_000},
        {"Open": c + 1.0, "High": c + 1.3, "Low": c + 0.9, "Close": c + 1.2, "Volume": 1_100_000},
        {"Open": c + 1.2, "High": c + 1.0, "Low": c + 0.7, "Close": c + 0.85, "Volume": 1_000_000},
        {"Open": c + 0.85, "High": c + 1.15, "Low": c + 0.75, "Close": c + 1.1, "Volume": 1_300_000},
    ]


def _run(rows):
    return brooks_screener.run_ticker(_to_df(rows), "TEST", dollar_vol=50_000_000, config=BrooksConfig())


def test_scenario_h1_only():
    rows = _quiet_uptrend()
    c = rows[-1]["Close"]
    rows += [
        {"Open": c, "High": c + 4, "Low": c - 0.5, "Close": c + 3.8, "Volume": 1_500_000},  # swing high
        {"Open": c + 3.8, "High": c + 2, "Low": c + 1, "Close": c + 1.5, "Volume": 1_000_000},  # pullback
        {"Open": c + 1.5, "High": c + 1.2, "Low": c + 0.5, "Close": c + 0.8, "Volume": 1_000_000},  # signal bar
        {"Open": c + 0.8, "High": c + 2.2, "Low": c + 0.6, "Close": c + 2.0, "Volume": 1_200_000},  # H1 trigger, last bar
    ]
    row = _run(rows)
    assert row["setup_state"] in {"H1_TRIGGERED_TODAY", "H1_TRIGGERED_RECENTLY", "H1_FORMING"}
    assert row["h2_status"] is None


def _clean_h2_row():
    rows = _quiet_uptrend()
    return _run(rows + _h1_h2_tail(rows[-1]["Close"]))


def test_scenario_clean_h2():
    row = _clean_h2_row()
    assert row["setup_state"] in {"H2_TRIGGERED_TODAY", "H2_TRIGGERED_RECENTLY"}
    assert row["h2_status"] == "triggered"


def test_scenario_h2_already_extended():
    rows = _quiet_uptrend()
    tail = _h1_h2_tail(rows[-1]["Close"])
    gclose = tail[-1]["Close"]
    for _ in range(4):
        tail.append({"Open": gclose, "High": gclose + 2.0, "Low": gclose - 0.05, "Close": gclose + 1.9, "Volume": 1_800_000})
        gclose = tail[-1]["Close"]
    row = _run(rows + tail)
    assert row["setup_state"] == "EXTENDED_AFTER_H2"


def test_scenario_failed_h2():
    rows = _quiet_uptrend()
    c = rows[-1]["Close"]
    tail = _h1_h2_tail(c)
    # a bar trading below F's pullback low (c + 0.7, the H2 pullback leg low)
    tail.append({"Open": tail[-1]["Close"], "High": tail[-1]["Close"] + 0.1, "Low": c + 0.3, "Close": c + 0.4, "Volume": 2_000_000})
    row = _run(rows + tail)
    assert row["setup_state"] == "FAILED_H2"


def test_scenario_strong_continuation_no_h2():
    rows = _quiet_uptrend()
    c = rows[-1]["Close"]
    tail = [
        {"Open": c, "High": c + 1.5, "Low": c - 0.2, "Close": c + 1.4, "Volume": 1_500_000},  # breakout
        {"Open": c + 1.4, "High": c + 1.6, "Low": c + 1.3, "Close": c + 1.55, "Volume": 1_100_000},  # modest continuation
        {"Open": c + 1.55, "High": c + 1.7, "Low": c + 1.45, "Close": c + 1.65, "Volume": 1_100_000},  # modest continuation
    ]
    row = _run(rows + tail)
    assert row["setup_state"] == "STRONG_BREAKOUT_FOLLOW_THROUGH"
    assert row["h1_status"] is None


def test_scenario_breakout_poor_follow_through():
    rows = _quiet_uptrend()
    c = rows[-1]["Close"]
    tail = [
        {"Open": c, "High": c + 1.5, "Low": c - 0.2, "Close": c + 1.4, "Volume": 1_500_000},  # breakout
        {"Open": c + 1.4, "High": c + 1.5, "Low": c - 1.0, "Close": c - 0.8, "Volume": 2_000_000},  # hard bear reversal
    ]
    row = _run(rows + tail)
    assert row["setup_state"] == "FAILED_H1"
    assert row["follow_through_score"] < 0


def test_scenario_strong_breakout_bad_reward_risk():
    def quiet_uptrend_with_shelf(n=55, start=100.0, step=0.15, shelf_idx=30, shelf_height=0.3):
        rows = []
        for i in range(n):
            c = start + i * step
            if i == shelf_idx:
                rows.append({"Open": c, "High": c + shelf_height, "Low": c - 0.3, "Close": c + shelf_height - 0.1, "Volume": 1_000_000})
            elif i == shelf_idx + 1:
                rows.append({"Open": c + shelf_height - 0.1, "High": c + shelf_height - 0.2, "Low": c - 0.2, "Close": c, "Volume": 1_000_000})
            else:
                rows.append({"Open": c - 0.05, "High": c + 0.3, "Low": c - 0.3, "Close": c + 0.1, "Volume": 1_000_000})
        return rows

    rows = quiet_uptrend_with_shelf()
    c = rows[-1]["Close"]
    rows += [
        {"Open": c, "High": c + 1.5, "Low": c - 0.2, "Close": c + 1.4, "Volume": 1_100_000},  # A resistance
        {"Open": c + 1.4, "High": c + 1.0, "Low": c + 0.5, "Close": c + 0.7, "Volume": 1_000_000},  # B pullback
        {"Open": c + 0.7, "High": c + 1.46, "Low": c + 0.2, "Close": c + 1.4, "Volume": 1_000_000},  # C signal (shallow, near ceiling)
        {"Open": c + 1.4, "High": c + 1.48, "Low": c + 1.3, "Close": c + 1.47, "Volume": 1_100_000},  # D H1 trigger
    ]
    row = _run(rows)
    config = BrooksConfig()

    assert row["rr_target_1"] < config.min_plausible_rr

    result_df = pd.DataFrame([row])
    buckets = brooks_screener.build_watchlist_buckets(result_df, config)
    assert len(buckets["READY_NOW"]) == 0  # excluded despite a clean-looking trigger state


def test_ranking_prefers_clean_pullback_over_extended():
    clean_h2_row = _clean_h2_row()
    extended_rows = _quiet_uptrend()
    extended_tail = _h1_h2_tail(extended_rows[-1]["Close"])
    gclose = extended_tail[-1]["Close"]
    for _ in range(4):
        extended_tail.append({"Open": gclose, "High": gclose + 2.0, "Low": gclose - 0.05, "Close": gclose + 1.9, "Volume": 1_800_000})
        gclose = extended_tail[-1]["Close"]
    extended_row = _run(extended_rows + extended_tail)

    assert clean_h2_row["setup_state"] in {"H2_TRIGGERED_TODAY", "H2_TRIGGERED_RECENTLY"}
    assert extended_row["setup_state"] == "EXTENDED_AFTER_H2"
    assert clean_h2_row["trade_score"] > extended_row["trade_score"]
