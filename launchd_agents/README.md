# Production schedule (launchd)

All 28 launchd jobs that drive ShortIndicator's scheduled services. Each file here is a
**verbatim copy** of what is installed in `~/Library/LaunchAgents/` on the production
machine — not a template. Copying one back into `~/Library/LaunchAgents/` and loading it
restores that job exactly.

Captured 2026-08-05. Every file in this directory was `cmp`-verified byte-for-byte
identical to the installed copy at capture time. 25 of the 28 are loaded; see
Observations for the three that are installed but not loaded.

Two jobs are **deliberate exceptions**, and they are exceptions of different kinds — do not
confuse them:

- One job present at capture time is **absent** from this directory: it was retired and is
  never coming back. See "Retired jobs — do not reinstate". Do not treat its absence as an
  omission to be repaired.
- One job **is** in this directory but is **never loaded** by a restore: `com.stockmonitor.eod`
  is paused pending improvement and will return. See "Paused jobs — stopped on purpose,
  will return". Do not treat its plist's presence as permission to start it.

Absolute paths (`/Users/sunilkumar/myProjects/ShortIndicator`) are baked in. That is
deliberate: the purpose is restoring *this* machine. On a different machine or username,
edit the paths before installing.

## Restoring the whole schedule

```bash
cd /Users/sunilkumar/myProjects/ShortIndicator

# 0. Prerequisites (see "Cross-repo dependency" below)
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
mkdir -p logs
#    NewsBase must also be checked out and its venv built.

# 1. Preview — checks every path each job references actually exists
./launchd_agents/install_launch_agents.sh

# 2. Install and load
./launchd_agents/install_launch_agents.sh --apply

# 3. Verify
launchctl list | grep -E 'nse|shortindicator|stockmonitor|nifty|weeklybacktest'
```

The script refuses to install a job whose referenced paths do not resolve, so a missing
venv or a missing NewsBase checkout shows up as a `SKIP` line rather than a job that
silently fails at 09:05 next Monday.

It also **copies but never loads** any job named in `DO_NOT_AUTOLOAD.txt`, printing a
`HELD` line with the reason:

```
HELD  com.stockmonitor.eod — copied to .../com.stockmonitor.eod.plist but DELIBERATELY NOT LOADED.
      Reason: PAUSED PENDING IMPROVEMENT — ...
```

That file is required: if it is missing, malformed, or names a label with no matching
plist, the script exits 1 without installing anything. It must never fail open, because a
held-back job that gets loaded anyway is exactly the accident it exists to prevent.

To restore a single job: `cp launchd_agents/<label>.plist ~/Library/LaunchAgents/` then
`launchctl load ~/Library/LaunchAgents/<label>.plist`. **Check `DO_NOT_AUTOLOAD.txt` first
— do not run the `load` step for a job listed there.**

## Cross-repo dependency: NewsBase

**ShortIndicator cannot start unattended without the NewsBase repository present and
working.** This is not optional and was previously undocumented.

`com.nse.central.collector` (09:05 Mon–Fri) runs `start_collector.sh`, which validates the
Kite access token and, if it is invalid, delegates the refresh to a module in a *different*
repository:

```
/Users/sunilkumar/myProjects/NewsBase/venv/bin/python3 -m data_feeds.token_refresh
```

If that command fails, `start_collector.sh` logs `Token refresh FAILED — cannot start
collector` and **exits 1** — the central data collector never starts, and every downstream
monitor that reads from the central quote DB runs blind for the day.

Verified present on the production machine at capture time:

- `/Users/sunilkumar/myProjects/NewsBase/` — exists
- `/Users/sunilkumar/myProjects/NewsBase/venv/bin/python3` — exists
- `/Users/sunilkumar/myProjects/NewsBase/data_feeds/token_refresh.py` — exists

So a full restore is: **restore NewsBase first, then ShortIndicator.**

## The jobs

Derived from the plists in this directory. `Mon–Fri` means the plist carries explicit
`Weekday` 1–5 entries; **`EVERY DAY` means it carries none and so fires on weekends too**
(see Observations). "Loaded" is `launchctl list` on 2026-08-05.

