# Double-Bottom Backtest: Look-Ahead Correction and Strategy Assessment

**Date:** 2026-08-05
**Scope:** `backtest_double_bottom_portfolio.py` (entry logic), `config.py` (comments only)
**Data:** cached `data/double_bottom_backtest_candles.json` — 195 F&O stocks,
2023-07-24 .. 2026-07-23. No broker calls were made; no configuration value was changed.

---

## 1. What was wrong

`config.py` justified the strategy's parameters with `+295.9%` over three years, CAGR
59.4%, 76.1% win. Those numbers reproduce exactly from the backtest as it was written — so
the figures were not mis-transcribed. The backtest itself was wrong.

`audit_double_bottom_backtest.py` (committed two days after the figures) had already named
three look-ahead biases in `build_table()`. All three were still present. Each was
verified against the live path in `double_bottom_support_monitor.py` before being touched.

### L1 — the trend gate used the day's own close — CONFIRMED

```python
ind = cd[max(0, i - INDICATOR_BARS + 1):i + 1]        # window ENDS on day i
trend_sma = sma(ind, config.DOUBLE_BOTTOM_TREND_SMA_PERIOD)
if config.DOUBLE_BOTTOM_REQUIRE_UPTREND and (trend_sma is None or close <= trend_sma):
```

Live, `_evaluate()` is called per quote with the *live* price and an SMA computed once that
morning from history (`_compute_levels`, cached by date). At the moment the alert fires,
the price on the left of that comparison is near the day's low and the day's close does not
exist yet. The backtest instead asked "did this stock close above its SMA?" — which keeps
exactly the dips that recovered into the bell and discards the ones that kept falling.
This was the single most expensive bias: fixing it alone takes the 3-year return from
+276% to +104% in the audit's harness.

### L2 — level detection saw the signal day — CONFIRMED

```python
window = cd[i - lookback + 1:i + 1]                   # day i is IN the window
setups = find_double_bottom_setups(window, ...)
```

`find_double_bottom_setups` walks the window and rejects any low that later price traded
below (`if low > min_low_after: continue`), measures the middle-peak rally against the
highest high after the low, and counts touches across the whole window. With day `i` in the
window, day `i`'s **final** low decides whether the level is still unbroken, its **final**
high inflates the rally, and its bar can add a touch. None of that is knowable at the
retest.

The regression test demonstrates this concretely: on the synthetic fixture the pre-fix code
finds **zero** signals, because day *i*'s low (0.999 × level) undercuts the level by 0.1%
and deletes the setup that live would have alerted on hours earlier.

### L3 — breakdown days were deleted — CONFIRMED

```python
hit = next((s for s in setups
            if abs(low - s['level']) / s['level'] * 100 <= prox
            and low >= s['level'] * (1 - max_below / 100)), None)
```

The day's *final* low had to sit inside the alert band. Live, `_evaluate()` runs on every
quote: price entering the band triggers the alert immediately, and price then continuing
down through support is a loss the position already owns. Requiring the settled low to be
inside the band removes precisely the days support failed — the worst losses in the sample.

### Not a bias — the exit engine

`replay()` in `double_bottom_position_tracker.py` was read and is clean. It excludes the
entry day (`forward = [c for c in candles if date > entry_date]`) and ratchets the trail
only on completed bars, both deliberately and both commented. Nothing was changed there.

---

## 2. What was changed

Only `build_table()`'s entry boundaries, plus the two consequences of fixing them:

| Change | Why |
|---|---|
| levels from `cd[i-lookback : i]` | L2 — history only |
| SMA + ATR from `cd[i-INDICATOR_BARS : i]`, gate compared to the **entry price** | L1 — the live comparison |
| fire when day `i`'s `[low, high]` intersects the alert band; enter at the first band price the path must have reached | L3 — the live trigger |
| rows carry `entry_price`; `simulate()` fills from it | L3 makes the fill no longer always the band top |
| `TABLE_LOGIC_VERSION` added to the table cache key | the key fingerprinted parameters but not the code, so a stale pickle would have been reused silently |

The alert band is written as the live gate verbatim — `|price - level| ≤ prox` **and**
`price ≥ level × (1 - max_below)` — so the lower edge is whichever bound is tighter. Both
default to 1.0%.

