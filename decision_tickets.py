from __future__ import annotations

from dataclasses import dataclass
from math import floor

import pandas as pd

SCREEN_STRENGTH_WEIGHT = 0.25
PATTERN_CONFIDENCE_WEIGHT = 0.30
REWARD_TO_RISK_WEIGHT = 0.25
LIQUIDITY_WEIGHT = 0.10
TRIGGER_QUALITY_WEIGHT = 0.10
TRIGGER_EXTENSION_LIMIT_PCT = 0.02
TRIGGER_BELOW_DECAY_PCT = 0.10
MAX_REWARD_TO_RISK = 3.0
MAX_TICKETS = 10
DEFAULT_MAX_LOSS_PCT = 0.11


@dataclass(frozen=True)
class DecisionCandidate:
    ticker: str
    pattern: str
    screen_strength: float
    pattern_confidence: float
    entry: float
    stop: float
    target: float
    current_price: float
    dollar_volume: float
    summary_reason: str
    invalidation_rule: str


@dataclass(frozen=True)
class ScoredDecisionCandidate:
    ticker: str
    pattern: str
    screen_strength: float
    pattern_confidence: float
    entry: float
    stop: float
    target: float
    current_price: float
    dollar_volume: float
    summary_reason: str
    invalidation_rule: str
    risk_per_share: float
    reward_to_risk: float
    liquidity_score: float
    trigger_quality: float
    score: float


@dataclass(frozen=True)
class DecisionTicket:
    rank: int
    ticker: str
    pattern: str
    entry: float
    stop: float
    target: float
    risk_per_share: float
    shares: int
    position_value: float
    score: float
    summary_reason: str
    invalidation_rule: str
    sizing_basis: dict[str, float | None]

    @property
    def risk_loss_pct(self) -> float:
        if self.entry <= 0:
            return 0.0
        return (self.risk_per_share / self.entry) * 100.0

    @property
    def target_gain_pct(self) -> float:
        if self.entry <= 0:
            return 0.0
        return ((self.target - self.entry) / self.entry) * 100.0

    @property
    def risk_value(self) -> float:
        return self.shares * self.risk_per_share


def ticket_to_dict(ticket: DecisionTicket) -> dict[str, object]:
    return {
        "rank": ticket.rank,
        "ticker": ticket.ticker,
        "pattern": ticket.pattern,
        "entry": ticket.entry,
        "stop": ticket.stop,
        "target": ticket.target,
        "risk_per_share": ticket.risk_per_share,
        "shares": ticket.shares,
        "position_value": ticket.position_value,
        "score": ticket.score,
        "summary_reason": ticket.summary_reason,
        "invalidation_rule": ticket.invalidation_rule,
        "sizing_basis": ticket.sizing_basis,
    }


def score_candidates(candidates: list[DecisionCandidate]) -> list[ScoredDecisionCandidate]:
    if not candidates:
        return []

    liquidity_scores = _liquidity_scores(candidates)
    scored: list[ScoredDecisionCandidate] = []
    for candidate in candidates:
        risk_per_share = candidate.entry - candidate.stop
        reward_to_risk = _reward_to_risk(candidate)
        trigger_quality = _trigger_quality(candidate.current_price, candidate.entry)
        liquidity_score = liquidity_scores[candidate.ticker, candidate.pattern]
        score = (
            SCREEN_STRENGTH_WEIGHT * candidate.screen_strength
            + PATTERN_CONFIDENCE_WEIGHT * candidate.pattern_confidence
            + REWARD_TO_RISK_WEIGHT * min(reward_to_risk, MAX_REWARD_TO_RISK) / MAX_REWARD_TO_RISK
            + LIQUIDITY_WEIGHT * liquidity_score
            + TRIGGER_QUALITY_WEIGHT * trigger_quality
        )
        scored.append(
            ScoredDecisionCandidate(
                ticker=candidate.ticker,
                pattern=candidate.pattern,
                screen_strength=candidate.screen_strength,
                pattern_confidence=candidate.pattern_confidence,
                entry=candidate.entry,
                stop=candidate.stop,
                target=candidate.target,
                current_price=candidate.current_price,
                dollar_volume=candidate.dollar_volume,
                summary_reason=candidate.summary_reason,
                invalidation_rule=candidate.invalidation_rule,
                risk_per_share=risk_per_share,
                reward_to_risk=reward_to_risk,
                liquidity_score=liquidity_score,
                trigger_quality=trigger_quality,
                score=score,
            )
        )
    return scored


