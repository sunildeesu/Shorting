# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.
(`CLAUDE.md` is a symlink to this file.)

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 5. Project-Specific Notes (ShortIndicator)

This is a **live NSE stock monitoring and alerting system**. Changes to core infrastructure can silently break live signals.

**Shared infrastructure — edit with extra care:**
- `config.py` — central config used by nearly every script
- `unified_data_cache.py` / `unified_quote_cache.py` — shared data layer
- `telegram_notifier.py` — live alert delivery
- `central_quote_db.py` / `central_data_collector.py` — real-time data pipeline

**Monitors that run live (launchd agents):**
- `stock_monitor.py`, `onemin_monitor.py`, `nifty_option_monitor.py`, `cpr_first_touch_monitor.py`, `atr_breakout_monitor.py`
- Changes to these require confirming the launchd `.plist` is reloaded after deployment.
- Launchers start monitors *before* the market opens (e.g. 09:12) but `market_utils.is_market_open()`
  is only true 09:25–15:25 (`config.MARKET_*`), so "market is closed" alone must never end a monitor —
  it would die at launch every morning. A monitor that is meant to be one-process-per-day exits on its
  own end-of-day condition instead; `vwap_mover_monitor._shutdown_reason()` is the worked example, and
  `tests/test_vwap_mover_monitor_daily_exit.py` pins it. Monitors that instead span midnight need
  day-rollover handling (`_check_day_reset`) — check which kind you are editing before changing a loop.

**Before changing signal/alert logic:**
- Understand the full detection → filter → alert pipeline first.
- Prefer backtesting (`backtest_*.py`) to verify behavior before touching live monitors.
- Backtest figures quoted in `config.py` comments are not self-verifying. One set was found
  to be ~3.5x inflated by look-ahead in the backtest's own entry logic — see
  `DOUBLE_BOTTOM_BACKTEST_AUDIT.md`. A `backtest_*.py` entry decision may use bars strictly
  before day *i* plus day *i*'s open/high/low, never its close and never a later bar;
  `tests/test_double_bottom_backtest_lookahead.py` pins that contract for the one that was
  fixed. If you re-derive numbers, re-derive the config comment in the same change.
  A second set — the auto-trader's "97% win rate / +1.67%" — had no producing script at all;
  the measured record is ~46.6% / +0.03%, re-derivable with `analyze_auto_trade_record.py`.
  Treat an unsourced performance figure as false until a script in-repo reproduces it.
- Live P&L evidence must outlive the trading day. `data/*_positions.json` files are
  current-day state and are reset on date change; anything you want to judge a strategy by
  later belongs in an append-only sibling log (`auto_trader._append_history` is the pattern,
  `tests/test_auto_trade_history_persists.py` pins it). Same trap inside a database: a
  cooldown table keyed `PRIMARY KEY (symbol, alert_type)` and written `INSERT OR REPLACE`
  keeps only the last fire — `order_flow.db` needed a separate append-only `alert_log`
  beside `alert_history` for that reason (`tests/test_order_flow_alert_history.py`).

- **Order flow signals were measured (2026-08-10) to have no tradeable edge** — 611 alerts
  over 15 trading days, 0 of 12 tests surviving Bonferroni, largest gross edge 0.090%
  against a 0.15% round-trip cost floor. They route to the debug Telegram channel by the
  captain's decision. Fix defects there; do not retune thresholds hunting for edge.
  `OVERNIGHT_BULL` has never fired (its gate conjunction is empirically unsatisfiable) and
  standalone wall alerts were removed as dead code.

**The production schedule lives in `launchd_agents/`** — verbatim copies of all 29 installed
launchd jobs, plus `launchd_agents/README.md` (per-job table, restore procedure, known
duplicate/unloaded jobs). It is the source of truth for *what is scheduled*; several
`setup_*.sh` scripts still write their own plists and some have drifted, so check
`launchd_agents/` before believing a setup script. If you change a job on the machine,
re-copy it here in the same change.

**Cross-repo dependency:** `start_collector.sh` (job `com.nse.central.collector`, 09:05
Mon–Fri) refreshes the Kite token via `NewsBase`'s `data_feeds.token_refresh` and **exits 1
if it fails**, so the central collector — and everything downstream of the quote DB —
cannot start without the NewsBase repo present and working.

**Python environment:** Use `venv/` (Python 3.13). Always run scripts from the project root.

**`UnifiedDataCache`:** a data type only exists if it is registered in *both* `DEFAULT_TTL` and
`cache_files` in `unified_data_cache.py`; an unregistered type is rejected with a logged ERROR and
no exception, so writes silently vanish. Payloads must be a `List[Dict]` — `set_data` copies each
element.

**NFO option symbols:** never build a trading symbol with a format string. NSE uses one
convention for weekly expiries (`NIFTY2681125700CE`, 2026-08-11) and another for monthly
(`NIFTY26AUG25350CE`, 2026-08-25), plus month letters O/N/D and holiday-shifted dates.
Formatting every symbol the weekly way is what recorded every monthly position at premium ₹0
(`data/nifty_options/position_state.json`, frozen 2026-07-20). Resolve against
`kite.instruments("NFO")` instead — `nifty_option_analyzer._resolve_option_symbol` is the
worked example, pinned by `tests/test_nifty_option_analyzer_measurement.py`. Conventions are
verifiable without a broker: NSE's F&O bhavcopy is public and unauthenticated
(`https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip`,
`FinInstrmNm` holds the trading symbol).

