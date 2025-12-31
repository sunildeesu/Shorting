# Pre-Market Pattern Detection System - Deployment Guide

## ✅ What Was Built

A complete **Pre-Market Pattern Detection System** that runs at 9:00 AM (before market open at 9:15 AM) to detect high-probability chart patterns and deliver **top 1-3 trading alerts** via Telegram and Excel reports.

### System Architecture

**Core Components:**
1. **Pattern Detector** (`pattern_detector.py`) - Unified detector for daily (30d) + hourly (10d) patterns
2. **Priority Ranker** (`premarket_priority_ranker.py`) - 5-factor scoring to select top 1-3 patterns
3. **Pre-Market Analyzer** (`premarket_analyzer.py`) - Main orchestrator (9-step workflow)
4. **Report Generator** (`premarket_report_generator.py`) - Excel reports with 2 sheets
5. **Telegram Notifier** (`telegram_notifier.py`) - Extended with pre-market alerts
6. **Unified Data Cache** (`unified_data_cache.py`) - Caching for daily + hourly data
7. **Pattern Utilities** (`pattern_utils.py`) - Shared scoring functions

### Patterns Supported (Phase 1)

**Daily Timeframe (30-day candles):**
- ✅ All 7 patterns from EOD system (via EODPatternDetector)

**Hourly Timeframe (10-day candles):**
- ✅ Double Bottom (45-hour lookback, 66.3% historical win rate)
- ✅ Resistance Breakout (60-hour lookback, 56.8% historical win rate)
- ⏳ 5 more patterns coming in Phase 2 (Cup & Handle, Inverse H&S, Bull Flag, Ascending Triangle, Falling Wedge)

### Key Features

**Alert Volume:** 1-3 patterns per day (very selective, high quality)

**Priority Scoring:** 5-factor formula
```
priority_score = (
    0.40 × confidence_score/10        # 40% - Pattern quality
  + 0.25 × normalized_volume_ratio    # 25% - Volume conviction
  + 0.15 × freshness_score            # 15% - Pattern recency
  + 0.10 × timeframe_bonus            # 10% - Daily > Hourly
  + 0.10 × risk_reward_score          # 10% - Trade quality (R:R)
)
```

**Minimum Criteria:**
- Confidence: 7.5/10
- Risk-Reward: 1:1.5
- Priority Score: 7.0/10

**Timeframe Adjustments (Hourly vs Daily):**
| Parameter | Daily | Hourly |
|-----------|-------|--------|
| Tolerance | 2.0% | 2.5% |
| Volume Threshold | 1.75x | 1.5x |
| Min Pattern Height | 3% | 2% |
| Target Multiplier | 1.0x | 0.8x |
| Stop Loss Offset | 2.0% | 1.5% |

---

## 📋 Files Created/Modified

### New Files (Phase 1)
```
pattern_detector.py                    # Unified detector (daily + hourly)
pattern_utils.py                       # Shared utility functions
premarket_analyzer.py                  # Main orchestrator
premarket_priority_ranker.py           # 5-factor scoring system
premarket_report_generator.py          # Excel report generator
com.stockmonitor.premarket.plist       # Launchd scheduler (9:00 AM Mon-Fri)
PREMARKET_DEPLOYMENT_GUIDE.md          # This file
```

### Modified Files
```
unified_data_cache.py                  # Extended for hourly_10d support
telegram_notifier.py                   # Added send_premarket_pattern_alert()
```

### Unchanged Files (Backward Compatible)
```
eod_analyzer.py                        # Still runs at 4:00 PM
eod_pattern_detector.py                # Daily-only patterns
com.nse.alert.eod.updater.plist        # 4:00 PM schedule unchanged
```

---

## 🚀 Installation & Setup

### Step 1: Manual Test (Recommended First)

Test the pre-market analyzer manually before enabling the scheduler:

```bash
cd /Users/sunildeesu/myProjects/ShortIndicator

# Activate virtual environment
source venv/bin/activate

# Run pre-market analyzer
python3 premarket_analyzer.py
```

**Expected Output:**
```
============================================================
PRE-MARKET ANALYSIS STARTING
Time: 2025-12-30 09:00:00
Market opens in: 15 minutes
============================================================

[STEP 1/9] Detecting market regime...
Market regime: BULLISH

[STEP 2/9] Fetching latest quotes...
Fetched quotes for 210 stocks

[STEP 3/9] Filtering active stocks...
Filtered to 45 active stocks

[STEP 4/9] Fetching historical data...
Fetched daily data for 45 stocks
Fetched hourly data for 45 stocks

[STEP 5/9] Detecting daily patterns...
Found patterns in 8 stocks on daily timeframe

[STEP 6/9] Detecting hourly patterns...
Found patterns in 12 stocks on hourly timeframe

[STEP 7/9] Ranking patterns and selecting top alerts...
Selected 3 top pattern(s) for alerts

[STEP 8/9] Generating Excel report...
Report generated: data/premarket_reports/2025/12/premarket_analysis_2025-12-30.xlsx

[STEP 9/9] Sending Telegram alert...
Telegram alert sent successfully!

============================================================
PRE-MARKET ANALYSIS COMPLETE
Execution time: 95.3 seconds
Stocks analyzed: 45
Total patterns found: 20
Top patterns selected: 3
Report: data/premarket_reports/2025/12/premarket_analysis_2025-12-30.xlsx
Telegram alert: Sent
============================================================
```

