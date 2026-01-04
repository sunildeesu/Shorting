# ATM Straddle 6-Month Backtest Analysis

**Backtest Date:** January 03, 2026
**Period:** 2025-07-07 to 2026-01-02
**Strategy:** Sell ATM Call + Put at 10:05 AM, Close at 3:10 PM (Next Week Expiry)
**Position Size:** 1 lot (50 qty)

---

## 📊 OVERALL PERFORMANCE

- **Total Trades:** 120
- **Winning Trades:** 120 (100.0%)
- **Losing Trades:** 0 (0.0%)
- **Total P&L:** ₹76,983.07
- **Average P&L per Trade:** ₹641.53
- **Best Trade:** ₹1,260.71
- **Worst Trade:** ₹278.24
- **Maximum Drawdown:** ₹0.00

### Verdict: 🟢 **PROFITABLE STRATEGY** - Good win rate and positive returns

---

## 📅 DAY OF WEEK ANALYSIS

Which days are most profitable for straddle selling?

| Day | Trades | Total P&L | Avg P&L | Win Rate |
|-----|--------|-----------|---------|----------|
| Monday    |     25 | ₹15,253.87 | ₹610.15 | 100.0% |
| Tuesday   |     25 | ₹19,244.44 | ₹769.78 | 100.0% |
| Wednesday |     23 | ₹25,555.43 | ₹1111.11 | 100.0% |
| Thursday  |     23 | ₹7,791.40 | ₹338.76 | 100.0% |
| Friday    |     24 | ₹9,137.93 | ₹380.75 | 100.0% |

---

## 📈 VIX LEVEL ANALYSIS

How does VIX affect profitability?

| VIX Level | Trades | Total P&L | Avg P&L |
|-----------|--------|-----------|---------|------|
| Low (<12)     |     96 | ₹60,889.30 | ₹634.26 |
| Medium (12-15) |     24 | ₹16,093.77 | ₹670.57 |
| High (15-20)  |      0 | ₹    0.00 | ₹   nan |
| Very High (>20) |      0 | ₹    0.00 | ₹   nan |

---

## 🎯 NIFTY MOVEMENT ANALYSIS

How does NIFTY movement affect straddle P&L?

| Movement | Trades | Total P&L | Avg P&L |
|----------|--------|-----------|---------|------|
| Tiny (<0.5%) |     97 | ₹63,086.90 | ₹650.38 |
| Small (0.5-1%) |     21 | ₹12,174.89 | ₹579.76 |
| Medium (1-1.5%) |      0 | ₹    0.00 | ₹   nan |
| Large (>1.5%) |      0 | ₹    0.00 | ₹   nan |

**Key Insight:** Straddles profit most when NIFTY movement is minimal (time decay > directional move)

---

## 🏆 BEST & WORST TRADES

### Top 5 Most Profitable Days

1. **2025-11-12 (Wednesday)** - ₹1,260.71
   - NIFTY Move: +0.09%, VIX: 12.11
   - Entry Straddle: ₹131.07, Exit: ₹103.76

2. **2025-11-26 (Wednesday)** - ₹1,254.55
   - NIFTY Move: +0.45%, VIX: 11.97
   - Entry Straddle: ₹130.76, Exit: ₹103.57

3. **2025-10-29 (Wednesday)** - ₹1,251.27
   - NIFTY Move: +0.23%, VIX: 11.97
   - Entry Straddle: ₹130.30, Exit: ₹103.18

4. **2025-11-19 (Wednesday)** - ₹1,246.05
   - NIFTY Move: +0.49%, VIX: 11.97
   - Entry Straddle: ₹129.95, Exit: ₹102.94

5. **2025-07-09 (Wednesday)** - ₹1,223.12
   - NIFTY Move: -0.14%, VIX: 11.94
   - Entry Straddle: ₹127.52, Exit: ₹100.97

### Top 5 Worst Days

1. **2025-09-11 (Thursday)** - ₹305.52
   - NIFTY Move: +0.15%, VIX: 10.36
   - Entry Straddle: ₹286.55, Exit: ₹278.08

2. **2025-09-18 (Thursday)** - ₹296.83
   - NIFTY Move: +0.08%, VIX: 9.89
   - Entry Straddle: ₹278.46, Exit: ₹270.18

3. **2025-10-09 (Thursday)** - ₹291.19
   - NIFTY Move: +0.53%, VIX: 10.12
   - Entry Straddle: ₹280.91, Exit: ₹272.73

4. **2025-12-18 (Thursday)** - ₹289.97
   - NIFTY Move: +0.28%, VIX: 9.71
   - Entry Straddle: ₹276.96, Exit: ₹268.81

5. **2026-01-01 (Thursday)** - ₹278.24
   - NIFTY Move: -0.11%, VIX: 9.19
   - Entry Straddle: ₹266.46, Exit: ₹258.57

---

## 💡 KEY INSIGHTS & RECOMMENDATIONS

✅ **Excellent win rate** (>70%) - Strategy has strong edge

✅ **Strong average profit** (>₹500/trade) - Good risk-reward

📅 **Best day:** Wednesday, **Worst day:** Thursday

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

*Backtest generated on 2026-01-03 14:35:13*
