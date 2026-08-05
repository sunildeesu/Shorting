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
  `tests/test_auto_trade_history_persists.py` pins it).

**Python environment:** Use `venv/` (Python 3.13). Always run scripts from the project root.

**`UnifiedDataCache`:** a data type only exists if it is registered in *both* `DEFAULT_TTL` and
`cache_files` in `unified_data_cache.py`; an unregistered type is rejected with a logged ERROR and
no exception, so writes silently vanish. Payloads must be a `List[Dict]` — `set_data` copies each
element.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