| Label | Runs | Schedule | Days | Loaded |
|---|---|---|---|---|
| `com.nse.prevent.sleep` | `start_caffeinate_if_trading_day.sh` | 07:50 (TimeOut 38400s ≈ until 18:30) | Mon–Fri | yes |
| `com.nse.token.reminder` | `check_token.py` | 08:00 | EVERY DAY | yes |
| `com.shortindicator.fo_universe_refresh` | `refresh_fo_universe.sh` | 09:00 | **Mon only** | yes |
| `com.stockmonitor.premarket` | `premarket_analyzer.py` | 09:00 | Mon–Fri | yes |
| `com.nse.central.collector` | `start_collector.sh` (→ NewsBase token refresh) | 09:05 | Mon–Fri | yes |
| `com.nse.gap.orb.monitor` | `start_gap_orb_monitor.sh` | 09:12 | Mon–Fri | yes |
| `com.shortindicator.vwapmovermonitor` | `start_vwap_mover_monitor.sh` | 09:12 | Mon–Fri | yes |
| `com.nse.orderflow.monitor` | `order_flow_monitor.py` | 09:14 | Mon–Fri | yes |
| `com.shortindicator.greekstracker` | `start_greeks_tracker.sh` | 09:14 | Mon–Fri | yes |
| `com.nse.stockmonitor` | `main.py` | 09:25 | Mon–Fri | yes |
| `com.nse.onemin.monitor.efficient` | `onemin_monitor_continuous.py` | 09:29 | Mon–Fri | yes |
| `com.nse.priceaction.monitor` | `price_action_monitor.py` | every 5 min, 09:25–15:25 (365 entries) | Mon–Fri | **NO** |
| `com.nse.atr.monitor` | `atr_breakout_monitor.py` | every 30 min, 09:30–15:00 (60 entries) | Mon–Fri | yes |
| `com.nifty.option.monitor` | `nifty_option_monitor.py` | every 15 min, 10:00–15:25 (23 entries) | EVERY DAY | yes |
| `com.nse.volume.profile.3pm` | `volume_profile_analyzer.py --execution-time=3:00PM` | 15:00 | EVERY DAY | yes |
| `com.nse.volume.profile.315pm` | `volume_profile_analyzer.py --execution-time=3:15PM` | 15:15 | EVERY DAY | yes |
| `com.nse.volume.profile.325pm` | `volume_profile_analyzer.py --execution-time=3:25PM` | 15:25 | EVERY DAY | yes |
| `com.nse.alert.eod.updater` | `update_eod_prices.py` | 15:30 | EVERY DAY | yes |
| `com.nse.alert.daily.update` | `daily_alert_price_update.sh` | 15:45 | EVERY DAY | yes |
| `com.nse.central.backfill` | `central_data_backfill.py` | 15:45 | Mon–Fri | yes |
| `com.nse.doublebottom.tracker` | `double_bottom_position_tracker.py` | 16:00 | EVERY DAY | yes |
| `com.stockmonitor.eod` | `start_eod_analyzer.sh` | 16:00 | Mon–Fri | **NO — paused on purpose, see below** |
| `com.sunildeesu.weeklybacktest` | `weekly_backtest_runner.py` | 16:00 | **Fri only** | yes |
| `com.nse.cpr.monitor` | `cpr_first_touch_monitor.py` | RunAtLoad + every 60s | continuous | yes |
| `com.nse.candle.reversal.monitor` | `candle_confirmation_monitor.py` | RunAtLoad + every 300s | continuous | yes |
| `com.nse.doublebottom.monitor` | `double_bottom_support_monitor.py` | RunAtLoad + every 300s | continuous | yes |
| `com.nse.intraday.candles` | `central_data_collector.py --intraday` | RunAtLoad + every 300s | continuous | yes |
| `com.nse.collector.watchdog` | `collector_watchdog.sh` | every 600s | continuous | **NO** |

No plist contains a secret. The only `EnvironmentVariables` keys across all 28 are `PATH`
(24 files) and `TZ=Asia/Kolkata` (3: `com.nifty.option.monitor`,
`com.nse.central.collector`, `com.nse.collector.watchdog`). Matches on
"token"/"secret"/"password" are filenames and labels only (`check_token.py`,
`com.nse.token.reminder`, `logs/token_reminder.log`).

## Paused jobs — stopped on purpose, will return

**Not the same as "Retired" below.** A retired job is gone for good and its definition is
deliberately not kept. A *paused* job is one the captain switched off on purpose, intends
to improve, and intends to bring back — its definition is kept precisely so it can return.
Do not merge these two sections, and do not move a job between them without the captain.

### `com.stockmonitor.eod` — paused 2026-08-05, pending improvement

**Current state, all of it deliberate:**

- `com.stockmonitor.eod.plist` **is installed** in `~/Library/LaunchAgents/` but is **not
  loaded**, so the job never fires. This is a choice, not a fault.
- The crontab entry `setup_eod_cron.sh` would install (`0 16 * * 1-5 …
  start_eod_analyzer.sh`) is **intentionally absent** — `crontab -l` reports *no crontab
  for sunilkumar*. The EOD analyzer is meant to run by neither mechanism right now.
- Its plist **stays versioned** in this directory. Losing the definition would be worse
  than the current state, because the job is coming back.