def rank_candidates(candidates: list[DecisionCandidate]) -> list[ScoredDecisionCandidate]:
    scored = score_candidates(candidates)
    return sorted(
        scored,
        key=lambda item: (
            -item.score,
            -item.pattern_confidence,
            -item.reward_to_risk,
            -item.liquidity_score,
            item.ticker,
            item.pattern,
        ),
    )


def build_decision_tickets(
    candidates: list[DecisionCandidate],
    *,
    account_size: float,
    risk_pct: float,
    max_loss_pct: float | None = DEFAULT_MAX_LOSS_PCT,
    max_position_dollars: float | None = None,
    top_n: int = MAX_TICKETS,
) -> list[DecisionTicket]:
    _validate_sizing_inputs(
        account_size=account_size,
        risk_pct=risk_pct,
        max_loss_pct=max_loss_pct,
        max_position_dollars=max_position_dollars,
    )

    ranked = rank_candidates(candidates)
    best_by_ticker: dict[str, ScoredDecisionCandidate] = {}
    for candidate in ranked:
        if candidate.risk_per_share <= 0:
            continue
        if max_loss_pct is not None and (candidate.risk_per_share / candidate.entry) > max_loss_pct:
            continue
        if candidate.ticker not in best_by_ticker:
            best_by_ticker[candidate.ticker] = candidate

    consolidated = sorted(
        best_by_ticker.values(),
        key=lambda item: (
            -item.score,
            -item.pattern_confidence,
            -item.reward_to_risk,
            -item.liquidity_score,
            item.ticker,
            item.pattern,
        ),
    )

    risk_dollars = account_size * risk_pct
    tickets: list[DecisionTicket] = []
    for candidate in consolidated:
        raw_shares = floor(risk_dollars / candidate.risk_per_share)
        final_shares = raw_shares
        if max_position_dollars is not None:
            capped_shares = floor(max_position_dollars / candidate.entry)
            final_shares = min(final_shares, capped_shares)
        if final_shares < 1:
            continue
        position_value = final_shares * candidate.entry
        tickets.append(
            DecisionTicket(
                rank=len(tickets) + 1,
                ticker=candidate.ticker,
                pattern=candidate.pattern,
                entry=candidate.entry,
                stop=candidate.stop,
                target=candidate.target,
                risk_per_share=candidate.risk_per_share,
                shares=final_shares,
                position_value=position_value,
                score=candidate.score,
                summary_reason=candidate.summary_reason,
                invalidation_rule=candidate.invalidation_rule,
                sizing_basis={
                    "account_size": account_size,
                    "risk_pct": risk_pct,
                    "risk_dollars": risk_dollars,
                    "max_position_dollars": max_position_dollars,
                },
            )
        )
        if len(tickets) == top_n:
            break
    return tickets


def _validate_sizing_inputs(
    *,
    account_size: float,
    risk_pct: float,
    max_loss_pct: float | None,
    max_position_dollars: float | None,
) -> None:
    if account_size <= 0:
        raise ValueError("account_size must be > 0")
    if risk_pct <= 0:
        raise ValueError("risk_pct must be > 0")
    if max_loss_pct is not None and max_loss_pct <= 0:
        raise ValueError("max_loss_pct must be > 0")
    if max_position_dollars is not None and max_position_dollars <= 0:
        raise ValueError("max_position_dollars must be > 0")


def _reward_to_risk(candidate: DecisionCandidate) -> float:
    risk_per_share = candidate.entry - candidate.stop
    if risk_per_share <= 0:
        return 0.0
    return (candidate.target - candidate.entry) / risk_per_share


def _trigger_quality(current_price: float, entry: float) -> float:
    if entry <= 0:
        return 0.0
    if current_price <= entry:
        below_pct = (entry - current_price) / entry
        return max(0.0, 1.0 - (below_pct / TRIGGER_BELOW_DECAY_PCT))
    extension_pct = (current_price - entry) / entry
    if extension_pct >= TRIGGER_EXTENSION_LIMIT_PCT:
        return 0.0
    return max(0.0, 1.0 - (extension_pct / TRIGGER_EXTENSION_LIMIT_PCT))


def _liquidity_scores(candidates: list[DecisionCandidate]) -> dict[tuple[str, str], float]:
    volumes = pd.Series([candidate.dollar_volume for candidate in candidates], dtype=float)
    if len(candidates) == 1:
        return {(candidates[0].ticker, candidates[0].pattern): 1.0}

    ranks = volumes.rank(method="average", ascending=True)
    normalized = (ranks - 1) / (len(candidates) - 1)
    scores: dict[tuple[str, str], float] = {}
    for candidate, score in zip(candidates, normalized.tolist(), strict=True):
        scores[(candidate.ticker, candidate.pattern)] = float(score)
    return scores
