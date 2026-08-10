# Al Brooks Post-Earnings Bullish Screener Design

**Date:** 2026-08-10

## Goal

Classify every ticker in `ranking_all.csv` into one of 16 Al Brooks-style daily
price-action states, rank by *current trade quality* (not by how strong the
original breakout was), and emit a full-detail DataFrame plus 7 watchlist
buckets, using only data already available in this repo (OHLCV via
`fetcher.py`/`db.py`; no earnings-date source exists, so earnings-specific
classification is out of scope for v1).

## Scope

In scope:
- new `brooks/` package: `config.py`, `features.py`, `market_cycle.py`,
  `breakout.py`, `h1h2.py`, `extension.py`, `stops_targets.py`, `scoring.py`,
  `state.py`, `output.py`
- new `brooks_screener.py` CLI
- `tests/test_brooks/` — one test module per package module, plus
  `test_synthetic_scenarios.py` covering the 7 required end-to-end scenarios
- new `display.show_brooks_results()` (reuses the existing rich-table style
  from `display.py`)

Out of scope (v1):
- earnings-date fetching/classification (`FAILED_EARNINGS_BREAKOUT`,
  `earnings_recent`, `days_since_earnings` — columns emitted as `None`/`NaN`,
  no dedicated state emitted; folds into generic `FAILED_H1`/`FAILED_H2` /
  negative-follow-through labeling instead)
- charting integration (no `charts.py` overlay for Brooks states)
- modifying `patterns/high2.py`, `brooks_analysis.py`, or any existing
  pattern detector
- short-side (bearish) classification — long-only, per the stated objective
- H3+ pullback tracking — a third trigger after H2 is treated as continuation
  of the post-H2 trend, not a new labeled state (not among the 16 required
  states)

## Why This Fits The Repo

`fetcher.fetch_data()` + the SQLite cache in `db.py` already provide
cached, no-lookahead OHLCV for arbitrary tickers/ranges — the same path
`screener.py` and `main.py` use. `ranking_all.csv` is already the
screener's most current filtered/ranked output, so it's a natural ticker
source rather than re-scanning the full universe. `patterns/support_resistance.py`
already does level-clustering for resistance levels; `strategies.py`/
`actionability.py` already establish the "setup validity" vs "is it
actionable right now" split this project wants generalized into
`setup_quality_score` vs `entry_quality_score`. None of the existing
`PatternResult`/`PatternDetector` machinery fits a 16-state daily classifier
well (it's built around single-pattern pivot geometry, not day-by-day state
transitions), so this is a new, separately-testable package rather than a
new `PatternDetector`.

## Package Layout

```
brooks/
  config.py          # BrooksConfig — every threshold, tunable
  features.py         # bar-level + rolling features, no lookahead
  market_cycle.py      # 8-state cycle classifier, prior_trend, TR length
  breakout.py           # strong-breakout detection + follow-through
  h1h2.py                 # sequential H1/H2 state machine + failure tracking
  extension.py            # BTC-continuation vs extended detection
  stops_targets.py         # structural stops, targets, RR
  scoring.py                 # setup_quality / entry_quality / trade_score
  state.py                    # priority-ordered resolver -> final 16-state label
  output.py                    # row assembly, reason/warning text, buckets
brooks_screener.py              # CLI
tests/test_brooks/
  conftest.py
  test_features.py
  test_market_cycle.py
  test_breakout.py
  test_h1h2.py
  test_extension.py
  test_stops_targets.py
  test_scoring.py
  test_state.py
  test_synthetic_scenarios.py
```

Every module is pure (dataclasses/DataFrames in, dataclasses/DataFrames
out) — no file I/O, no network — so each is unit-testable with synthetic
`make_ohlcv`-style fixtures, matching CLAUDE.md's "no network in tests"
rule.

## Config (`brooks/config.py`)

All thresholds live on one `@dataclass BrooksConfig` with sensible defaults
so nothing is hard-coded inline. Defaults (all overridable):