- `install_launch_agents.sh` copies it and refuses to load it, via `DO_NOT_AUTOLOAD.txt`.
  Without that, a machine rebuild would restart a job the captain deliberately stopped —
  silently reversing the decision during a recovery, the worst possible moment.

**The captain stopped it in order to improve it, and will re-enable it when ready. That
decision is theirs alone.** Do not "fix" it by loading the plist, do not run
`setup_eod_cron.sh`, and do not follow the cron setup steps in `EOD_ANALYSIS_SYSTEM.md`.

`eod_analyzer.py`, `start_eod_analyzer.sh` and `run_eod_for_date.py` all still work when
run by hand. Only the *schedule* is off.

To re-enable (captain only): delete the `com.stockmonitor.eod` line from
`DO_NOT_AUTOLOAD.txt`, move this section's entry out, and load the plist.

## Retired jobs — do not reinstate

Jobs here are **gone for good**. Nothing in this section is coming back; if you want a
job that is switched off but *will* return, look under "Paused jobs" above instead.

### `com.shortindicator.volumeprofile` — retired 2026-08-05

**It was a duplicate, not a loss.** It ran `start_volume_profile.sh` at 15:25 Mon–Fri,
which invokes `volume_profile_analyzer.py` with a hardcoded `EXECUTION_TIME="3:25PM"` —
exactly the work `com.nse.volume.profile.325pm` already does at 15:25 with
`--execution-time 3:25PM`.

The duplication was **confirmed empirically from the production log**: at `15:25:01` on
2026-08-05 the analyzer's startup banner appears twice, milliseconds apart — two processes
doing identical work.

The captain kept `com.nse.volume.profile.325pm` because it matches its 3:00 and 3:15
siblings in invocation style, and retired the wrapper-based job. On the machine it was
unloaded and its plist moved out of `~/Library/LaunchAgents` to
`~/Library/LaunchAgents.disabled-2026-08-05/`, where the disabled copy is kept.

If you are restoring after a machine loss: **do not recreate this job.** The three
surviving `com.nse.volume.profile.*` jobs cover 15:00, 15:15 and 15:25 completely.

`start_volume_profile.sh` itself was **not** deleted and is still in the repo — it remains
usable by hand (`./start_volume_profile.sh`). It is simply no longer scheduled.

## Observations — reported, not changed

None of the following was altered. Each is the captain's call.

1. **Three jobs are installed but not loaded**, so they do not run at all:
   `com.nse.priceaction.monitor`, `com.stockmonitor.eod`, `com.nse.collector.watchdog`.
   `com.stockmonitor.eod` is the one of the three that is **known to be deliberate** — it
   is paused pending improvement; see "Paused jobs" above, which is now the authority on
   it. The other two were not investigated and remain the captain's call.

2. **Nine jobs carry no `Weekday` restriction and therefore fire seven days a week**,
   including on weekends and NSE holidays: `com.nse.token.reminder`,
   `com.nifty.option.monitor`, the three `com.nse.volume.profile.*` jobs,
   `com.nse.alert.eod.updater`, `com.nse.alert.daily.update`,
   `com.nse.doublebottom.tracker` — plus the four `StartInterval` jobs, which are
   continuous by construction. These are bare-Python invocations and do not visibly
   self-guard from the plist.

3. **All referenced paths currently resolve.** Every `ProgramArguments` and
   `WorkingDirectory` path across the 28 was checked and exists.

4. **`setup_price_action_launchd.sh` is obsolete and would install a broken job.** It
   hardcodes `/Users/sunildeesu/myProjects/ShortIndicator` — the old username. The
   installed plist uses `/Users/sunilkumar/...`. The schedule it generates matches the
   installed one; only the paths are stale. It was not edited.

5. **`setup_eod_cron.sh` installs a cron job, not the launchd job** that is actually
   installed (`com.stockmonitor.eod`). The two mechanisms disagree about how the EOD
   analyzer should be scheduled, and neither is active **by choice** — running that script
   would re-enable a job the captain deliberately stopped. It now carries a banner saying
   so, as does the cron setup section of `EOD_ANALYSIS_SYSTEM.md`.

## Maintaining this directory

When a job is added, changed, or removed on the production machine, re-copy the plist here
in the same change and update the table above. If a job is deliberately stopped rather than
removed, add it to `DO_NOT_AUTOLOAD.txt` **and** to "Paused jobs" or "Retired jobs" —
whichever it actually is — in the same change. Re-verify with:

```bash
for f in launchd_agents/*.plist; do
  cmp -s "$f" "$HOME/Library/LaunchAgents/$(basename "$f")" || echo "DRIFT: $f"
done
```
