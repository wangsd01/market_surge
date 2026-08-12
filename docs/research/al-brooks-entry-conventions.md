# Al Brooks Entry/Stop Conventions vs. `brooks_screener.py`

Research date: 2026-08-11. Scope: verify 5 specific conventions in
`brooks/h1h2.py`, `brooks/breakout.py`, `brooks/stops_targets.py`, and
`brooks_screener.py` against Al Brooks' own documented price-action
methodology.

**Primary sources used** (Al Brooks' own site, brookstradingcourse.com):
- [Beginners should enter with stop orders](https://www.brookstradingcourse.com/how-to-trade-manual/stop-orders/) — "brooks-stop-orders"
- [Price Action Trading Glossary](https://www.brookstradingcourse.com/price-action-trading-terms-glossary/) — Brooks' own glossary, "brooks-glossary"
- [Ask Al: Buy the Close bull trend or reversal?](https://www.brookstradingcourse.com/ask-al/buy-the-close-trading-decision/) — trading-room Q&A transcript in Brooks' own words, "brooks-buy-the-close"

`brookstradingcourse.com` returns HTTP 403 to a plain fetch (bot-blocked);
these pages were retrieved successfully and are quoted directly below. No
paywalled book text was accessible, so where the site doesn't cover a point,
that gap is called out explicitly rather than filled with book paraphrases
I couldn't verify.

Secondary sources (blog summaries, not Brooks' own words) are labeled as such.

---

## 1. H1/H2 entry: buy-stop at `signal_bar_high + one tick`

**What we do:** `brooks/h1h2.py` places `naive_trigger_price = signal_bar_high * (1 + signal_bar_break_buffer_pct)` (0.05% buffer as a tick proxy), where the signal bar is the last bar of the pullback before the trigger bar breaks above it.

**What Brooks teaches:**

> "Beginning traders should enter with stop orders, for example, buying one tick above the high of the signal bar on a stop." — [stop-orders page](https://www.brookstradingcourse.com/how-to-trade-manual/stop-orders/)

> "The entry bar is the bar when you enter a trade and the signal bar is the bar before, which gives you a reason to enter." — same page

Secondary source (search-engine synthesis of H1/H2, cross-checked against glossary's `low 1, 2, 3, 4` entry, which describes the mirror-image L1/L2 mechanics consistently): "H1 (High 1) is the first pullback in a bull trend after a minor new high... the entry bar is the bar after the signal bar... if it goes above the signal bar high." This matches Brooks' own glossary structure for `low 1, 2, 3, or 4` (a low bar below the prior bar, with the next higher-low bar becoming the signal for entry above it) — same logic mirrored to the buy side.

**Verdict: Matches.** Our "signal bar = last bar of pullback, trigger = stop one tick above its high" is exactly Brooks' documented mechanic. The only divergence is *what* "one tick" means for stocks — see point 5.

---

## 2. Gap-through handling (fill at Open instead of the unreachable stop price)

**What we do:** if `trigger_open > naive_trigger_price`, use `trigger_open` as the realistic fill price instead of the stop level that price already gapped past (fixed recently in `brooks/h1h2.py`).

**What Brooks teaches:** No primary-source passage was found that addresses this specific scenario — a stop order that the market gaps through at the open — for daily-bar swing trading. Brooks' own material is written almost entirely from an intraday futures perspective, where an "opening gap" mid-day (not the daily-bar overnight gap this screener deals with) is discussed as a `gap` in his glossary:

> "gap — A space between any two price bars on the chart. An opening gap is a common occurrence and is present if the open of the first bar of today is beyond the high or low of the prior bar (the last bar of yesterday) or of the entire day." — [glossary](https://www.brookstradingcourse.com/price-action-trading-terms-glossary/)

He does not say what fill price to assume once a stop is gapped through. What he does say generally (stop-orders page) is that a stop order fills when "the market actually trades" through the trigger level — which, if the bar's open already cleared it, means the realistic fill is the open (a stop order cannot get a price better than the market's first available trade). That is standard order-mechanics reasoning, not a Brooks-specific rule, and it's consistent with — not contradicted by — anything in his accessible material.

**Verdict: Ambiguous / not explicitly documented by Brooks.** No source (primary or secondary) was found where Brooks says "skip the trade" on a gap-through, nor one where he explicitly names "use the open" as the fill convention. Our fix is sound order-mechanics logic and doesn't contradict anything Brooks teaches, but it isn't something we can cite him for directly.

---

## 3. Stop placement: "tight" (signal bar low) vs "structural" (pullback leg low)

**What we do:** `tight_stop = signal_bar_low - buffer`; `structural_stop = pullback_leg_low - buffer` (the low of the entire pullback leg, not just the signal bar); we prefer `structural_stop` by default.

**What Brooks teaches:** Brooks doesn't use the words "tight stop" and "structural stop" as a named, binary pair. What he does describe is a size/probability tradeoff between a stop just beyond the signal bar and a wider stop beyond the whole move, tied to conviction and how late you enter:

> "If you are buying a strong breakout on the 5 minute chart and you enter on the fourth bar of the breakout, your stop is below the low of this four bar rally, which might be 50 pips (ticks) away... since you are entering late, the profit that remains in the trade is less, and your reward might be only as big as your risk, instead of two or more times greater than your risk." — [stop-orders page](https://www.brookstradingcourse.com/how-to-trade-manual/stop-orders/)

> "...if you're buying a consecutive buy climax at resistance, I think you need a wide stop and you have to be patient." — [Ask Al: Buy the Close](https://www.brookstradingcourse.com/ask-al/buy-the-close-trading-decision/)

His glossary's `scalper` entry ("a trader who primarily scalps for small profits, usually using a tight stop") frames "tight stop" as a scalping-style choice, not a default. Elsewhere he defines `money stop` (a stop based on a fixed dollar/point amount, e.g. "a dollar in a stock") as a distinct, inferior alternative to a stop placed by chart structure — implying structure-based placement (beyond a swing/pullback low) is his preferred default over an arbitrary tight distance, which aligns directionally with our "prefer structural" choice, but he never states this as a rule specifically for H1/H2 setups.

**Verdict: Ambiguous — no named convention, but our default (prefer the wider, structure-based stop) is directionally consistent** with how Brooks talks about stop sizing (wider stops for higher-conviction/late entries; money-stops as an inferior shortcut vs. structure). We should not claim Brooks explicitly endorses "structural over tight by default" — he doesn't formalize it that way.

---

## 4. Buy-the-close / strong continuation entries (no H1/H2 pullback yet)

**What we do:** For `STRONG_BREAKOUT` / `STRONG_BREAKOUT_FOLLOW_THROUGH` states (no pullback yet), `_resolve_entry()` in `brooks_screener.py` uses `breakout_event.breakout_level * (1 + buffer)` — a buy-stop above the resistance level that was cleared. We do **not** implement anything called "Buy The Close," and we never use today's close as the entry price.

**What Brooks teaches:** "Buy The Close" is a real, named, distinct entry technique — not a synonym for a breakout buy-stop:

> "Buy The Close bull trend — A series of 2 or more bull trend bars closing near their highs. If the context is good for a rally, many bulls will buy the closes of the bars or above their highs." — [glossary](https://www.brookstradingcourse.com/price-action-trading-terms-glossary/)

And from the trading-room Q&A, in his own words describing exactly this "no pullback, strong continuation" situation:

> "Whenever I see something like this, breakout follow-through and more follow-through... I'm just not going to short. I'm either buying closes or I'm waiting to buy a pullback." — [Ask Al: Buy the Close](https://www.brookstradingcourse.com/ask-al/buy-the-close-trading-decision/)

So Brooks frames it as literally buying at (or slightly above) the closing price of a strong trend bar while it's happening / just after it closes — a market-style entry taken because waiting for a pullback risks missing the move — explicitly presented as an *alternative* to waiting for a pullback (H1/H2), not the same thing. Secondary sources corroborate: "you can buy the close of the bar and put your stop one tick below a prior bar."

**Verdict: Does not match — this is a real gap.** Our `STRONG_BREAKOUT` entry logic (buy-stop above the resistance level/breakout_level) is a reasonable and separately-defensible mechanic, but it is not "Buy The Close" and shouldn't be labeled or thought of as such. If the intent is to model Brooks' actual "Buy The Close" technique for the no-pullback-yet continuation case, the entry should be closer to "current/most recent strong bar's close" (or one tick above it), not a stop keyed off the resistance level that was cleared several bars ago at the original breakout.

---

## 5. Buffer size: 0.05% vs. Brooks' "one tick"

**What we do:** fixed `signal_bar_break_buffer_pct = 0.0005` (0.05% of price) as a stand-in for "one tick," applied uniformly across all stocks regardless of price.

**What Brooks teaches:** Brooks defines tick literally and explicitly, per-instrument, never as a percentage:

> "tick — The smallest unit of price movement. For most stocks, it is one penny; for 10-Year U.S. Treasury Note Futures, it is 1/64 of a point; and for Eminis, it is 0.25 points." — [glossary](https://www.brookstradingcourse.com/price-action-trading-terms-glossary/)

He gives no guidance for "tick-equivalent" sizing when trading a universe of stocks at different price levels (his own examples are almost all single-instrument E-mini futures, where tick size is fixed and uniform) — this cross-price-level generalization problem is genuinely outside what he addresses.

**Verdict: Partial mismatch.** A flat percentage buffer diverges from Brooks' literal "one tick = one penny for most stocks" at both ends of the price range:
- Low-priced stocks (e.g. ~$10): 0.05% ≈ $0.005 — *smaller* than Brooks' one-penny tick, and below most real stock tick increments.
- Mid-priced stocks (~$20): 0.05% ≈ $0.01 — happens to land close to a literal penny.
- Higher-priced stocks (~$200+): 0.05% ≈ $0.10+ — 10x+ wider than Brooks' literal one-cent tick, a much more conservative (later, worse-priced) trigger than he specifies.

Since modern US equities trade in penny increments (SEC Rule 612) regardless of share price, the theoretically closer-to-Brooks buffer would be a flat `$0.01` (or `max($0.01, small pct)` for very low-priced/volatile names), not a price-scaled percentage.

---

## Recommended changes

1. **Buffer size (point 5):** Consider replacing the flat 0.05% percentage buffer with a flat one-cent (`$0.01`) buffer, matching Brooks' literal "tick = one penny for most stocks" definition — this is the clearest, most directly-supported mismatch found. If a percentage-based safety margin is still wanted for very low-priced/volatile tickers, use `max($0.01, price * small_pct)` rather than a pure percentage.
2. **"Buy The Close" (point 4):** Either (a) rename `STRONG_BREAKOUT`/`STRONG_BREAKOUT_FOLLOW_THROUGH` entry logic to something that doesn't imply it's Brooks' "Buy The Close" technique (since it isn't), or (b) if the intent was genuinely to model Buy The Close, change the entry price for that no-pullback-yet case to the latest strong bar's close (or one tick above it) rather than the original breakout_level resistance line.
3. **Points 1, 2, 3:** No code changes indicated. Point 1 (H1/H2 stop-buy at signal-bar-high+tick) is directly confirmed correct. Points 2 and 3 are areas Brooks doesn't formalize explicitly in accessible material — our current choices are reasonable and not contradicted by anything found, but shouldn't be described in code comments/docs as "this is what Brooks says" since no exact source backs the specific gap-fill-at-open rule or the tight-vs-structural naming.

## Sourcing caveats

- All quotes above are from `brookstradingcourse.com` pages fetched directly (not paywalled, no login required) — these are Brooks' own words, either his written course material or a transcript of his own trading-room commentary.
- Brooks' books ("Trading Price Action Trends," "Trading Price Action Trading Ranges," "Trading Price Action Reversals," "Reading Price Charts Bar by Bar") were not accessible in full text online; no direct book quotes are used here. Everything cited is from his freely accessible site content, which covers the same core H1/H2/signal-bar/tick/Buy-The-Close vocabulary as the books use.
- Where noted "no primary source found" (points 2 and 3's specific named-convention claims), that reflects the limits of what's freely accessible on his site, not a search of the full book text — treat those verdicts as "unverified," not "Brooks disagrees."
