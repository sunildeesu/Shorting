# Weekly Backtest Automation - Setup Guide

This system automatically runs backtests every week using **REAL historical option data** from Kite Connect, building a comprehensive performance database over time.

---

## 🎯 What This Does

1. **Runs every Friday at 4:00 PM** automatically (after market hours)
2. **Backtests past 7 days** with real option prices from Kite
3. **Stores results** in SQLite database (cumulative)
4. **Generates weekly reports** in `data/weekly_reports/`
5. **Sends Telegram alerts** with performance summary
6. **Tracks trends** over weeks/months

---

## 📁 Files Created

| File | Purpose |
|------|---------|
| `weekly_backtest_runner.py` | Main script that runs the backtest |
| `setup_weekly_backtest.sh` | One-time setup for automation |
| `view_backtest_history.py` | Query and analyze historical data |
| `data/backtest_history.db` | SQLite database (stores all trades) |
| `data/weekly_reports/` | Weekly markdown reports |
| `logs/weekly_backtest.log` | Execution logs |

---

## 🚀 Initial Setup (One-Time)

### Step 1: Make Scripts Executable
```bash
chmod +x setup_weekly_backtest.sh
chmod +x weekly_backtest_runner.py
chmod +x view_backtest_history.py
```

### Step 2: Run Setup
```bash
./setup_weekly_backtest.sh
```

This will:
- Create macOS launchd configuration
- Set up to run every Friday at 4:00 PM (after market hours)
- Create logs directory
- Start the automation

### Step 3: Verify Setup
```bash
launchctl list | grep weeklybacktest
```

You should see:
```
-	0	com.sunildeesu.weeklybacktest
```

---

## 🧪 Test Manually (Before Waiting for Friday)

Run the backtest immediately to seed the database:

```bash
./venv/bin/python3 weekly_backtest_runner.py
```

This will:
1. Backtest past 7 days
2. Save results to database
3. Generate a report in `data/weekly_reports/`
4. Send Telegram alert

---

## 📊 Viewing Results

### 1. All-Time Statistics
```bash
./venv/bin/python3 view_backtest_history.py --all-time
```

Shows:
- Total trades analyzed
- Win rate (all-time)
- Total P&L
- Day-of-week breakdown

### 2. Last 30 Days
```bash
./venv/bin/python3 view_backtest_history.py --last-month
```

### 3. Weekly Trends
```bash
./venv/bin/python3 view_backtest_history.py --trends
```

Shows last 10 weeks performance

### 4. Analyze Losing Days
```bash
./venv/bin/python3 view_backtest_history.py --losing-days
```

Shows:
- All losing days
- Patterns (DTE, movement, day of week)
- Top 10 worst losses

### 5. Export to Excel/CSV
```bash
./venv/bin/python3 view_backtest_history.py --export
```

Creates `data/backtest_history_export.csv`

---

## 📈 What You'll Learn Over Time

After 4-8 weeks, you'll have enough data to answer:

### 1. **Is the Strategy Actually Profitable?**
```bash
./venv/bin/python3 view_backtest_history.py --all-time
```

Check:
- Win rate > 70%? ✅ Good
- Win rate < 60%? ⚠️ Needs work
- Total P&L positive? ✅ Working
- Total P&L negative? ❌ Stop trading!

### 2. **Which Days to Trade?**
```bash
./venv/bin/python3 view_backtest_history.py --all-time
```

Look at "Day of Week Breakdown":
- If Wednesday avg P&L = ₹500 → Trade Wednesdays
- If Monday avg P&L = -₹200 → Skip Mondays

### 3. **Is Performance Improving or Degrading?**
```bash
./venv/bin/python3 view_backtest_history.py --trends
```

If win rate is declining week-over-week → Strategy is failing

### 4. **What Causes Losses?**
```bash
./venv/bin/python3 view_backtest_history.py --losing-days
```

Find patterns:
- Losing days have avg move of 0.6%? → Skip days with >0.4% AM move
- Losing days avg 6 DTE? → Use 10+ DTE only
- Most losses on Mondays? → Don't trade Mondays

---

## 🔧 Customization

### Change Schedule

Edit this file:
```
~/Library/LaunchAgents/com.sunildeesu.weeklybacktest.plist
```

Change:
```xml
<key>Weekday</key>
<integer>5</integer>  <!-- 0=Sunday, 5=Friday, etc. -->
<key>Hour</key>
<integer>16</integer>  <!-- 4 PM (16:00) -->
```

Then reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.sunildeesu.weeklybacktest.plist
launchctl load ~/Library/LaunchAgents/com.sunildeesu.weeklybacktest.plist
```

### Change Backtest Window

Edit `weekly_backtest_runner.py`, line ~118:
```python
results = backtest.run_backtest(days_back=7)  # Change 7 to 14 for 2 weeks
```

---

## 🚨 Alerts & Monitoring

### Telegram Alerts

Every Friday at 4 PM (after market hours), you'll receive:
```
📊 Weekly Backtest Report

Period: 2025-12-29 to 2026-01-04

THIS WEEK:
Win Rate: 71.4%
Total P&L: ₹850.00
Avg P&L: ₹121.43

ALL TIME:
Win Rate: 68.2%
Total Trades: 38
Cumulative P&L: ₹4,250.00

⚠️ WARNING: Win rate below 60%!  (if applicable)
```

### Check Logs

If backtest fails:
```bash
tail -50 logs/weekly_backtest.log
tail -50 logs/weekly_backtest_error.log
```

---

## 📋 Weekly Workflow (After Setup)

### Friday Afternoon (Automatic)
- 4:00 PM: Backtest runs automatically (after market closes at 3:30 PM)
- 4:01 PM: You receive Telegram alert

### Friday Evening (Manual - 5 mins)
```bash
# 1. Review the weekly report
cat data/weekly_reports/weekly_backtest_2026-01-05.md

