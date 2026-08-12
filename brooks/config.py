from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BrooksConfig:
    lookback_bdays: int = 252
    min_bars_required: int = 60

    # features.py
    atr_period: int = 14
    vol_avg_period: int = 20
    ema_short: int = 20
    ema_long: int = 50
    slope_window_short: int = 20
    slope_window_long: int = 50

    # market_cycle.py
    swing_order: int = 3
    min_swing_pct: float = 0.02
    cycle_window: int = 40
    tr_length_probe_window: int = 15
    strong_trend_bar_ratio: float = 0.65
    trend_bar_ratio: float = 0.55
    bar_overlap_ratio_threshold: float = 0.50
    trading_range_overlap_threshold: float = 0.55
    max_range_channel_width_pct: float = 0.25
    reversal_lookback_bars: int = 5
    short_tr_bdays: int = 10
    mature_tr_bdays: int = 25
    mature_tr_bear_relevance_floor: float = 0.2

    # breakout.py
    strong_body_ratio: float = 0.6
    strong_close_location: float = 0.75
    strong_range_atr_ratio: float = 1.2
    extreme_range_atr_ratio: float = 1.8
    extreme_close_location: float = 0.8
    breakout_vol_ratio: float = 1.5
    breakout_search_bars: int = 60
    breakout_score_min_threshold: float = 0.5
    follow_through_bars: int = 3
    shallow_retracement_max: float = 0.35
    moderate_retracement_max: float = 0.60

    # h1h2.py
    anchor_max_age_bdays: int = 15
    anchor_lookback_bars: int = 60
    pullback_max_bars: int = 8
    max_state_resets: int = 1

    # state.py
    h1_stale_bdays: int = 3
    h2_stale_bdays: int = 4
    breakout_pullback_max_age_bdays: int = 5

    # extension.py
    extended_consec_bull_bars: int = 3
    extended_atr_multiple: float = 3.0
    extended_ema20_distance_pct: float = 0.12

    # tick buffer (h1h2.py entries, stops_targets.py stops, brooks_screener.py
    # Buy The Close entries) -- Brooks defines a tick literally (one cent for
    # most US stocks, per SEC Rule 612), never as a percentage of price. Use a
    # flat one-cent floor, scaling up for higher-priced names where a literal
    # penny would be negligible relative to normal volatility. See
    # tick_buffer() below.
    min_tick_buffer: float = 0.01
    tick_buffer_pct: float = 0.0005

    # scoring.py
    min_plausible_rr: float = 1.0
    min_entry_quality_for_ready_now: float = 5.0
    weight_market_context: float = 0.25
    weight_breakout_quality: float = 0.20
    weight_follow_through: float = 0.15
    weight_current_setup: float = 0.15
    weight_reward_risk: float = 0.15
    weight_liquidity: float = 0.10
    min_dollar_vol_for_full_liquidity: float = 50_000_000


def tick_buffer(price: float, config: BrooksConfig) -> float:
    """A "one tick above/below" buffer, per Brooks' literal per-instrument
    tick definition rather than a pure percentage of price. Callers add this
    for a buy-stop entry, subtract it for a stop below a reference low."""
    return max(config.min_tick_buffer, price * config.tick_buffer_pct)