| Field | Default | Used by |
|---|---|---|
| `lookback_bdays` | 252 | CLI fetch window |
| `min_bars_required` | 60 | skip ticker if fewer bars |
| `atr_period` | 14 | features |
| `vol_avg_period` | 20 | features |
| `ema_short` / `ema_long` | 20 / 50 | features |
| `slope_window_short` / `slope_window_long` | 20 / 50 | features |
| `swing_order` | 3 | market_cycle (argrelextrema order) |
| `min_swing_pct` | 0.02 | market_cycle (ignore swings < 2%) |
| `cycle_window` | 40 | market_cycle |
| `tr_length_probe_window` | 15 | market_cycle |
| `strong_trend_bar_ratio` | 0.65 | market_cycle |
| `trend_bar_ratio` | 0.55 | market_cycle |
| `trading_range_overlap_threshold` | 0.55 | market_cycle |
| `max_range_channel_width_pct` | 0.25 | market_cycle |
| `reversal_lookback_bars` | 5 | market_cycle |
| `short_tr_bdays` | 10 | market_cycle / scoring |
| `mature_tr_bdays` | 25 | market_cycle / scoring |
| `mature_tr_bear_relevance_floor` | 0.2 | scoring |
| `strong_body_ratio` | 0.6 | breakout |
| `strong_close_location` | 0.75 | breakout |
| `strong_range_atr_ratio` | 1.2 | breakout |
| `extreme_range_atr_ratio` | 1.8 | breakout |
| `extreme_close_location` | 0.8 | breakout |
| `breakout_vol_ratio` | 1.5 | breakout |
| `breakout_search_bars` | 60 | breakout |
| `breakout_score_min_threshold` | 0.5 | breakout |
| `follow_through_bars` | 3 | breakout |
| `shallow_retracement_max` | 0.35 | breakout |
| `moderate_retracement_max` | 0.60 | breakout |
| `anchor_max_age_bdays` | 15 | h1h2 |
| `anchor_lookback_bars` | 60 | h1h2 |
| `pullback_max_bars` | 8 | h1h2 |
| `signal_bar_break_buffer_pct` | 0.0005 | h1h2 / stops_targets |
| `h1_stale_bdays` | 3 | state |
| `h2_stale_bdays` | 4 | state |
| `max_state_resets` | 1 | h1h2 |
| `extended_consec_bull_bars` | 3 | extension |
| `extended_atr_multiple` | 3.0 | extension |
| `extended_ema20_distance_pct` | 0.12 | extension |
| `stop_buffer_pct` | 0.0005 | stops_targets |
| `min_plausible_rr` | 1.0 | scoring (penalize below this) |
| `weight_market_context` | 0.25 | scoring |
| `weight_breakout_quality` | 0.20 | scoring |
| `weight_follow_through` | 0.15 | scoring |
| `weight_current_setup` | 0.15 | scoring |
| `weight_reward_risk` | 0.15 | scoring |
| `weight_liquidity` | 0.10 | scoring |
| `min_dollar_vol_for_full_liquidity` | 50_000_000 | scoring |

## Data Flow

`brooks_screener.py`:
1. Read `Ticker` column from `--tickers-csv` (default `ranking_all.csv`).
2. `fetcher.fetch_data(tickers=..., low_start=<today - lookback_bdays>, end_date=<today>, cache_dir=Path("cache"), refresh=args.refresh, db_path=Path("market_surge.db"))` — same cached path as `screener.py`.
3. Reuse `screener._slice_for_patterns`-equivalent pivot (per-ticker `DatetimeIndex` OHLCV frame) — implemented locally as `_slice_for_ticker` since the pattern-lookback tail-truncation in `screener._slice_for_patterns` (`PATTERN_LOOKBACK_DAYS=180`) is shorter than Brooks' 252-day requirement; the two are not reused directly but follow the same groupby/sort/set_index shape.
4. Skip tickers with fewer than `config.min_bars_required` rows.
5. Run the pipeline (features -> market_cycle -> breakout/follow_through -> h1h2 -> extension -> stops_targets -> scoring -> state) per ticker, assemble one output row per ticker via `output.assemble_row`. Note: `scoring` runs *before* `state` — `resolve_state`'s `WAIT_FIRST_PULLBACK` rule (rule 15 below) consumes `entry_quality_score`, and none of `scoring`'s components depend on the resolved state label, so this ordering has no cycle.
6. Concatenate into a DataFrame, sort by `trade_score` descending.
7. Write full CSV + 7 bucket CSVs to `runs/brooks/<timestamp>/` (mirrors the existing `runs/` convention from `main.py`).
8. Print top 20 via `display.show_brooks_results()`.

No lookahead: every feature/classification for date `t` uses only bars at
or before index `t` (rolling/shift-based); `argrelextrema` swing detection
on a rolling *trailing* window only (never applied to the full series and
then read at an earlier date — each date's swing state is computed from
data available at that date).

## `features.py`

Given `df` (`DatetimeIndex`, `[Open, High, Low, Close, Volume]`), add columns:

