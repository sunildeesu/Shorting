# ATM Straddle 6-Month Backtest Analysis (NEXT WEEK EXPIRY ONLY)

**Backtest Date:** January 03, 2026
**Period:** 2025-07-07 to 2026-01-02
**Strategy:** Sell ATM Call + Put at 10:05 AM, Close at 3:10 PM (Next Week Expiry ONLY)
**Expiry Policy:** ALWAYS next week Thursday (6-10 DTE), NEVER current week (avoids 1-3 DTE gamma risk)
**Position Size:** 1 lot (50 qty)

---

## 📊 OVERALL PERFORMANCE

- **Total Trades:** 116
- **Winning Trades:** 116 (100.0%)
- **Losing Trades:** 0 (0.0%)
- **Total P&L:** ₹36,588.07
- **Average P&L per Trade:** ₹315.41
- **Best Trade:** ₹506.14
- **Worst Trade:** ₹217.89
- **Maximum Drawdown:** ₹0.00

### Verdict: 🟢 **PROFITABLE STRATEGY** - Good win rate and positive returns

---

## 📅 DAY OF WEEK ANALYSIS

Which days are most profitable for straddle selling?

| Day | Trades | Total P&L | Avg P&L | Win Rate |
|-----|--------|-----------|---------|----------|
| Monday    |     22 | ₹5,800.93 | ₹263.68 | 100.0% |
| Tuesday   |     24 | ₹6,872.69 | ₹286.36 | 100.0% |
| Wednesday |     23 | ₹6,957.97 | ₹302.52 | 100.0% |
| Thursday  |     22 | ₹7,485.88 | ₹340.27 | 100.0% |
| Friday    |     25 | ₹9,470.60 | ₹378.82 | 100.0% |

---

## 📈 VIX LEVEL ANALYSIS

How does VIX affect profitability?

| VIX Level | Trades | Total P&L | Avg P&L |
|-----------|--------|-----------|---------|------|
| Low (<12)     |     93 | ₹28,508.24 | ₹306.54 |
| Medium (12-15) |     23 | ₹8,079.83 | ₹351.30 |
| High (15-20)  |      0 | ₹    0.00 | ₹   nan |
| Very High (>20) |      0 | ₹    0.00 | ₹   nan |

---

## 🎯 NIFTY MOVEMENT ANALYSIS

How does NIFTY movement affect straddle P&L?

| Movement | Trades | Total P&L | Avg P&L |
|----------|--------|-----------|---------|------|
| Tiny (<0.5%) |     94 | ₹29,433.58 | ₹313.12 |
| Small (0.5-1%) |     20 | ₹6,562.81 | ₹328.14 |
| Medium (1-1.5%) |      0 | ₹    0.00 | ₹   nan |
| Large (>1.5%) |      0 | ₹    0.00 | ₹   nan |

**Key Insight:** Straddles profit most when NIFTY movement is minimal (time decay > directional move)

---

## 🏆 BEST & WORST TRADES

### Top 5 Most Profitable Days

1. **2025-11-21 (Friday)** - ₹506.14
   - NIFTY Move: -0.11%, VIX: 13.63
   - Entry Straddle: ₹364.80, Exit: ₹352.19

2. **2025-11-07 (Friday)** - ₹432.96
   - NIFTY Move: +0.63%, VIX: 12.56
   - Entry Straddle: ₹326.47, Exit: ₹315.38

3. **2025-10-31 (Friday)** - ₹425.72
   - NIFTY Move: -0.68%, VIX: 12.15
   - Entry Straddle: ₹322.64, Exit: ₹311.70

4. **2025-11-28 (Friday)** - ₹418.76
   - NIFTY Move: -0.22%, VIX: 11.62
   - Entry Straddle: ₹312.95, Exit: ₹302.17

5. **2025-11-14 (Friday)** - ₹416.82
   - NIFTY Move: +0.56%, VIX: 11.94
   - Entry Straddle: ₹315.66, Exit: ₹304.91

### Top 5 Worst Days

1. **2025-09-15 (Monday)** - ₹236.70
   - NIFTY Move: -0.10%, VIX: 10.40
   - Entry Straddle: ₹345.52, Exit: ₹338.32

2. **2025-09-22 (Monday)** - ₹234.63
   - NIFTY Move: -0.47%, VIX: 10.56
   - Entry Straddle: ₹354.09, Exit: ₹346.91

3. **2025-12-22 (Monday)** - ₹224.39
   - NIFTY Move: +0.11%, VIX: 9.68
   - Entry Straddle: ₹335.05, Exit: ₹328.12

4. **2025-12-29 (Monday)** - ₹219.55
   - NIFTY Move: -0.35%, VIX: 9.72
   - Entry Straddle: ₹335.05, Exit: ₹328.21

5. **2025-10-06 (Monday)** - ₹217.89
   - NIFTY Move: +0.50%, VIX: 10.19
   - Entry Straddle: ₹336.73, Exit: ₹329.93

---

## 💡 KEY INSIGHTS & RECOMMENDATIONS

✅ **Excellent win rate** (>70%) - Strategy has strong edge

⚠️ **Marginal average profit** - Risk-reward needs improvement

📅 **Best day:** Friday, **Worst day:** Monday

📉 **Lower VIX = Better profits** - Careful with high VIX days

⚠️ **Big moves hurt straddles** - Avoid days with large expected movement

---

## 🤖 HOW THIS HELPS YOUR INDICATOR

Use these insights to improve your option selling indicator:

1. **Focus on high-probability days** - Use backtest data to identify ideal selling conditions
2. **Avoid unfavorable patterns** - Skip days with characteristics that historically lose money
3. **Optimize position sizing** - Larger positions on best setups, smaller on marginal days
4. **Validate indicator signals** - Cross-reference with historical performance patterns

---

*Backtest generated on 2026-01-03 15:05:12*
