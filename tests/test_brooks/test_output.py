import datetime

import pandas as pd

from brooks.config import BrooksConfig
from brooks.market_cycle import MarketCycleResult
from brooks.breakout import BreakoutEvent, FollowThroughResult
from brooks.h1h2 import TriggerEvent, H1H2State
from brooks.extension import ExtensionResult
from brooks.stops_targets import StopSet, TargetSet
from brooks.scoring import ScoreResult
from brooks.output import assemble_row, build_watchlist_buckets, ALL_OUTPUT_COLUMNS


def _minimal_kwargs(**overrides):
    trigger = TriggerEvent(
        signal_date=datetime.date(2025, 1, 8), trigger_date=datetime.date(2025, 1, 9), trigger_price=105.0,
        signal_bar_low=100.0, signal_bar_high=104.0, pullback_leg_low=99.0,
    )
    defaults = dict(
        ticker="TEST",
        date=datetime.date(2025, 1, 10),
        market_cycle=MarketCycleResult(current_cycle="BULL_TREND", prior_trend=None, trading_range_length=0, bear_relevance=1.0),
        breakout_event=BreakoutEvent(
            idx=5, date=datetime.date(2025, 1, 6), breakout_score=0.9, is_strong=True, is_extreme=False,
            breakout_level=95.0, gap_pct=0.03, true_gap_up=True, volume_ratio=1.8,
        ),
        follow_through=FollowThroughResult(follow_through_score=0.4, retracement_pct=0.2, gap_still_open=True),
        h1h2_state=H1H2State(
            h1=trigger, h2=None, h1_failed=False, h2_failed=False, h1_structural_failed=False,
            h2_structural_failed=False, days_since_h1_trigger=1, days_since_h2_trigger=None,
            forming=None, reset_from_failure=False, prior_failed_pattern=None,
        ),
        extension=ExtensionResult(False, None),
        stops=StopSet(
            signal_bar_stop=99.9, pullback_swing_stop=98.9, breakout_bar_stop=94.9,
            gap_failure_stop=94.9, tight_stop=99.9, structural_stop=98.9,
        ),
        targets=TargetSet(nearest_resistance=115.0, target_1=115.0, target_2=112.0, rr_target_1=2.5, rr_target_2=2.0),
        scores=ScoreResult(
            market_context=8.0, breakout_quality=9.0, follow_through=7.0, current_setup=7.0,
            reward_risk=8.0, liquidity=6.0, setup_quality_score=8.2, entry_quality_score=7.3, trade_score=7.8,
        ),
        setup_state="H1_TRIGGERED_RECENTLY",
        proposed_entry=105.0,
        dollar_vol=80_000_000,
    )
    defaults.update(overrides)
    return defaults


def test_assemble_row_has_all_documented_columns_and_key_values():
    row = assemble_row(**_minimal_kwargs())

    assert set(ALL_OUTPUT_COLUMNS) <= set(row.keys())
    assert row["ticker"] == "TEST"
    assert row["setup_state"] == "H1_TRIGGERED_RECENTLY"
    assert row["trade_score"] == 7.8
    assert row["structural_stop"] == 98.9
    assert row["rr_target_1"] == 2.5
    assert row["earnings_recent"] is None
    assert row["days_since_earnings"] is None
    assert isinstance(row["reason"], str) and len(row["reason"]) > 0
    assert isinstance(row["warning"], str)


def _bucket_row(setup_state, entry_quality_score=7.0, rr_target_1=2.0, trade_score=5.0):
    row = assemble_row(**_minimal_kwargs(setup_state=setup_state))
    row["entry_quality_score"] = entry_quality_score
    row["rr_target_1"] = rr_target_1
    row["trade_score"] = trade_score
    return row


def test_watchlist_buckets_partition_by_setup_state_and_gates():
    df = pd.DataFrame(
        [
            _bucket_row("H1_TRIGGERED_TODAY", entry_quality_score=6.0, rr_target_1=2.0, trade_score=8.0),
            _bucket_row("H1_TRIGGERED_TODAY", entry_quality_score=3.0, rr_target_1=2.0, trade_score=8.0),  # gated out: low entry_quality
            _bucket_row("H1_TRIGGERED_TODAY", entry_quality_score=6.0, rr_target_1=0.5, trade_score=8.0),  # gated out: low RR
            _bucket_row("WAIT_FIRST_PULLBACK", trade_score=4.0),
            _bucket_row("H1_FORMING", trade_score=3.0),
            _bucket_row("H2_FORMING", trade_score=6.0),
            _bucket_row("EXTENDED_AFTER_H2", trade_score=9.0),
            _bucket_row("FAILED_H1", trade_score=1.0),
        ]
    )

    buckets = build_watchlist_buckets(df)

    assert len(buckets["READY_NOW"]) == 1
    assert buckets["READY_NOW"].iloc[0]["entry_quality_score"] == 6.0
    assert len(buckets["WAIT_PULLBACK"]) == 1
    assert len(buckets["H1_WATCH"]) == 1
    assert len(buckets["H2_WATCH"]) == 1
    assert len(buckets["EXTENDED_DO_NOT_CHASE"]) == 1
    assert len(buckets["FAILED_SETUP"]) == 1
