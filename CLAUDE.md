# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

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

**Before changing signal/alert logic:**
- Understand the full detection → filter → alert pipeline first.
- Prefer backtesting (`backtest_*.py`) to verify behavior before touching live monitors.

**Python environment:** Use `venv/` (Python 3.13). Always run scripts from the project root.