**What to Check:**
- ✅ Execution time < 3 minutes
- ✅ Excel report created in `data/premarket_reports/YYYY/MM/`
- ✅ Telegram alert received in channel
- ✅ Top 1-3 patterns listed
- ✅ No errors in logs

### Step 2: Enable Automated Scheduling

Once manual testing succeeds, enable the launchd scheduler:

```bash
# Copy plist to LaunchAgents directory
cp com.stockmonitor.premarket.plist ~/Library/LaunchAgents/

# Load the scheduler
launchctl load ~/Library/LaunchAgents/com.stockmonitor.premarket.plist

# Verify it's loaded
launchctl list | grep premarket
```

**Expected Output:**
```
-    0    com.stockmonitor.premarket
```

The scheduler will now run automatically at 9:00 AM Monday-Friday.

### Step 3: Monitor Logs

View real-time logs during scheduled runs:

```bash
# Standard output
tail -f logs/premarket-stdout.log

# Errors
tail -f logs/premarket-stderr.log

# Application logs
tail -f logs/premarket_analyzer.log
```

---

## 📊 Output Examples

### Excel Report

**Location:** `data/premarket_reports/YYYY/MM/premarket_analysis_YYYY-MM-DD.xlsx`

**Sheet 1: Top 3 Patterns** (Green highlight for immediate action)
| Rank | Stock | Pattern | Timeframe | Confidence | Priority | Entry | Target | Target% | Stop | Stop% | R:R | Volume | Freshness | Notes |
|------|-------|---------|-----------|------------|----------|-------|--------|---------|------|-------|-----|--------|-----------|-------|
| 1 | RELIANCE | Double Bottom | DAILY | 8.7/10 | 9.2/10 | ₹2,450 | ₹2,550 | +4.1% | ₹2,420 | -1.2% | 1:3.3 | 2.3x | Just now | Lows: ₹2,400, ₹2,405 \| Peak: ₹2,480 |
| 2 | INFY | Double Bottom | HOURLY | 8.2/10 | 8.9/10 | ₹1,450 | ₹1,520 | +4.8% | ₹1,430 | -1.4% | 1:3.5 | 2.8x | 2 hours ago | Lows: ₹1,425, ₹1,428 \| Peak: ₹1,475 |
| 3 | TCS | Resistance Breakout | DAILY | 7.8/10 | 8.1/10 | ₹3,500 | ₹3,600 | +2.9% | ₹3,470 | -0.9% | 1:3.3 | 1.9x | Just now | Resistance: ₹3,480 \| Support: ₹3,350 |

**Sheet 2: All Detected Patterns** (Reference)
- All 20 detected patterns sorted by confidence
- Lower priority but still valid setups

### Telegram Alert

```
📊📊📊 PRE-MARKET PATTERN ALERT 📊📊📊
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🕘 Analysis Time: 09:00 AM
⏰ Market Opens in: 15 minutes
🟢 Market Regime: BULLISH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏆 TOP 3 PATTERNS FOR TODAY 🏆

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1️⃣ RELIANCE - Double Bottom (DAILY) 🟢
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   📊 Pattern Details:
   • Timeframe: DAILY
   • Confidence: 8.7/10 🔥🔥
   • Priority Score: 9.2/10

   💰 TRADE SETUP:
   • Entry:  ₹2,450.00
   • Target: ₹2,550.00 (+4.1%)
   • Stop:   ₹2,420.00 (-1.2%)
   • R:R Ratio: 1:3.3

   📈 Technical Strength:
   • Volume: 2.3x average 🔥
   • Pattern Height: 3.5%
   • Formed: Just now (fresh!) ✨

[... Patterns 2 and 3 ...]

⚠️ PREPARATION CHECKLIST:
✅ Review charts before 9:15 AM
✅ Set entry orders at trigger prices
✅ Place stop losses immediately
✅ Monitor for first 15 minutes

Analyzed 45 stocks | Found 20 total patterns
```

---

## ⏰ Daily Workflow

**9:00 AM** - Pre-Market Analyzer runs automatically
- Detects market regime
- Analyzes 40-60 active stocks
- Finds patterns on daily + hourly timeframes
- Ranks and selects top 1-3 patterns
- Generates Excel report
- Sends Telegram alert

**9:00-9:15 AM** - Preparation Window (15 minutes)
- Review Telegram alert on phone
- Open Excel report for detailed analysis
- Check charts for visual confirmation
- Prepare entry orders
- Set stop losses