- `prior_close = Close.shift(1)`, `prior_high = High.shift(1)`
- `daily_return = Close.pct_change()`
- `gap_pct = (Open - prior_close) / prior_close`
- `true_gap_up = Low > prior_high` (bool)
- `bar_range = (High - Low).replace(0, np.nan)` — zero-range bars produce
  `NaN` in all range-derived ratios below (never divide by zero)
- `body = (Close - Open).abs()`
- `body_pct = body / bar_range`
- `close_location = (Close - Low) / bar_range`
- `upper_tail_pct = (High - Close.clip(lower=Open... )) / bar_range` — precisely: `(High - np.maximum(Open, Close)) / bar_range`
- `lower_tail_pct = (np.minimum(Open, Close) - Low) / bar_range`
- `true_range = np.maximum.reduce([High-Low, (High-prior_close).abs(), (Low-prior_close).abs()])`
- `atr14 = true_range.rolling(config.atr_period, min_periods=config.atr_period).mean()`
- `range_atr_ratio = bar_range / atr14`
- `vol_sma20 = Volume.rolling(config.vol_avg_period, min_periods=config.vol_avg_period).mean()`
- `vol_ratio = Volume / vol_sma20`
- `ema20 = Close.ewm(span=config.ema_short, adjust=False).mean()`
- `ema50 = Close.ewm(span=config.ema_long, adjust=False).mean()`
- `dist_ema20_pct = (Close - ema20) / ema20`
- `dist_ema50_pct = (Close - ema50) / ema50`
- `recent_high_20/50/252 = High.shift(1).rolling(N, min_periods=1).max()` (excludes the current bar, so a breakout bar can actually exceed it)
- `dist_from_20d_high_pct = (Close - recent_high_20) / recent_high_20` (same for 50)
- `slope_20 / slope_50`: `scipy.stats.linregress(x=range(N), y=Close.tail(N)).slope / Close.tail(N).mean()`, computed via `.rolling(N).apply(...)`, `NaN` until `N` bars exist

## `market_cycle.py`