**No configuration value, threshold, or runtime behaviour changed.** Verified mechanically:
all 323 module-level names in `config.py` compare equal to `HEAD`.

---

## 3. The corrected numbers

`venv/bin/python3 backtest_double_bottom_portfolio.py --years 3 --by-year`
— 195 F&O stocks, ₹1,00,000, 4 slots, current defaults.

| period | regime | median stock | **published (biased)** | **corrected** |
|---|---|---|---|---|
| 2023-07 .. 2024-07 | BULL | +57.1% | +101.1% | **+34.3%** |
| 2024-07 .. 2025-07 | FLAT | +1.8% | +43.4% | **+19.3%** |
| 2025-07 .. 2026-07 | FLAT | +1.1% | +40.8% | **+10.3%** |
| **full 3y** | BULL | **+70.2%** (85% of stocks up) | +295.9% | **+83.2%** |

| | published | corrected |
|---|---|---|
| CAGR | 59.4% | **22.8%** |
| max drawdown | 11.6% | **13.3%** |
| trades | 176 | **139** |
| win rate | 76.1% | **63.3%** |
| signals found | 503 | **382** |
| longest underwater | 123 days | **175 days** |

Roughly three-quarters of the advertised return was look-ahead.

### Reconciliation with the audit — they agree

The corrected backtest reports **+83.2%**; the audit's `ALL FIXES` variant reports
**+73.7%**. That gap is *not* a disagreement about entry logic. Cross-running the two
tables through the two portfolio engines isolates it completely:

| candidate table × portfolio engine | return | trades |
|---|---|---|
| corrected table × backtest `simulate()` | +83.2% | 139 |
| audit ALL-FIXES table × backtest `simulate()` | +83.2% | 139 |
| corrected table × audit `simulate()` | +73.7% | 130 |
| audit ALL-FIXES table × audit `simulate()` | +73.7% | 130 |

The tables are interchangeable. Field-by-field, the 380 rows they share are **identical** —
zero mismatches across `date`, `entry_price`, `level`, `strength`, `touches`, `rally`,
`atr_pct`. The corrected table has 2 extra rows, both at bar index 50, because the audit
uses a warmup of `max(...) + 1` where the backtest uses `max(...)`; both rows fall outside
the 3-year evaluation window and change nothing (restricting to `i >= 51` reproduces the
audit exactly).

The residual return difference is a **pre-existing, deliberate** difference between the two
portfolio engines, documented in the audit's own docstring: `backtest.simulate()` sizes at
`min(equity/slots, cash)` and takes a reduced-size position when cash is short, while
`audit.simulate()` sizes at `equity/size_div` and skips the trade instead. That is worth 9
extra trades and ~9 points. It is orthogonal to look-ahead and was left alone.

### Other config figures re-derived

The same discredited run also supplied the exit-geometry and trend-gate justifications.
Re-derived on the de-biased table (the fixed-target variant was validated against the live
`replay()` on all 142 non-arming trades, where the two engines must agree exactly):

| claim | published | corrected |
|---|---|---|
| fixed +6% exit | +171.7% | **+26.1%** |
| arm at +6%, trail 1.5% | +295.9% | **+83.2%** |
| trades armed | 129 of 176 | **86 of 139** |
| finished at or above +6% | 120 | **82** |
| overnight-gap exits (worst) | 9 (+5.5%) | **7 (+5.8%)** |
| armed trades that became losses | 0 | **0** |
| trail 1.0% / 1.5% / 2.0% | "tied; 1.5% halves gaps" | **+78.4% (12 gaps) / +83.2% (7) / +85.3% (5)** |
| trend gate on vs off | 70.0% → 81.2% win | **+1.71%/trade, 64.9% win vs +1.09%/trade, 60.4% win** |

Two of these are worth the captain's attention as *recommendations only* — no value was
changed:

- **`DOUBLE_BOTTOM_TRAIL_PCT`**: 2.0% now edges out the incumbent 1.5% (+85.3% vs +83.2%).
  Over 139 trades that spread is inside the noise, so this is not a reason to change it —
  but the old comment's specific claim ("1.5% earns the same as 1.0% while halving gap
  exits") no longer describes the data.
