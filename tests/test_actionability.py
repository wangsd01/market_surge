from __future__ import annotations

from datetime import date

from patterns.base import PatternResult

from actionability import assess_actionability


def _result(
    *,
    state: str,
    pivots: dict[str, float],
    pivot_dates: dict[str, date] | None = None,
) -> PatternResult:
    return PatternResult(
        pattern="cup_handle",
        ticker="TEST",
        confidence=1.0,
        detected_on=date(2025, 4, 14),
        pivots=pivots,
        pivot_dates=pivot_dates or {name: date(2025, 4, 1) for name in pivots},
        metadata={"state": state},
    )


def test_assess_actionability_returns_incomplete_geometry_for_missing_handle_pivots():
    result = _result(
        state="cup_forming",
        pivots={"left_high": 100.0, "cup_low": 75.0},
    )

    assessment = assess_actionability(result, current_price=90.0)

    assert assessment.is_actionable is False
    assert assessment.reason == "incomplete_geometry"


def test_assess_actionability_accepts_pre_breakout_setup_within_ten_percent_below_entry():
    result = _result(
        state="handle_forming",
        pivots={
            "left_high": 100.0,
            "cup_low": 75.0,
            "handle_high": 100.0,
            "handle_low": 95.0,
        },
    )

    assessment = assess_actionability(result, current_price=92.10)

    assert assessment.is_actionable is True
    assert assessment.reason == "pre_breakout_buy"


def test_assess_actionability_rejects_pre_breakout_setup_more_than_ten_percent_below_entry():
    result = _result(
        state="handle_forming",
        pivots={
            "left_high": 100.0,
            "cup_low": 75.0,
            "handle_high": 100.0,
            "handle_low": 95.0,
        },
    )

    assessment = assess_actionability(result, current_price=89.00)

    assert assessment.is_actionable is False
    assert assessment.reason == "too_far_below_entry"


def test_assess_actionability_accepts_confirmed_pullback_inside_buy_zone():
    result = _result(
        state="confirmed",
        pivots={
            "left_high": 100.0,
            "cup_low": 75.0,
            "handle_high": 100.0,
            "handle_low": 95.0,
            "breakout": 101.0,
        },
    )

    assessment = assess_actionability(result, current_price=103.10)

    assert assessment.is_actionable is True
    assert assessment.reason == "post_breakout_pullback"


def test_assess_actionability_rejects_confirmed_setup_above_five_percent_buy_zone():
    result = _result(
        state="confirmed",
        pivots={
            "left_high": 100.0,
            "cup_low": 75.0,
            "handle_high": 100.0,
            "handle_low": 95.0,
            "breakout": 101.0,
        },
    )

    assessment = assess_actionability(result, current_price=106.20)

    assert assessment.is_actionable is False
    assert assessment.reason == "too_extended"


def test_assess_actionability_rejects_confirmed_setup_more_than_two_percent_below_entry():
    result = _result(
        state="confirmed",
        pivots={
            "left_high": 100.0,
            "cup_low": 75.0,
            "handle_high": 100.0,
            "handle_low": 95.0,
            "breakout": 101.0,
        },
    )

    assessment = assess_actionability(result, current_price=97.00)

    assert assessment.is_actionable is False
    assert assessment.reason == "too_far_below_entry"


def test_assess_actionability_rejects_confirmed_setup_below_stop():
    result = _result(
        state="confirmed",
        pivots={
            "left_high": 100.0,
            "cup_low": 75.0,
            "handle_high": 100.0,
            "handle_low": 95.0,
            "breakout": 101.0,
        },
    )

    assessment = assess_actionability(result, current_price=94.00)

    assert assessment.is_actionable is False
    assert assessment.reason == "below_stop"
