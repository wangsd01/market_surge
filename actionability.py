from __future__ import annotations

from dataclasses import dataclass

from patterns.base import PatternResult
from strategies import _entry_price, levels_for

PRE_BREAKOUT_MAX_BELOW_ENTRY_PCT = 0.10
POST_BREAKOUT_MAX_BELOW_ENTRY_PCT = 0.02
POST_BREAKOUT_MAX_ABOVE_ENTRY_PCT = 0.05

_PRE_BREAKOUT_STATES = {"active_pre_breakout", "handle_forming"}
_POST_BREAKOUT_STATES = {"confirmed", "complete"}


@dataclass(frozen=True)
class ActionabilityAssessment:
    is_actionable: bool
    reason: str
    entry: float | None = None
    stop: float | None = None


def assess_actionability(result: PatternResult, current_price: float) -> ActionabilityAssessment:
    try:
        breakout, stop = levels_for(result)
    except ValueError:
        return ActionabilityAssessment(False, "incomplete_geometry")

    entry = _entry_price(result.pattern, breakout)
    state = result.metadata.get("state")
    if _is_post_breakout_state(result, state):
        return _assess_post_breakout(entry=entry, stop=stop, current_price=current_price)
    return _assess_pre_breakout(entry=entry, stop=stop, current_price=current_price)


def _is_post_breakout_state(result: PatternResult, state: object) -> bool:
    if state in _POST_BREAKOUT_STATES:
        return True
    if state in _PRE_BREAKOUT_STATES:
        return False
    return "breakout" in result.pivots


def _assess_pre_breakout(*, entry: float, stop: float, current_price: float) -> ActionabilityAssessment:
    minimum_price = entry * (1.0 - PRE_BREAKOUT_MAX_BELOW_ENTRY_PCT)
    if current_price < minimum_price:
        return ActionabilityAssessment(False, "too_far_below_entry", entry=entry, stop=stop)
    if current_price > entry:
        return ActionabilityAssessment(False, "too_extended", entry=entry, stop=stop)
    return ActionabilityAssessment(True, "pre_breakout_buy", entry=entry, stop=stop)


def _assess_post_breakout(*, entry: float, stop: float, current_price: float) -> ActionabilityAssessment:
    if current_price < stop:
        return ActionabilityAssessment(False, "below_stop", entry=entry, stop=stop)

    minimum_price = entry * (1.0 - POST_BREAKOUT_MAX_BELOW_ENTRY_PCT)
    maximum_price = entry * (1.0 + POST_BREAKOUT_MAX_ABOVE_ENTRY_PCT)
    if current_price < minimum_price:
        return ActionabilityAssessment(False, "too_far_below_entry", entry=entry, stop=stop)
    if current_price > maximum_price:
        return ActionabilityAssessment(False, "too_extended", entry=entry, stop=stop)
    return ActionabilityAssessment(True, "post_breakout_pullback", entry=entry, stop=stop)
