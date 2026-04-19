from __future__ import annotations

from datetime import date

import pandas as pd

from patterns.high2 import High2Detector


def _df(rows: list[tuple[float, float, float, float, int]]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(
        [
            {"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}
            for o, h, l, c, v in rows
        ],
        index=dates,
    )


def _valid_h2_rows() -> list[tuple[float, float, float, float, int]]:
    return [
        (99.8, 100.4, 99.4, 100.0, 900_000),
        (100.0, 100.9, 99.8, 100.6, 920_000),
        (100.6, 101.2, 100.1, 100.9, 930_000),
        (100.9, 101.5, 100.4, 101.3, 940_000),
        (101.3, 101.9, 100.9, 101.7, 950_000),
        (101.7, 102.6, 101.2, 102.2, 960_000),
        (102.2, 103.5, 102.0, 103.0, 970_000),
        (103.0, 104.3, 102.8, 103.9, 980_000),
        (103.9, 105.1, 103.6, 104.8, 990_000),
        (104.8, 105.6, 104.1, 105.0, 995_000),
        (104.3, 104.6, 103.8, 103.9, 980_000),
        (103.9, 104.1, 103.6, 103.7, 970_000),
        (103.7, 104.7, 103.5, 103.9, 960_000),
        (103.9, 104.7, 103.7, 104.0, 950_000),
        (104.0, 104.8, 103.9, 104.1, 940_000),
        (105.0, 105.9, 104.9, 105.8, 1_700_000),
    ]


def _prepend_filler(
    rows: list[tuple[float, float, float, float, int]],
    *,
    count: int = 34,
    start: float = 80.0,
) -> list[tuple[float, float, float, float, int]]:
    filler: list[tuple[float, float, float, float, int]] = []
    price = start
    for _ in range(count):
        filler.append((price, price + 0.6, price - 0.4, price + 0.2, 800_000))
        price += 0.3
    return filler + rows


def test_detects_valid_high2_sequence():
    df = _df(_valid_h2_rows())

    result = High2Detector().detect(df, "TEST")

    assert result is not None
    assert result.pattern == "high2"
    assert result.ticker == "TEST"
    assert result.pivots["prior_swing_high"] == 105.6
    assert result.pivots["pullback_low"] == 103.6
    assert result.pivots["h1_high"] == 104.7
    assert result.pivots["h2_high"] == 105.9
    assert result.pivots["h2_low"] == 104.9
    assert result.pivot_dates["h2_high"] == df.index[15].date()
    assert result.pivot_dates["h2_low"] == df.index[15].date()
    assert result.metadata["ail_start_idx"] == 0
    assert result.metadata["pullback_start_idx"] == 10
    assert result.metadata["pullback_end_idx"] == 11
    assert result.metadata["h1_idx"] == 12
    assert result.metadata["h2_idx"] == 15
    assert abs(result.metadata["prior_leg_height"] - 6.2) < 1e-9
    assert 0.0 <= result.confidence <= 1.0


def test_rejects_trading_range_context():
    rows = [
        (100.0, 100.8, 99.7, 100.2, 900_000),
        (100.2, 100.9, 99.9, 100.4, 900_000),
        (100.4, 101.0, 100.0, 100.5, 900_000),
        (100.5, 101.1, 100.2, 100.6, 900_000),
        (100.6, 101.2, 100.4, 100.8, 900_000),
        (100.8, 101.3, 100.6, 101.0, 900_000),
        (101.0, 101.4, 100.8, 101.1, 900_000),
        (101.1, 101.5, 100.9, 101.2, 900_000),
        (101.2, 101.6, 101.0, 101.3, 900_000),
        (101.3, 101.6, 101.0, 101.1, 900_000),
        (101.1, 101.3, 100.8, 100.9, 900_000),
        (100.9, 101.1, 100.7, 100.8, 900_000),
        (100.8, 101.4, 100.7, 101.0, 900_000),
        (101.0, 101.4, 100.8, 101.1, 900_000),
        (101.1, 101.5, 100.9, 101.2, 900_000),
        (101.2, 101.7, 101.0, 101.5, 1_200_000),
    ]

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None


def test_rejects_pullback_deeper_than_sixty_percent():
    rows = _valid_h2_rows()
    rows[10] = (104.3, 104.4, 101.7, 102.2, 980_000)
    rows[11] = (102.2, 102.5, 101.3, 101.6, 970_000)
    rows[12] = (101.6, 102.7, 101.4, 101.8, 960_000)
    rows[13] = (101.8, 102.7, 101.6, 101.9, 950_000)
    rows[14] = (101.9, 102.8, 101.8, 102.0, 940_000)
    rows[15] = (102.0, 105.3, 101.9, 105.2, 1_700_000)

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None


def test_rejects_strong_bear_pullback():
    rows = _valid_h2_rows()
    rows[10] = (104.8, 105.0, 102.5, 102.7, 980_000)

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None


def test_rejects_weak_h2_signal_bar():
    rows = _valid_h2_rows()
    rows[15] = (104.9, 105.3, 104.3, 105.0, 1_700_000)

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None


def test_rejects_h1_too_far_from_pullback():
    rows = _valid_h2_rows()
    extra: list[tuple[float, float, float, float, int]] = [
        (103.7, 104.1, 103.7, 104.0, 850_000),
        (103.8, 104.0, 103.8, 103.95, 840_000),
        (103.7, 103.9, 103.7, 103.85, 830_000),
        (103.6, 103.8, 103.6, 103.75, 820_000),
        (103.5, 103.7, 103.5, 103.65, 810_000),
        (103.5, 103.6, 103.5, 103.55, 800_000),
    ]
    rows = rows[:12] + extra + rows[12:]

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None


def test_rejects_h2_too_far_from_h1():
    rows = _valid_h2_rows()
    extra: list[tuple[float, float, float, float, int]] = [
        (104.5, 105.5, 104.3, 104.8, 900_000),
        (104.8, 105.4, 104.6, 104.9, 890_000),
        (104.9, 105.3, 104.7, 105.0, 880_000),
        (105.0, 105.3, 104.8, 105.1, 870_000),
        (105.1, 105.4, 104.9, 105.2, 860_000),
        (105.2, 105.5, 105.0, 105.3, 850_000),
        (105.3, 105.5, 105.1, 105.4, 840_000),
        (105.4, 105.5, 105.2, 105.3, 830_000),
        (105.3, 105.5, 105.1, 105.2, 820_000),
    ]
    rows = rows[:15] + extra + rows[15:]

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is None


def test_prefers_highest_confidence_h2_when_multiple_candidates_exist():
    rows = _valid_h2_rows() + [
        (105.2, 105.4, 104.8, 105.0, 1_000_000),
        (105.0, 105.2, 104.5, 104.7, 980_000),
        (104.7, 104.9, 104.3, 104.5, 970_000),
        (104.5, 105.5, 104.4, 104.8, 960_000),
        (104.8, 105.5, 104.6, 104.9, 950_000),
        (105.4, 106.3, 105.3, 106.2, 1_800_000),
    ]

    result = High2Detector().detect(_df(rows), "TEST")

    assert result is not None
    assert result.metadata["h2_idx"] == 15
    assert result.pivots["h2_high"] == 105.9
    assert result.pivot_dates["h2_high"] == date(2025, 1, 22)
