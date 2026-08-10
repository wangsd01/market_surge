from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from brooks.breakout import BreakoutEvent, strong_bull_bar
from brooks.config import BrooksConfig
from brooks.h1h2 import H1H2State


@dataclass
class ExtensionResult:
    is_extended: bool
    reason: str | None


def _reference(h1h2_state: H1H2State | None, breakout_event: BreakoutEvent | None) -> tuple[date, float] | None:
    if h1h2_state is not None and h1h2_state.h2 is not None:
        return h1h2_state.h2.trigger_date, h1h2_state.h2.trigger_price
    if h1h2_state is not None and h1h2_state.h1 is not None:
        return h1h2_state.h1.trigger_date, h1h2_state.h1.trigger_price
    if breakout_event is not None:
        return breakout_event.date, breakout_event.breakout_level
    return None


def is_extended(
    df: pd.DataFrame,
    h1h2_state: H1H2State | None,
    breakout_event: BreakoutEvent | None,
    config: BrooksConfig,
) -> ExtensionResult:
    reference = _reference(h1h2_state, breakout_event)
    if reference is None:
        return ExtensionResult(is_extended=False, reason=None)

    reference_date, reference_price = reference
    reference_idx = df.index.get_indexer([pd.Timestamp(reference_date)])[0]
    if reference_idx < 0:
        return ExtensionResult(is_extended=False, reason=None)

    since = df.iloc[reference_idx + 1 :]
    if since.empty:
        return ExtensionResult(is_extended=False, reason=None)

    consecutive = 0
    for _, bar in since.iterrows():
        if strong_bull_bar(bar, config):
            consecutive += 1
        else:
            consecutive = 0
    if consecutive >= config.extended_consec_bull_bars:
        return ExtensionResult(is_extended=True, reason="consecutive_strong_bull_bars")

    last = df.iloc[-1]
    atr = last.get("atr14")
    if atr is not None and not pd.isna(atr) and atr > 0:
        atr_distance = (float(last["Close"]) - reference_price) / float(atr)
        if atr_distance >= config.extended_atr_multiple:
            return ExtensionResult(is_extended=True, reason="atr_distance")

    dist_ema20 = last.get("dist_ema20_pct")
    if dist_ema20 is not None and not pd.isna(dist_ema20) and dist_ema20 >= config.extended_ema20_distance_pct:
        return ExtensionResult(is_extended=True, reason="ema20_distance")

    return ExtensionResult(is_extended=False, reason=None)