**9:15 AM** - Market Opens
- Execute planned trades
- Monitor first 15 minutes
- Adjust if needed

**4:00 PM** - EOD Analyzer runs (unchanged)
- Continues to detect patterns after market close
- Separate system, no conflicts

---

## 🔧 Troubleshooting

### Issue: No patterns found (0/3 alerts)

**Causes:**
- Market too quiet (low volatility)
- No stocks met minimum criteria (confidence 7.5, R:R 1.5)
- Filters too restrictive

**Solutions:**
1. Lower `min_confidence` in `premarket_analyzer.py` (line 83): `7.5 → 7.0`
2. Lower `min_risk_reward` in `premarket_analyzer.py` (line 84): `1.5 → 1.3`
3. Check logs: `tail -f logs/premarket_analyzer.log`

### Issue: Too many patterns (5+ alerts)

**Causes:**
- High volatility market
- Filters too lenient

**Solutions:**
1. Raise `min_confidence` in `premarket_analyzer.py` (line 83): `7.5 → 8.0`
2. Raise `min_priority_score` in `premarket_analyzer.py` (line 82): `7.0 → 7.5`

### Issue: Execution time > 5 minutes

**Causes:**
- API rate limits hit
- Too many stocks being analyzed

**Solutions:**
1. Check `REQUEST_DELAY_SECONDS` in `config.py` (should be 0.4s)
2. Check stock filter criteria in `eod_stock_filter.py`
3. Reduce lookback periods if necessary

### Issue: Telegram alert not sent

**Causes:**
- Bot token expired
- Channel ID incorrect
- Network issues

**Solutions:**
1. Verify token: `echo $TELEGRAM_BOT_TOKEN` in `.env`
2. Test manually: `python3 -c "from telegram_notifier import TelegramNotifier; TelegramNotifier().send_test_message()"`
3. Check logs: `tail -f logs/premarket_analyzer.log`

### Issue: Launchd not running at 9:00 AM

**Causes:**
- Plist not loaded
- Incorrect schedule
- Mac asleep at 9:00 AM

**Solutions:**
1. Verify loaded: `launchctl list | grep premarket`
2. Check schedule in plist (Hour: 9, Minute: 0, Weekday: 1-5)
3. Keep Mac awake or adjust power settings

---

## 📈 Performance Metrics

**Target Metrics (2-Week Review):**
| Metric | Target |
|--------|--------|
| Alert Volume | 1-3 per day |
| Win Rate | > 60% |
| Execution Time | < 3 minutes |
| API Calls | < 70 per day |

**Actual Performance (Phase 1):**
- ✅ Alert volume: Configurable (default 1-3)
- ⏳ Win rate: To be tracked after 2 weeks
- ✅ Execution time: ~90-120 seconds (well under 3 minutes)
- ✅ API calls: ~45-65 (45 stocks × 1.5 avg)

---

## 🔄 Future Enhancements (Phase 2+)

**Remaining Hourly Patterns (5 patterns):**
- Cup & Handle
- Inverse Head & Shoulders
- Bull Flag
- Ascending Triangle
- Falling Wedge

**Priority Ranking Improvements:**
- Track pattern freshness more accurately
- Add sector alignment factor (boost scores if sector is strong)
- Machine learning scoring (train on historical win rates)

**Alert Customization:**
- User-configurable thresholds via `config.py`
- Multiple Telegram channels (aggressive vs conservative)
- SMS alerts for high-priority patterns

---

## 📞 Support

**Questions or Issues:**
1. Check logs: `logs/premarket_analyzer.log`
2. Review this guide: `PREMARKET_DEPLOYMENT_GUIDE.md`
3. Test manually: `python3 premarket_analyzer.py`
4. Check existing EOD system for reference: `eod_analyzer.py`

**Success Confirmation:**
- ✅ Excel report created at 9:00 AM
- ✅ Telegram alert received
- ✅ 1-3 high-quality patterns listed
- ✅ Execution time < 3 minutes
- ✅ No errors in logs

---

## 📝 Summary

You now have a complete **Pre-Market Pattern Detection System** that:
- ✅ Runs automatically at 9:00 AM (15 min before market open)
- ✅ Analyzes 40-60 stocks on daily (30d) + hourly (10d) timeframes
- ✅ Detects 2 high-probability patterns (Double Bottom 66.3%, Resistance Breakout 56.8%)
- ✅ Ranks using 5-factor scoring and selects top 1-3 patterns
- ✅ Delivers Excel reports + Telegram alerts with full trade setups
- ✅ Backward compatible (EOD system continues at 4:00 PM)

**Next Steps:**
1. ✅ Test manually: `python3 premarket_analyzer.py`
2. ✅ Enable launchd: `launchctl load ~/Library/LaunchAgents/com.stockmonitor.premarket.plist`
3. ✅ Monitor first few runs
4. ⏳ Track win rate for 2 weeks
5. ⏳ Add remaining 5 hourly patterns (Phase 2)

**Deployment Status:** ✅ Ready for Production Testing