- **`DOUBLE_BOTTOM_REQUIRE_UPTREND`**: still the strongest single filter, but its advertised
  edge was largely the L1 bias measuring itself. It is worth ~+0.6%/trade and ~4.5 points of
  win rate, not the 11-point out-of-sample jump quoted.

---

## 4. Assessment: does the strategy earn its place?

**No — not on this evidence. Keep it on the debug channel.** The corrected result is
consistent with a strategy that has, at best, a small edge that the current test cannot
distinguish from noise, and it is measured in a window that flatters it.

**It lost to the market over the test window.** +83.2% over three years is a 22.8% CAGR.
The median stock in the same universe over the same window returned +70.2% — a 19.4% CAGR —
with 85% of stocks up. The strategy is ahead by about 13 points over three years while
holding four positions at a time, sitting in cash much of the time, and turning over 139
trades with the operational and tax burden that implies. In the one genuinely bullish year
it **underperformed outright**: +34.3% against a +57.1% median stock. Its only clear wins
are the two flat years, which is the honest version of the original claim — this is a
sideways-market strategy, not an all-weather one.

**The pattern itself is not distinguishable from a random entry.** The audit's control
takes the same dates, the same exit engine and the same ATR stop geometry but a *random*
stock instead of the one the double-bottom scan chose, 20 draws per signal:

```
double-bottom signals      374   +1.71%/trade   65.0% win
random stock, same dates  7279   +1.37%/trade   61.3% win
edge over random selection: +0.34%/trade  (Welch t = +0.90)
```

t ≈ 0.90 is roughly p ≈ 0.37. There is no statistical basis for claiming the double-bottom
*pattern* is doing the work. What return there is comes overwhelmingly from the exit
geometry — arm at +6% and trail — which the control also gets. That is a real finding about
where the edge lives: **the exit, not the entry.** A +6% hard exit on the same signals
returns +26.1%; arming and trailing returns +83.2%.

**Survivorship bias limits how far any of this can be pushed.** The universe is *today's*
F&O list replayed over three years of history. Stocks that were delisted, that fell out of
F&O, or that blew up are absent — and F&O membership is itself partly a function of having
performed well. This inflates the strategy and the benchmark together, which is why the
comparison between them is the meaningful number and the absolute +83.2% is not. But the
two are not inflated by the same amount, and which is inflated more is unknown: the
strategy only holds a name for a few weeks at a time, while the benchmark holds it for the
full three years, so the benchmark is plausibly the more flattered of the two — in which
case the 13-point margin shrinks or reverses. A 13-point margin over three years is well
within that uncertainty, so it cannot be relied on as a positive result. No conclusion
about absolute return should be drawn from this backtest at all.

**The captain's existing call is the right one.** `DOUBLE_BOTTOM_ALERTS_TO_DEBUG = true`
already routes these alerts away from the main channel with the note "backtest showed it
underperforms". The corrected evidence supports that decision more strongly than the
evidence available when it was made. Nothing here justifies promoting the alerts.

### What would actually settle it

The current test cannot distinguish "small real edge" from "no edge" — 139 trades and
t ≈ 0.90 are simply not enough resolution. Three things would:

1. **A point-in-time universe.** Reconstruct F&O membership as of each date rather than
   using today's list. Until that exists, no absolute number from this backtest means
   anything, and the survivorship caveat applies to every row above.
2. **A bear or sustained-downtrend period.** Every year in the data is bullish or flat. The
   SMA trend gate is the only thing standing between this strategy and a falling market,
   and it has never been tested against one. 2018-2020 data would do it.
3. **Forward paper-tracking of the live alerts.** The alerts already run and are already
   tracked; the position tracker records real outcomes. Six to twelve months of genuinely
   out-of-sample results, with no cached-candle backtest in the loop, would answer the
   question the way no amount of re-running history can.

Until at least (1) and (3) exist, the strategy should stay where it is: running, observed,
and off the main channel.

---

## Reproducing

```bash
venv/bin/python3 backtest_double_bottom_portfolio.py --years 3 --by-year   # corrected
venv/bin/python3 audit_double_bottom_backtest.py --years 3                 # audit
venv/bin/python3 tests/test_double_bottom_backtest_lookahead.py            # contract tests
```

All three read the cached candle file and make no API calls. The regression test is fully
synthetic and needs no data file at all.