**Swings**: `scipy.signal.argrelextrema(High.values, np.greater_equal, order=config.swing_order)` for swing highs, same with `Low`/`np.less_equal` for swing lows, computed once over the full input `df` (this is safe — it never uses future bars beyond what's already asked for by `t`, since `t` is always the last bar of the slice given to the classifier for a given evaluation date). Discard swings whose move from the adjacent opposite-type swing is `< config.min_swing_pct`.

**Window classification** `classify_cycle_window(window) -> str` operates on the trailing `config.cycle_window`-bar slice and computes: `bull_ratio` (bars where `Close>Open` / len), `bear_ratio` (bars where `Close<Open` / len), `ema20_slope` (`slope_20` at the window's last bar), `pct_above_ema20` (fraction of bars with `Close>ema20`), `overlap_frac` (fraction of consecutive bar pairs where `(min(High_i,High_{i-1}) - max(Low_i,Low_{i-1})) / min(range_i,range_{i-1}) >= config.trading_range_overlap_threshold`), `channel_width_pct` (`(window.High.max()-window.Low.min())/((window.High.max()+window.Low.min())/2)`), and HH/HL vs LH/LL swing counts within the window.

Decision order (first match wins):
1. `ema20_slope>0 and pct_above_ema20>=0.80 and bull_ratio>=strong_trend_bar_ratio and HH/HL-dominant` -> `STRONG_BULL_TREND`
2. `ema20_slope>0 and pct_above_ema20>=0.60 and bull_ratio>=trend_bar_ratio and HH/HL-dominant` -> `BULL_TREND`
3. `ema20_slope<0 and pct_above_ema20<=0.20 and bear_ratio>=strong_trend_bar_ratio and LH/LL-dominant` -> `STRONG_BEAR_TREND`
4. `ema20_slope<0 and pct_above_ema20<=0.40 and bear_ratio>=trend_bar_ratio and LH/LL-dominant` -> `BEAR_TREND`
5. `overlap_frac>=trading_range_overlap_threshold and channel_width_pct<=max_range_channel_width_pct`:
   - `bull_ratio>=0.55 or pct_above_ema20>=0.60` -> `BULLISH_TRADING_RANGE`
   - `bull_ratio<=0.45 or pct_above_ema20<=0.40` -> `BEARISH_TRADING_RANGE`
   - else -> `TRADING_RANGE`
6. `_is_possible_reversal(...)` (see below) -> `POSSIBLE_MAJOR_TREND_REVERSAL`
7. fallback -> `TRADING_RANGE`

`_is_possible_reversal`: the `config.cycle_window`-bar segment *preceding* the last `config.reversal_lookback_bars` bars classifies as `BEAR_TREND`/`STRONG_BEAR_TREND`, AND at least one bar within the last `reversal_lookback_bars` satisfies breakout.py's `extreme_bull_breakout` predicate with `Close > ema20`.

**`trading_range_length`**: walk backward from the last bar; for each candidate end-index `e` (starting at `n-1`, decrementing), classify the trailing `config.tr_length_probe_window`-bar window ending at `e`; count consecutive trailing bars while the result is one of `{TRADING_RANGE, BULLISH_TRADING_RANGE, BEARISH_TRADING_RANGE}`; stop at the first non-TR classification. Result is the count.

**`prior_trend`**: `classify_cycle_window` on the `config.cycle_window`-bar window ending immediately before the trading range started (`index = n-1-trading_range_length`). If `trading_range_length==0`, `prior_trend` is undefined/`None` (current window isn't a TR, so there's no "before the TR" segment relevant to the bear-relevance discount).

**`bear_relevance`** (used by `scoring.py`, not part of the label itself): 1.0 if `prior_trend not in {BEAR_TREND, STRONG_BEAR_TREND}`; else `1.0` when `trading_range_length <= short_tr_bdays`, `mature_tr_bear_relevance_floor` when `trading_range_length >= mature_tr_bdays`, linear interpolation between.

Returns a `MarketCycleResult` dataclass: `current_cycle`, `prior_trend`, `trading_range_length`, `bear_relevance`.

## `breakout.py`

`strong_bull_bar(bar) = Close>Open and body_pct>=strong_body_ratio and close_location>=strong_close_location and range_atr_ratio>=strong_range_atr_ratio`

`extreme_bull_breakout(bar) = range_atr_ratio>=extreme_range_atr_ratio and close_location>=extreme_close_location and (Close>recent_high_20 or Close>recent_high_50)`

`breakout_score`: a data-driven rule list `[(name, predicate, weight)]` covering the 11 conditions from the spec (large bull body / body-vs-ATR / close near high / little upper tail / gap up / true gap / break of current-TR high / break of prior swing high / new 20/50/252-day high / volume expansion / breaking multi-week resistance), default equal weights summing to 1.0; `breakout_score = sum(weight for rules that pass) / sum(all weights)`.

`find_latest_breakout(df, market_cycle) -> BreakoutEvent | None`: scan indices `n-1` down to `max(0, n-breakout_search_bars)`; return the most recent bar where `breakout_score>=breakout_score_min_threshold` AND (`Close>recent_high_20` or `Close>recent_high_50`) — must actually clear a resistance level, not just look statistically strong. `BreakoutEvent` fields: `idx`, `date`, `breakout_score`, `is_strong`, `is_extreme`, `breakout_level` (highest resistance cleared), `gap_pct`, `true_gap_up`, `volume_ratio`.

`follow_through(df, breakout_event) -> FollowThroughResult | None`: `window = df.iloc[breakout_event.idx+1 : breakout_event.idx+1+follow_through_bars]`; `None` if `window` empty (breakout is today, nothing to confirm yet — this is exactly the `STRONG_BREAKOUT` vs `STRONG_BREAKOUT_FOLLOW_THROUGH` boundary in `state.py`). Positive/negative rule lists analogous to `breakout_score`'s pattern (higher high/low vs breakout bar, close above breakout-bar midpoint, close above `breakout_level`, another `strong_bull_bar`, low overlap / large bear bar, close near low, breaks breakout bar's own low, gap re-filled, 2+ consecutive bear closes). `follow_through_score = clip((pos_weight - neg_weight)/max_pos_weight, -1.0, 1.0)`.

`FollowThroughResult` also carries `retracement_pct` and `gap_still_open`, computed regardless of whether `window` is empty (both are meaningful from the breakout bar's own first day onward, unlike the bar-comparison follow-through conditions above which need at least one bar after the breakout):

`retracement_pct = (breakout_high - min(Low[breakout_idx : latest_idx+1])) / (breakout_high - breakout_low)`; `0.0` if `breakout_idx==latest_idx`. Buckets: `<0.35` shallow, `0.35-0.60` moderate, `0.60-1.00` deep, `>=1.00` full retracement.

`gap_still_open`: `None` unless `true_gap_up` at the breakout bar; else `True` iff no bar since the breakout has traded a `Low <= prior_high` (the top of the gap zone).

## `h1h2.py`

**Anchor**: if a `BreakoutEvent` exists and is within `anchor_max_age_bdays`, anchor = index of the highest `High` from the breakout bar onward. Otherwise, anchor = the most recent swing-high index (from `market_cycle`'s swing list) within `anchor_lookback_bars`. `None` if neither exists.

**Sequential scan** starting at `i = anchor_idx + 1`, two states (`seeking_pullback`, `in_pullback`):
- In `seeking_pullback`: if `High[i] < High[i-1]`, a pullback begins (`pullback_start_idx = i`, state -> `in_pullback`); otherwise stay in `seeking_pullback` (this correctly treats a fresh higher high as continuation, not a new trigger, exactly matching the "Day E is H1 continuation, not H2" example from the requirements).
- In `in_pullback`: if `High[i] > High[i-1]`, a trigger fires. Signal bar = `i-1`; trigger bar = `i`. `trigger_count += 1`. `pullback_leg_low = min(Low[pullback_start_idx : i])` (used for the structural stop/failure check). If `trigger_count==1`, this is `H1`. If `trigger_count==2`, this is `H2` and the scan stops (v1 does not track H3+). After a trigger, state returns to `seeking_pullback` (comparisons resume against the trigger bar).
- Scan ends at the last bar. If it ends in `in_pullback` with `trigger_count==0`, that's `H1_FORMING`; if `in_pullback` with `trigger_count==1`, that's `H2_FORMING`.

`TriggerEvent` fields: `signal_date`, `trigger_date`, `trigger_price = signal_bar_high * (1+signal_bar_break_buffer_pct)`, `signal_bar_low`, `signal_bar_high`, `pullback_leg_low`.

**Failure check** (`check_failure(trigger, latest_idx)`), applied independently to `h1` and `h2`: `window = df.iloc[trigger_idx+1 : latest_idx+1]` where `trigger_idx` is the trigger bar's index; `False, False` if empty. `tight_stop_failure = (window.Low < trigger.signal_bar_low).any()`. `structural_failure = (window.Low < trigger.pullback_leg_low).any()`. `strong_structural_failure = ((window.Close < trigger.pullback_leg_low) & (window.Close < window.Open)).any()`. `failed = tight_stop_failure or structural_failure or strong_structural_failure`.

**Reset on failure**: if the most advanced trigger (`h2` if present, else `h1`) failed, re-run the scan starting immediately after the failure was confirmed, looking for a brand-new anchor (a fresh swing high formed after the failure). Capped at `max_state_resets=1` (v1 doesn't chase indefinite failure chains). On reset, tag `reset_from_failure=True`, `prior_failed_pattern="h1"|"h2"` in the result metadata so `state.py`/`output.py` can produce the `"Prior H2 failed; current setup is a new H1 attempt."`-style warning.

`days_since_h1_trigger` / `days_since_h2_trigger` = `len(pd.bdate_range(trigger_date, latest_date)) - 1` (0 if trigger is today).

Returns `H1H2State`: `h1`, `h2`, `h1_failed`, `h2_failed`, `h1_structural_failed`, `h2_structural_failed`, `days_since_h1_trigger`, `days_since_h2_trigger`, `forming` (`"h1"|"h2"|None`), `reset_from_failure`, `prior_failed_pattern`.

## `extension.py`

`is_extended(df, h1h2_state, breakout_event) -> bool`: reference trigger = `h2.trigger_date` if present else `h1.trigger_date` else `breakout_event.date`; `None` -> not extended. From the reference bar to the latest bar:
- `consecutive_strong_bull_bars >= extended_consec_bull_bars` (strong per `breakout.strong_bull_bar`), OR
- `(Close[latest] - reference_price) / atr14[latest] >= extended_atr_multiple`, OR
- `dist_ema20_pct[latest] >= extended_ema20_distance_pct`

Returns `ExtensionResult(is_extended, reason)` where `reason` names which condition tripped (used in `warning` text, e.g. "entry extended 2.4 ATR above support").

## `stops_targets.py`

`compute_stops(h1h2_state, breakout_event) -> StopSet`: `signal_bar_stop = trigger.signal_bar_low - buffer`, `pullback_swing_stop = trigger.pullback_leg_low - buffer`, `breakout_bar_stop = breakout_event.breakout_level's bar Low - buffer` (if a breakout exists), `gap_failure_stop = prior_high_before_gap - buffer` (if `true_gap_up`). `tight_stop = signal_bar_stop`. `structural_stop = pullback_swing_stop` (preferred stop per the requirements — "prefer the structural stop when determining whether the setup remains logically valid").

`compute_targets(df, current_price, structural_stop, entry)`: `nearest_resistance` reuses `patterns.support_resistance.SupportResistanceDetector` — run it on the same `df`, take the lowest clustered level above `current_price`. `target_1 = nearest_resistance` (or the prior swing high from `h1h2_state`/`breakout_event` if no S/R level found above price). `target_2 = entry + 2*(entry-structural_stop)` (2R). `rr_target_1 = (target_1-entry)/(entry-structural_stop)`, `rr_target_2 = 2.0` by construction.

## `scoring.py`

Six components, each mapped to `0..10`:
- **market_context**: from `MarketCycleResult.current_cycle` (trend states score higher than ranges) `* bear_relevance` when `prior_trend` is bearish.
- **breakout_quality**: `breakout_score * 10`, penalized for large upper tail / weak close per the penalty rules below.
- **follow_through**: `(follow_through_score+1)/2 * 10` (rescaled from `-1..1`), `None` -> neutral `5.0` (breakout is today, nothing to confirm yet).
- **current_setup**: derived from `h1h2_state`/`extension` — a clean un-failed, non-extended, recently-triggered setup scores high; a failed or extended setup scores low; `WAIT_FIRST_PULLBACK`-shaped situations (strong stock, no pullback yet) score in the middle.
- **reward_risk**: `min(10, rr_target_1 * 5)`, floored to near-`0` when `rr_target_1 < min_plausible_rr`.
- **liquidity**: `min(10, dollar_vol / min_dollar_vol_for_full_liquidity * 10)`.

**Penalty/bonus rules**: a data-driven list `[(name, condition_fn, component, points)]` (matching sections 13-14 of the requirements 1:1 — each named condition maps to exactly one rule with its own unit test), applied additively to the relevant component before the `0..10` clamp.

`setup_quality_score = clip(0,10, market_context*0.25 + breakout_quality*0.20 + follow_through*0.15) / 0.6 * 10` (renormalized to a `0..10` scale using only its 3 components' relative weights).

`entry_quality_score = clip(0,10, current_setup*0.15 + reward_risk*0.15 + liquidity*0.10) / 0.40 * 10` (renormalized similarly).

`trade_score = market_context*weight_market_context + breakout_quality*weight_breakout_quality + follow_through*weight_follow_through + current_setup*weight_current_setup + reward_risk*weight_reward_risk + liquidity*weight_liquidity` (weights sum to 1.0, so this is already `0..10`).

## `state.py`

`resolve_state(market_cycle, breakout_event, follow_through, h1h2_state, extension, entry_quality_score) -> str`, priority-ordered (first match wins):

1. `h1h2_state.h2_failed and not h1h2_state.reset_from_failure` -> `FAILED_H2`
2. `h1h2_state.h1_failed and h1h2_state.h2 is None and not h1h2_state.reset_from_failure` -> `FAILED_H1`
3. `breakout_event is not None and follow_through is not None and follow_through.follow_through_score < 0 and follow_through.retracement_pct >= 1.0` -> `FAILED_H1` (generic failed-breakout bucket per the earnings-scope decision; `warning` notes "breakout fully retraced")
4. `extension.is_extended and h1h2_state.h2 is not None` -> `EXTENDED_AFTER_H2`
5. `extension.is_extended and h1h2_state.h2 is None` -> `EXTENDED_AFTER_BREAKOUT`
6. `breakout_event.idx == latest_idx` (breakout is today, no confirmation bars yet) -> `STRONG_BREAKOUT`
7. `breakout_event is not None and (latest_idx - breakout_event.idx) <= follow_through_bars and follow_through.follow_through_score > 0` -> `STRONG_BREAKOUT_FOLLOW_THROUGH`
8. `h1h2_state.days_since_h2_trigger == 0` -> `H2_TRIGGERED_TODAY`
9. `0 < h1h2_state.days_since_h2_trigger < h2_stale_bdays` -> `H2_TRIGGERED_RECENTLY`
10. `h1h2_state.forming == "h2"` -> `H2_FORMING`
11. `h1h2_state.days_since_h1_trigger == 0 and h1h2_state.h2 is None` -> `H1_TRIGGERED_TODAY`
12. `0 < h1h2_state.days_since_h1_trigger < h1_stale_bdays and h1h2_state.h2 is None` -> `H1_TRIGGERED_RECENTLY`
13. `h1h2_state.forming == "h1" and breakout_event is not None and (latest_idx - breakout_event.idx) <= 5 and follow_through is not None and follow_through.retracement_pct <= moderate_retracement_max` -> `BREAKOUT_PULLBACK` (shallow, controlled pullback directly off a strong breakout)
14. `h1h2_state.forming == "h1"` -> `H1_FORMING`
15. `market_cycle.current_cycle in {STRONG_BULL_TREND, BULL_TREND} and entry_quality_score < 5.0` -> `WAIT_FIRST_PULLBACK`
16. fallback -> `TRADING_RANGE`

## `output.py`

`assemble_row(...) -> dict` with exactly the columns listed in the
requirements (ticker, date, market_cycle, prior_trend, trading_range_length,
earnings_recent=`None`, days_since_earnings=`None`, gap_pct, true_gap,
gap_still_open, breakout_score, follow_through_score, retracement_depth,
setup_state, h1_status, h1_trigger_date, days_since_h1, h2_status,
h2_trigger_date, days_since_h2, signal_bar_high, signal_bar_low,
pullback_low, proposed_entry, tight_stop, structural_stop, risk_pct,
nearest_resistance, target_1, target_2, rr_target_1, rr_target_2,
setup_quality_score, entry_quality_score, trade_score, reason, warning).

`reason`/`warning` are built from the same penalty/bonus rule list used in
`scoring.py` (which rules fired) plus key facts (pattern, pullback length,
stop distance) — same pattern as `strategies.summary_reason`.

`build_watchlist_buckets(df) -> dict[str, pd.DataFrame]`:
- `READY_NOW`: `setup_state in {STRONG_BREAKOUT, STRONG_BREAKOUT_FOLLOW_THROUGH, H1_TRIGGERED_TODAY, H1_TRIGGERED_RECENTLY, H2_TRIGGERED_TODAY, H2_TRIGGERED_RECENTLY, BREAKOUT_PULLBACK}` and `entry_quality_score >= 5.0` and `rr_target_1 >= min_plausible_rr`
- `WAIT_PULLBACK`: `setup_state == WAIT_FIRST_PULLBACK`
- `H1_WATCH`: `setup_state == H1_FORMING`
- `H2_WATCH`: `setup_state == H2_FORMING`
- `STRONG_FOLLOW_THROUGH`: `setup_state in {STRONG_BREAKOUT, STRONG_BREAKOUT_FOLLOW_THROUGH}`
- `EXTENDED_DO_NOT_CHASE`: `setup_state in {EXTENDED_AFTER_BREAKOUT, EXTENDED_AFTER_H2}`
- `FAILED_SETUP`: `setup_state in {FAILED_H1, FAILED_H2}`

Each bucket sorted by `trade_score` descending.

## CLI (`brooks_screener.py`)

```
python brooks_screener.py [--tickers-csv ranking_all.csv] [--top 20]
                           [--output-dir runs/brooks/<timestamp>] [--refresh]
```

Uses `fetcher.fetch_data`, writes `runs/brooks/<timestamp>/brooks_ranking.csv`
plus one CSV per bucket (`ready_now.csv`, `wait_pullback.csv`, etc.), prints
top N via `display.show_brooks_results()`.

## Test-First Plan

Every module gets its own test file built on synthetic price paths (extend
`tests/conftest.py`'s `make_ohlcv` fixture style — explicit price/volume
lists, no network, no randomness).

- **test_features.py**: zero-range bar produces `NaN` (not a crash) in all range ratios; hand-computed gap/true-gap/ATR/EMA values on a short fixed series; `recent_high_20` excludes the current bar.
- **test_market_cycle.py**: a monotonic uptrend series classifies `STRONG_BULL_TREND` or `BULL_TREND`; a monotonic downtrend classifies `STRONG_BEAR_TREND`/`BEAR_TREND`; a flat overlapping series classifies a `*_TRADING_RANGE` variant; comparative test: `bear_relevance` for `trading_range_length=8` (short) is `1.0`, for `trading_range_length=30` (mature) is `0.2`, matching the "mature TR discounts old bear trend" requirement.
- **test_breakout.py**: `strong_bull_bar`/`extreme_bull_breakout` boolean checks on hand-built single bars; `find_latest_breakout` picks the most recent qualifying bar, not the highest-scoring one further back; positive vs negative synthetic follow-through sequences; `post_breakout_retracement_pct` bucket boundaries (0.34/0.35, 0.59/0.60, 0.99/1.00).
- **test_h1h2.py**: reproduce the exact Day A-G worked example from the requirements (`highs = [100, 97, 95, 96, 98, 96, 97]`) — assert H1 signal=C, trigger=D; assert E does *not* create a new trigger; assert H2 signal=F, trigger=G; assert `trigger_price = signal_bar_high * 1.0005`.
- **test_h1h2_failure.py** (or folded into `test_h1h2.py`): a triggered H1 followed by a bar trading below `signal_bar_low` sets `h1_failed=True`; a triggered H2 followed by a bar trading below `pullback_leg_low` sets `h2_failed=True` and `structural_failure=True`; after failure, a fresh anchor/pullback/trigger sequence is picked up with `reset_from_failure=True`.
- **test_extension.py**: 3+ consecutive `strong_bull_bar`s past the trigger flips `is_extended=True`; a single strong bar does not.
- **test_stops_targets.py**: `structural_stop` uses `pullback_leg_low`, not `signal_bar_low`; `nearest_resistance` correctly delegates to `SupportResistanceDetector`; low-RR setup (`entry` near resistance, `structural_stop` far) produces `rr_target_1 < min_plausible_rr`.
- **test_scoring.py**: the spec's own worked example — a setup with `setup_quality_score≈9.5` (strong breakout, poor current entry: extended) and `entry_quality_score≈5.5`, vs. a setup with `setup_quality_score≈7.5` and `entry_quality_score≈9.0` (clean pullback, nearby structural stop) — assert the *entry-quality-weighted* component ordering matches; each penalty/bonus rule gets one direct unit test asserting its point delta fires under its exact triggering condition and not otherwise.
- **test_state.py**: construct minimal (non-OHLCV) `MarketCycleResult`/`BreakoutEvent`/`FollowThroughResult`/`H1H2State`/`ExtensionResult` inputs for each of the 16 states and assert `resolve_state` returns the correct label; assert priority ordering (e.g. extension overrides a technically-still-recent H2 trigger; failure overrides everything else).
- **test_synthetic_scenarios.py**: full `brooks_screener` pipeline (features through output) run against 7 synthetic tickers built as explicit price paths:
  1. **H1 only** — uptrend, pullback, one trigger, no second pullback yet -> `H1_TRIGGERED_RECENTLY` or `H1_FORMING`.
  2. **Clean H2** — uptrend, pullback, H1 trigger, continuation (no fail), second pullback, H2 trigger 1-2 bars ago -> `H2_TRIGGERED_RECENTLY`, `entry_quality_score` high.
  3. **H2 already extended** — same as (2) but followed by 4+ strong bull bars -> `EXTENDED_AFTER_H2`.
  4. **Failed H2** — H2 triggers, then price trades below `pullback_leg_low` -> `FAILED_H2`.
  5. **Strong BTC continuation, no H2** — strong breakout bar, 2 more strong bull bars immediately after, no pullback yet -> `STRONG_BREAKOUT_FOLLOW_THROUGH`.
  6. **Breakout with poor follow-through** — strong breakout bar, then a large bear bar closing near its low -> low `follow_through_score`, `FAILED_H1`/generic-failed labeling per rule 3.
  7. **Strong breakout but bad reward/risk** — clean H1 trigger, but `nearest_resistance` sits just above `entry` (constructed via a prior swing high close to the trigger price) -> `rr_target_1 < min_plausible_rr`, excluded from `READY_NOW` bucket even though `setup_state` looks actionable.
  
  Assert both label correctness and that ranking behaves sanely: scenario 2 (clean pullback, good RR) outranks scenario 3 (extended) by `trade_score`; scenario 7 is excluded from `READY_NOW` despite a clean-looking state.

## Risks

- The market-cycle and H1/H2 heuristics are inherently judgment calls (as
  the requirements themselves note — "the goal is not to mechanically find
  every H1/H2"); thresholds are centralized in `BrooksConfig` specifically
  so they can be retuned against real results without touching logic.
- Skipping earnings-date data means big generic gaps and true earnings gaps
  are scored identically in v1; the `warning` column is written to never
  claim an earnings cause it can't verify.
- `SupportResistanceDetector` reuse for `nearest_resistance` assumes its
  90-day-oriented level clustering behaves reasonably over a 252-day input;
  if levels look too coarse/stale in practice, this is an isolated swap
  inside `stops_targets.py`.

## Acceptance Criteria

- All 16 states are reachable and covered by `test_state.py`.
- `test_h1h2.py` reproduces the requirements' own Day A-G example exactly
  (H1 at C->D, E is continuation not H2, H2 at F->G).
- `setup_quality_score` and `entry_quality_score` diverge in the direction
  the requirements specify for the "extended great breakout" vs "clean
  pullback entry" cases.
- The 7 required synthetic scenarios each resolve to a sensible state and
  the full pipeline runs end-to-end with no network access in tests.
- `python -m pytest tests/` all green; `brooks_screener.py` runs against
  `ranking_all.csv` and produces a sorted CSV + 7 bucket CSVs without
  touching `patterns/`, `brooks_analysis.py`, or any existing module.
