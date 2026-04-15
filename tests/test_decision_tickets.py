from __future__ import annotations

import pytest

from decision_tickets import DecisionCandidate, build_decision_tickets, rank_candidates, score_candidates


def _candidate(
    *,
    ticker: str,
    pattern: str = "cup_handle",
    screen_strength: float = 0.8,
    pattern_confidence: float = 0.7,
    entry: float = 10.0,
    stop: float = 9.0,
    target: float = 12.0,
    current_price: float = 10.0,
    dollar_volume: float = 100_000_000.0,
    summary_reason: str = "clean setup",
    invalidation_rule: str = "invalid if price trades below stop",
) -> DecisionCandidate:
    return DecisionCandidate(
        ticker=ticker,
        pattern=pattern,
        screen_strength=screen_strength,
        pattern_confidence=pattern_confidence,
        entry=entry,
        stop=stop,
        target=target,
        current_price=current_price,
        dollar_volume=dollar_volume,
        summary_reason=summary_reason,
        invalidation_rule=invalidation_rule,
    )


def test_score_candidates_uses_fixed_v1_weights():
    low_liquidity = _candidate(ticker="LOW", dollar_volume=50_000_000.0)
    high_liquidity = _candidate(ticker="HIGH", dollar_volume=100_000_000.0)

    scored = score_candidates([low_liquidity, high_liquidity])
    by_ticker = {item.ticker: item for item in scored}

    assert by_ticker["HIGH"].score == pytest.approx(0.7766666667)


def test_rank_candidates_uses_pattern_confidence_before_other_ties():
    higher_conf = _candidate(
        ticker="AAA",
        screen_strength=0.0,
        pattern_confidence=0.8,
        entry=10.0,
        stop=9.0,
        target=10.0,
        dollar_volume=100_000_000.0,
    )
    lower_conf = _candidate(
        ticker="BBB",
        screen_strength=0.36,
        pattern_confidence=0.5,
        entry=10.0,
        stop=9.0,
        target=10.0,
        dollar_volume=100_000_000.0,
    )

    ranked = rank_candidates([lower_conf, higher_conf])

    assert [item.ticker for item in ranked] == ["AAA", "BBB"]


def test_rank_candidates_uses_reward_to_risk_then_liquidity_then_ticker():
    higher_rr = _candidate(
        ticker="AAA",
        screen_strength=0.0,
        pattern_confidence=0.7,
        entry=10.0,
        stop=9.0,
        target=12.0,
        dollar_volume=80_000_000.0,
    )
    lower_rr = _candidate(
        ticker="BBB",
        screen_strength=1.0 / 3.0,
        pattern_confidence=0.7,
        entry=10.0,
        stop=9.0,
        target=11.0,
        dollar_volume=80_000_000.0,
    )
    alphabetic = _candidate(
        ticker="CCC",
        screen_strength=0.8,
        pattern_confidence=0.7,
        entry=10.0,
        stop=9.0,
        target=12.0,
        dollar_volume=60_000_000.0,
    )
    alphabetic_2 = _candidate(
        ticker="DDD",
        screen_strength=0.8,
        pattern_confidence=0.7,
        entry=10.0,
        stop=9.0,
        target=12.0,
        dollar_volume=60_000_000.0,
    )

    ranked = rank_candidates([alphabetic_2, alphabetic, lower_rr, higher_rr])

    assert [item.ticker for item in ranked] == ["CCC", "DDD", "AAA", "BBB"]


def test_build_decision_tickets_keeps_only_highest_scoring_ticket_per_ticker():
    candidates = [
        _candidate(ticker="AAA", pattern="cup_handle", screen_strength=0.8),
        _candidate(ticker="AAA", pattern="channel", screen_strength=0.2),
        _candidate(ticker="BBB", pattern="double_bottom", screen_strength=0.7),
    ]

    tickets = build_decision_tickets(
        candidates,
        account_size=10_000.0,
        risk_pct=0.01,
        max_loss_pct=None,
    )

    assert [ticket.ticker for ticket in tickets] == ["AAA", "BBB"]
    assert tickets[0].pattern == "cup_handle"


def test_build_decision_tickets_applies_fixed_risk_sizing_and_position_cap():
    tickets = build_decision_tickets(
        [
            _candidate(
                ticker="AAA",
                entry=10.0,
                stop=8.0,
                target=14.0,
            )
        ],
        account_size=10_000.0,
        risk_pct=0.01,
        max_loss_pct=None,
        max_position_dollars=400.0,
    )

    assert len(tickets) == 1
    assert tickets[0].risk_per_share == 2.0
    assert tickets[0].shares == 40
    assert tickets[0].position_value == 400.0
    assert tickets[0].sizing_basis["risk_dollars"] == 100.0


def test_build_decision_tickets_rejects_invalid_risk_and_returns_top_ten_by_default():
    candidates = [
        _candidate(ticker="AAA", entry=10.0, stop=10.0, target=12.0),
        _candidate(ticker="BBB", screen_strength=0.9),
        _candidate(ticker="CCC", screen_strength=0.8),
        _candidate(ticker="DDD", screen_strength=0.7),
        _candidate(ticker="EEE", screen_strength=0.6),
    ]

    tickets = build_decision_tickets(
        candidates,
        account_size=10_000.0,
        risk_pct=0.01,
        max_loss_pct=None,
    )

    assert [ticket.ticker for ticket in tickets] == ["BBB", "CCC", "DDD", "EEE"]
    assert len(tickets) == 4


def test_build_decision_tickets_filters_candidates_above_max_loss_pct():
    candidates = [
        _candidate(ticker="SAFE", entry=10.0, stop=9.3, target=11.4),
        _candidate(ticker="WIDE", entry=10.0, stop=9.1, target=11.8),
    ]

    tickets = build_decision_tickets(
        candidates,
        account_size=10_000.0,
        risk_pct=0.01,
        max_loss_pct=0.08,
    )

    assert [ticket.ticker for ticket in tickets] == ["SAFE"]


def test_build_decision_tickets_allows_disabling_max_loss_filter():
    candidates = [
        _candidate(ticker="SAFE", entry=10.0, stop=9.3, target=11.4),
        _candidate(ticker="WIDE", entry=10.0, stop=9.1, target=11.8),
    ]

    tickets = build_decision_tickets(
        candidates,
        account_size=10_000.0,
        risk_pct=0.01,
        max_loss_pct=None,
    )

    assert [ticket.ticker for ticket in tickets] == ["SAFE", "WIDE"]


def test_build_decision_tickets_validates_sizing_inputs():
    candidate = _candidate(ticker="AAA")

    with pytest.raises(ValueError, match="account_size"):
        build_decision_tickets([candidate], account_size=0.0, risk_pct=0.01)

    with pytest.raises(ValueError, match="risk_pct"):
        build_decision_tickets([candidate], account_size=10_000.0, risk_pct=0.0)

    with pytest.raises(ValueError, match="max_position_dollars"):
        build_decision_tickets(
            [candidate],
            account_size=10_000.0,
            risk_pct=0.01,
            max_position_dollars=0.0,
        )

    with pytest.raises(ValueError, match="max_loss_pct"):
        build_decision_tickets(
            [candidate],
            account_size=10_000.0,
            risk_pct=0.01,
            max_loss_pct=0.0,
        )
