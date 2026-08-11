import pandas as pd

from brooks.breakout import BreakoutEvent
from brooks.config import BrooksConfig
from brooks.h1h2 import scan_from_anchor, compute_h1h2_state, find_anchor


def _ohlcv(rows: list[dict]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=dates)[["Open", "High", "Low", "Close", "Volume"]]


def _df_from_highs_lows(highs: list[float], lows: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(highs), freq="B")
    opens = lows  # irrelevant to the state machine, which only reads High/Low
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": [1_000_000] * len(highs)},
        index=dates,
    )


def test_worked_example_h1_then_h2_not_h1_continuation():
    # Day:      A    B    C    D    E    F    G
    # High:   100   97   95   96   98   96   97
    # Low:     95   92   90   91   93   91   92
    #
    # C is the H1 signal bar (last bar of the pullback); D triggers H1 by
    # exceeding C's high. E makes a new high vs D -- continuation, NOT a new
    # trigger (no intervening pullback). F pulls back below E; G triggers H2
    # by exceeding F's high.
    highs = [100, 97, 95, 96, 98, 96, 97]
    lows = [95, 92, 90, 91, 93, 91, 92]
    df = _df_from_highs_lows(highs, lows)
    config = BrooksConfig()

    state = scan_from_anchor(df, anchor_idx=0, config=config)

    assert state.h1 is not None
    assert state.h1.signal_date == df.index[2].date()  # C
    assert state.h1.trigger_date == df.index[3].date()  # D
    assert state.h1.trigger_price == df["High"].iloc[2] * (1 + config.signal_bar_break_buffer_pct)

    assert state.h2 is not None
    assert state.h2.signal_date == df.index[5].date()  # F
    assert state.h2.trigger_date == df.index[6].date()  # G


def test_h2_fails_then_fresh_h1_forms_after_reset():
    # A-G reproduce the worked example (H1 at C->D, H2 at F->G). H is a hard
    # bear reversal below H2's pullback low (F=91) -- a "very strong failure"
    # (bear close below the pullback structure). I-J-K then form a genuinely
    # fresh pullback-and-trigger sequence that the original mechanical scan
    # can never see, because it already stopped (`break`) the instant H2
    # triggered at G -- this is exactly why the reset step exists.
    rows = [
        {"Open": 99, "High": 100, "Low": 95, "Close": 99.5, "Volume": 1_000_000},  # A
        {"Open": 99.5, "High": 97, "Low": 92, "Close": 93, "Volume": 1_000_000},  # B
        {"Open": 93, "High": 95, "Low": 90, "Close": 91, "Volume": 1_000_000},  # C (H1 signal)
        {"Open": 91, "High": 96, "Low": 91, "Close": 95.5, "Volume": 1_000_000},  # D (H1 trigger)
        {"Open": 95.5, "High": 98, "Low": 93, "Close": 97.5, "Volume": 1_000_000},  # E (continuation, not H2)
        {"Open": 97.5, "High": 96, "Low": 91, "Close": 92, "Volume": 1_000_000},  # F (H2 signal)
        {"Open": 92, "High": 97, "Low": 92, "Close": 96.5, "Volume": 1_000_000},  # G (H2 trigger)
        {"Open": 93, "High": 93, "Low": 85, "Close": 86, "Volume": 2_000_000},  # H (H2 fails: bear close < 91)
        {"Open": 88, "High": 88, "Low": 83, "Close": 84, "Volume": 1_000_000},  # I (fresh pullback start)
        {"Open": 84, "High": 86, "Low": 82, "Close": 85.5, "Volume": 1_000_000},  # J (fresh signal bar)
        {"Open": 85.5, "High": 89, "Low": 84, "Close": 88.5, "Volume": 1_000_000},  # K (fresh H1 trigger)
    ]
    df = _ohlcv(rows)
    config = BrooksConfig()

    raw = scan_from_anchor(df, anchor_idx=0, config=config)
    assert raw.h2 is not None
    assert raw.h2_failed is True
    assert raw.h2_structural_failed is True

    state = compute_h1h2_state(df, breakout_event=None, config=config)
    assert state is not None
    assert state.reset_from_failure is True
    assert state.prior_failed_pattern == "h2"
    assert state.h1 is not None
    assert state.h1.signal_date == df.index[9].date()  # J
    assert state.h1.trigger_date == df.index[10].date()  # K
    assert state.h2 is None


def test_forming_h1_when_pullback_active_with_no_trigger_yet():
    # A-B-C only: pullback (B, C) has started after the anchor (A) but neither
    # bar has yet exceeded the immediately preceding bar's high.
    highs = [100, 97, 95]
    lows = [95, 92, 90]
    df = _df_from_highs_lows(highs, lows)
    config = BrooksConfig()

    state = scan_from_anchor(df, anchor_idx=0, config=config)

    assert state.h1 is None
    assert state.h2 is None
    assert state.forming == "h1"


def test_find_anchor_prefers_high_since_breakout_when_recent():
    highs = [90, 95, 100, 98, 103, 101]
    lows = [85, 90, 95, 93, 98, 96]
    df = _df_from_highs_lows(highs, lows)
    config = BrooksConfig()
    breakout_event = BreakoutEvent(
        idx=2, date=df.index[2].date(), breakout_score=0.9, is_strong=True, is_extreme=False,
        breakout_level=95.0, low=94.0, prior_high=93.5, gap_pct=0.0, true_gap_up=False, volume_ratio=1.0,
    )

    anchor_idx = find_anchor(df, breakout_event, config)

    # highest High from idx 2 onward is idx 4 (103), not the breakout bar itself.
    assert anchor_idx == 4


def test_find_anchor_falls_back_to_lookback_window_start_without_breakout():
    highs = [90, 95, 100, 98, 103, 101]
    lows = [85, 90, 95, 93, 98, 96]
    df = _df_from_highs_lows(highs, lows)
    config = BrooksConfig()

    anchor_idx = find_anchor(df, breakout_event=None, config=config)

    # Not the highest High (idx 4) or lowest Low (idx 0, which happens to
    # coincide here) picked by argmax/argmin -- the start of the lookback
    # window, which scan_from_anchor can always walk forward from safely.
    assert anchor_idx == 0
