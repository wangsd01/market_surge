from __future__ import annotations

from dataclasses import dataclass

from brooks.breakout import BreakoutEvent, FollowThroughResult
from brooks.config import BrooksConfig
from brooks.extension import ExtensionResult
from brooks.h1h2 import H1H2State
from brooks.market_cycle import MarketCycleResult
from brooks.stops_targets import TargetSet

_CYCLE_MARKET_CONTEXT_POINTS = {
    "STRONG_BULL_TREND": 10.0,
    "BULL_TREND": 8.0,
    "BULLISH_TRADING_RANGE": 6.0,
    "TRADING_RANGE": 5.0,
    "POSSIBLE_MAJOR_TREND_REVERSAL": 5.0,
    "BEARISH_TRADING_RANGE": 3.0,
    "BEAR_TREND": 2.0,
    "STRONG_BEAR_TREND": 0.0,
}

# Starter set of the penalty/bonus rules from spec sections 13-14. Each rule
# is (name, component, condition_fn, points). Extending this list is the
# intended way to add more of the spec's ~28 named conditions later.
_PENALTY_BONUS_RULES: list[tuple[str, str, object, float]] = [
    (
        "weak_breakout_close",
        "breakout_quality",
        lambda ctx: ctx["breakout_event"] is not None and not ctx["breakout_event"].is_strong,
        -1.0,
    ),
    (
        "true_gap_bonus",
        "breakout_quality",
        lambda ctx: ctx["breakout_event"] is not None and ctx["breakout_event"].true_gap_up,
        0.5,
    ),
    (
        "volume_expansion_bonus",
        "liquidity",
        lambda ctx: ctx["breakout_event"] is not None and ctx["breakout_event"].volume_ratio > 1.5,
        0.5,
    ),
    (
        "complete_retracement_penalty",
        "follow_through",
        lambda ctx: ctx["follow_through"] is not None and ctx["follow_through"].retracement_pct >= 1.0,
        -2.0,
    ),
    (
        "shallow_pullback_bonus",
        "current_setup",
        lambda ctx: ctx["follow_through"] is not None and ctx["follow_through"].retracement_pct <= ctx["config"].shallow_retracement_max,
        0.5,
    ),
    (
        "low_rr_penalty",
        "reward_risk",
        lambda ctx: ctx["targets"] is not None and ctx["targets"].rr_target_1 < ctx["config"].min_plausible_rr,
        -1.0,
    ),
]


@dataclass
class ScoreResult:
    market_context: float
    breakout_quality: float
    follow_through: float
    current_setup: float
    reward_risk: float
    liquidity: float
    setup_quality_score: float
    entry_quality_score: float
    trade_score: float


def _clip10(value: float) -> float:
    return max(0.0, min(10.0, value))


def _market_context_score(market_cycle: MarketCycleResult) -> float:
    base = _CYCLE_MARKET_CONTEXT_POINTS.get(market_cycle.current_cycle, 5.0)
    if market_cycle.prior_trend in {"BEAR_TREND", "STRONG_BEAR_TREND"}:
        base *= market_cycle.bear_relevance
    return _clip10(base)


def _breakout_quality_score(breakout_event: BreakoutEvent | None) -> float:
    if breakout_event is None:
        return 0.0
    return _clip10(breakout_event.breakout_score * 10.0)


def _follow_through_score(follow_through: FollowThroughResult | None) -> float:
    if follow_through is None or follow_through.follow_through_score is None:
        return 5.0
    return _clip10((follow_through.follow_through_score + 1.0) / 2.0 * 10.0)


def _current_setup_score(h1h2_state: H1H2State | None, extension: ExtensionResult) -> float:
    if extension.is_extended:
        return 2.0
    if h1h2_state is None:
        return 4.0
    if h1h2_state.h2_failed or h1h2_state.h1_failed:
        return 1.0
    if h1h2_state.h2 is not None:
        return 9.0
    if h1h2_state.h1 is not None:
        return 7.0
    if h1h2_state.forming is not None:
        return 6.0
    return 4.0


def _reward_risk_score(targets: TargetSet, config: BrooksConfig) -> float:
    score = _clip10(targets.rr_target_1 * 5.0)
    if targets.rr_target_1 < config.min_plausible_rr:
        score = min(score, 1.0)
    return score


def _liquidity_score(dollar_vol: float, config: BrooksConfig) -> float:
    if config.min_dollar_vol_for_full_liquidity <= 0:
        return 10.0
    return _clip10(dollar_vol / config.min_dollar_vol_for_full_liquidity * 10.0)


def _apply_penalty_bonus_rules(components: dict[str, float], ctx: dict) -> dict[str, float]:
    out = dict(components)
    for _, component, condition, points in _PENALTY_BONUS_RULES:
        if condition(ctx):
            out[component] = _clip10(out[component] + points)
    return out


def compute_scores(
    *,
    market_cycle: MarketCycleResult,
    breakout_event: BreakoutEvent | None,
    follow_through: FollowThroughResult | None,
    h1h2_state: H1H2State | None,
    extension: ExtensionResult,
    targets: TargetSet,
    dollar_vol: float,
    config: BrooksConfig,
) -> ScoreResult:
    components = {
        "market_context": _market_context_score(market_cycle),
        "breakout_quality": _breakout_quality_score(breakout_event),
        "follow_through": _follow_through_score(follow_through),
        "current_setup": _current_setup_score(h1h2_state, extension),
        "reward_risk": _reward_risk_score(targets, config),
        "liquidity": _liquidity_score(dollar_vol, config),
    }
    ctx = {
        "breakout_event": breakout_event,
        "follow_through": follow_through,
        "h1h2_state": h1h2_state,
        "targets": targets,
        "config": config,
    }
    components = _apply_penalty_bonus_rules(components, ctx)

    setup_weight_sum = 0.25 + 0.20 + 0.15
    setup_quality_score = _clip10(
        (components["market_context"] * 0.25 + components["breakout_quality"] * 0.20 + components["follow_through"] * 0.15)
        / setup_weight_sum
    )

    entry_weight_sum = 0.15 + 0.15 + 0.10
    entry_quality_score = _clip10(
        (components["current_setup"] * 0.15 + components["reward_risk"] * 0.15 + components["liquidity"] * 0.10)
        / entry_weight_sum
    )

    trade_score = _clip10(
        components["market_context"] * config.weight_market_context
        + components["breakout_quality"] * config.weight_breakout_quality
        + components["follow_through"] * config.weight_follow_through
        + components["current_setup"] * config.weight_current_setup
        + components["reward_risk"] * config.weight_reward_risk
        + components["liquidity"] * config.weight_liquidity
    )

    return ScoreResult(
        market_context=components["market_context"],
        breakout_quality=components["breakout_quality"],
        follow_through=components["follow_through"],
        current_setup=components["current_setup"],
        reward_risk=components["reward_risk"],
        liquidity=components["liquidity"],
        setup_quality_score=setup_quality_score,
        entry_quality_score=entry_quality_score,
        trade_score=trade_score,
    )