**NIFTY weekly expiry is not "next Thursday".** NSE moved weekly expiry to Tuesday effective
2025-09-01 — last Thursday expiry 2025-08-28, first Tuesday expiry 2025-09-02 — and holidays
shift an expiry BACK one session, never forward. Never write weekday arithmetic; call
`market_utils.get_next_weekly_expiry()`, whose docstring carries the rule and its two known
limitations (Muhurat sessions, and dependence on the 2025–2026-only `NSE_HOLIDAYS` table).
`tests/test_weekly_expiry_resolver.py` pins it against NSE-confirmed expiry dates. The live
path is separate and already correct: `nifty_option_analyzer.py` resolves from the NFO
instrument dump and computes no weekday.

**A failed lookup must never become a number.** Kite's `quote()` returns neither `greeks` nor
`implied_volatility`, and a missing quote has no `last_price`. Defaulting either — premium 0,
or the old hardcoded 20% IV — records a fabricated measurement as if it were observed. Refuse
(`OptionDataError` in `nifty_option_analyzer.py`) so the monitor's `if 'error' in result`
branch drops the cycle. Greeks come from inverting Black-Scholes on the observed premium.

**Every alert carries its own provenance.** `alert_provenance.stamp()` appends a
`[ShortIndicator · <service>]` footer, where `<service>` defaults to the entry-point script
name (`sys.argv[0]`) — so a new monitor is covered without touching it. `BaseNotifier`
stamps at its three HTTP payload sites, and the ten scripts that bypass `BaseNotifier` with
their own `requests.post(.../sendMessage)` stamp at the payload too. Never hand-write a
service label into a message body; if the derived name is wrong, call
`alert_provenance.set_service()` at process start. `tests/test_alert_provenance.py` pins it.

**Secrets come from the Keychain; never `os.getenv` them and never truncate `.env`.**
`credentials.get_secret()` is the only way to read one (macOS Keychain, service
`ShortIndicator`, account = the key name), with a *temporary* `.env` fallback that phase 2
deletes. The ~200 non-secret tuning settings stay ordinary `os.getenv` reads of `.env`.
Any write to `.env` goes through `credentials.update_env_atomic()` — temp file + fsync +
`os.replace`. This is not style: on 2026-08-09 two token-refresh writers landed 514 µs
apart, one read inside the other's `open(path,'w')` truncate window, and `.env` came back
as a single line — 22 settings lost, including the Telegram tokens that would have raised
the alarm, so twelve services were silently down for 90 minutes of live trading.
`tests/test_credentials_keychain.py` pins it, and proves the harness by running the
pre-incident algorithm through it and catching the empty file. Cross-repo: NewsBase's
`data_feeds/token_refresh.py` calls `TokenManager.update_env_file()` after `chdir(SI_PATH)`
— keep that name and signature.

**Kite intraday history: measured, not remembered.** Probed against the live API on
2026-08-11 (RELIANCE): one `historical_data` request may span at most **100 days** for
`5minute` (`InputException: interval exceeds max limit: 100 days`), and depth reaches back
to at least 2016 — the "~60 days for minute data" in older docstrings is not the binding
constraint. Kite also publishes the **tail of a session late**: a day fetched within about
a week stops at 15:10, and the same day fetched a fortnight later has all 75 bars
(09:15–15:25). Anything that decides "this day is already stored" must therefore key on
completeness, not presence — `backfill_intraday_candles.py` is the worked example
(`PROVISIONAL_DAYS`), pinned by `tests/test_intraday_backfill.py`.

**`CentralQuoteDB.cleanup_old_data()` does not run in production.** Its only caller is
`central_data_collector.main()` (`central_data_collector.py:737`), but the live jobs run
`central_data_collector_continuous.py` (`com.nse.central.collector`) and
`central_data_collector.py --intraday` (`com.nse.intraday.candles`), which returns before
that branch. So `central_quotes.db` grows unbounded, and both retention settings are
currently declarations of intent, not behaviour. Do not wire it up casually: it also runs
`VACUUM`, an exclusive rewrite of a 370 MB+ database, and it deletes quote rows on a 1-day
window. `tests/test_intraday_retention.py` pins what the function does when it is called.

**Stored 5-minute bars are gap-free inside a session, never across one.** Measured
2026-08-11 over 195 symbols × 16 sessions: 225,401 of 225,401 intra-session steps are
exactly 5 minutes, every timestamp carries `+05:30`, and the step across a session boundary
is ~17h50m–18h05m (overnight) or ~2d18h (weekend). A resampler that buckets by wall-clock
time alone will fabricate bars spanning the overnight gap; group by session date first. A
full session is 75 bars, which divides evenly into 15m but not into 10m or 1h.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