# 2. Check trends
./venv/bin/python3 view_backtest_history.py --trends

# 3. If win rate dropped, investigate
./venv/bin/python3 view_backtest_history.py --losing-days
```

### Monthly Review (Manual - 15 mins)
```bash
# After 4-8 weeks, do comprehensive analysis

# 1. Export data
./venv/bin/python3 view_backtest_history.py --export

# 2. Open in Excel/Google Sheets
open data/backtest_history_export.csv

# 3. Analyze patterns:
#    - Which days of week are profitable?
#    - What DTE works best?
#    - What NIFTY movement % causes losses?
#    - Is overall trend improving?

# 4. Adjust trading rules based on findings
```

---

## 🎯 Decision Making Framework

After 1 month (4-5 backtests):

| All-Time Win Rate | Decision |
|-------------------|----------|
| **>75%** | ✅ Strategy is excellent, trade confidently |
| **65-75%** | ✅ Strategy works, but be selective |
| **55-65%** | ⚠️ Marginal, needs improvement |
| **<55%** | ❌ Strategy failing, STOP trading |

After 3 months (12-15 backtests):

| Cumulative P&L | Annual Projection | Decision |
|----------------|-------------------|----------|
| **>₹15,000** | ~₹60K/year | ✅ Scale to 2-3 lots |
| **₹5K-15K** | ~₹20-60K/year | ✅ Keep 1 lot, monitor |
| **₹0-5K** | ~₹0-20K/year | ⚠️ Marginal, improve filters |
| **<₹0** | Losing money | ❌ STOP immediately |

---

## 🔍 Database Schema

### `backtest_trades` table:
```sql
- trade_date: Date of the trade
- day_of_week: Monday/Tuesday/etc.
- nifty_entry, nifty_exit: NIFTY prices
- nifty_move_pct: Percentage movement
- atm_strike: Strike used
- expiry, days_to_expiry: Expiry details
- ce_entry, pe_entry: Option premiums at entry
- ce_exit, pe_exit: Option premiums at exit
- net_pnl: Final P&L after costs
```

### `weekly_summaries` table:
```sql
- week_start, week_end: Week range
- total_trades, winning_trades, losing_trades
- win_rate: Percentage
- total_pnl, avg_pnl
- max_profit, max_loss
```

---

## 🛠️ Troubleshooting

### Backtest Not Running Automatically

**Check if loaded:**
```bash
launchctl list | grep weeklybacktest
```

**Check logs:**
```bash
tail -50 logs/weekly_backtest_error.log
```

**Common issues:**
1. Kite token expired → Refresh token
2. Virtual environment not found → Check paths in plist
3. Network error → Check internet connection

### No Data in Database

**Check if database exists:**
```bash
ls -lh data/backtest_history.db
```

**If missing, run manually:**
```bash
./venv/bin/python3 weekly_backtest_runner.py
```

### Telegram Alert Not Received

**Check config:**
```bash
grep TELEGRAM .env
```

Make sure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` are set.

---

## 📊 Sample Output After 2 Months

```
ALL-TIME BACKTEST STATISTICS
================================================================================

Period: 2025-12-01 to 2026-01-31

Total Trades: 42
Winning Trades: 29 (69.0%)
Losing Trades: 13 (31.0%)

Total P&L: ₹5,840.00
Average P&L: ₹139.05
Best Trade: ₹1,756.40
Worst Trade: ₹-2,800.80

--------------------------------------------------------------------------------
DAY OF WEEK BREAKDOWN
--------------------------------------------------------------------------------

Day          Trades   Win Rate     Avg P&L     Total P&L
--------------------------------------------------------------------------------
Monday       9        55.6%        ₹  78.20    ₹   704.00
Tuesday      8        75.0%        ₹ 285.50    ₹ 2,284.00
Wednesday    9        66.7%        ₹ 145.30    ₹ 1,308.00
Thursday     8        75.0%        ₹ 220.40    ₹ 1,763.00
Friday       8        62.5%        ₹ -26.12    ₹  -209.00
```

**Insights from above:**
- ✅ Overall win rate 69% → Strategy works
- ✅ Tuesday & Thursday are best days (75% win rate)
- ⚠️ Friday is breakeven/slightly negative → Skip Fridays
- ⚠️ Monday has lowest win rate → Trade smaller or skip

---

## 🚀 Next Steps After Setup

1. **Week 1:** Run manually to seed database
2. **Week 2-4:** Let it run automatically, monitor Telegram alerts
3. **Week 5:** First analysis using `--trends` and `--losing-days`
4. **Week 8:** Comprehensive review, adjust trading rules
5. **Week 12:** Decide if strategy is profitable long-term

---

## 💡 Pro Tips

1. **Don't trade based on 1-2 weeks data** → Need at least 4-6 weeks
2. **Pay attention to losing patterns** → They reveal what to avoid
3. **Win rate >70% is excellent** → Don't expect 100%
4. **One big loss can wipe out weeks** → Always use stop loss in real trading
5. **If all-time P&L goes negative** → STOP trading immediately

---

## 📞 Support

If you encounter issues:

1. Check logs: `logs/weekly_backtest.log`
2. Test manually: `./venv/bin/python3 weekly_backtest_runner.py`
3. View database: `./venv/bin/python3 view_backtest_history.py --all-time`
4. Export data: `./venv/bin/python3 view_backtest_history.py --export`

---

*Last Updated: January 3, 2026*
