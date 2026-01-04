# REAL Option Data Backtest - Actual Kite Historical Prices

**Backtest Date:** January 03, 2026
**Data Source:** Kite Connect Historical API (REAL option prices)
**Period:** 2025-12-22 to 2026-01-02
**Strategy:** Sell ATM Call + Put at 10:05 AM, Close at 3:10 PM
**Expiry:** Next week only (6-10 DTE)
**Position Size:** 1 lot (50 qty)

---

## 🎯 CRITICAL DIFFERENCE: REAL vs ESTIMATED

This backtest uses **ACTUAL historical option premiums** from Kite Connect.
Previous backtests used Black-Scholes estimates which showed 100% win rate.
This shows **REALITY** - what would have ACTUALLY happened!

---

## 📊 OVERALL PERFORMANCE (REAL DATA)

- **Total Trades:** 9
- **Winning Trades:** 6 (66.7%)
- **Losing Trades:** 3 (33.3%)
- **Total P&L:** ₹1,240.05
- **Average P&L per Trade:** ₹137.78
- **Best Trade:** ₹1,756.40
- **Worst Trade:** ₹-2,800.80

### Verdict: 🟡 **MARGINALLY PROFITABLE** (Real data shows lower win rate)

---

## 📅 DAY OF WEEK ANALYSIS (REAL DATA)

| Day | Trades | Total P&L | Avg P&L |
|-----|--------|-----------|----------|
| Monday    |      2 | ₹ -231.66 | ₹-115.83 |
| Tuesday   |      2 | ₹1,848.72 | ₹924.36 |
| Wednesday |      2 | ₹-1,044.40 | ₹-522.20 |
| Thursday  |      1 | ₹  770.80 | ₹770.80 |
| Friday    |      2 | ₹ -103.41 | ₹-51.70 |

---

## 📋 ALL TRADES (REAL DATA)


### 2025-12-22 (Monday)
**✅ P&L: ₹36.06**

- NIFTY: 26139.25 → 26162.75 (+0.09%)
- Strike: 26150 (15 DTE, expires 2026-01-06)
- Entry: CE ₹231.95 + PE ₹150.65 = ₹382.60
- Exit:  CE ₹238.70 + PE ₹140.65 = ₹379.35
- Options: NIFTY2610626150CE, NIFTY2610626150PE

### 2025-12-23 (Tuesday)
**✅ P&L: ₹815.73**

- NIFTY: 26181.65 → 26165.95 (-0.06%)
- Strike: 26200 (14 DTE, expires 2026-01-06)
- Entry: CE ₹221.50 + PE ₹140.75 = ₹362.25
- Exit:  CE ₹205.90 + PE ₹137.55 = ₹343.45
- Options: NIFTY2610626200CE, NIFTY2610626200PE

### 2025-12-24 (Wednesday)
**✅ P&L: ₹1756.40**

- NIFTY: 26209.70 → 26141.65 (-0.26%)
- Strike: 26200 (13 DTE, expires 2026-01-06)
- Entry: CE ₹214.00 + PE ₹117.10 = ₹331.10
- Exit:  CE ₹161.20 + PE ₹132.35 = ₹293.55
- Options: NIFTY2610626200CE, NIFTY2610626200PE

### 2025-12-26 (Friday)
**✅ P&L: ₹475.10**

- NIFTY: 26094.85 → 26047.65 (-0.18%)
- Strike: 26100 (11 DTE, expires 2026-01-06)
- Entry: CE ₹161.15 + PE ₹116.85 = ₹278.00
- Exit:  CE ₹138.85 + PE ₹127.30 = ₹266.15
- Options: NIFTY2610626100CE, NIFTY2610626100PE

### 2025-12-29 (Monday)
**❌ P&L: ₹-267.72**

- NIFTY: 26031.50 → 25949.80 (-0.31%)
- Strike: 26050 (8 DTE, expires 2026-01-06)
- Entry: CE ₹140.60 + PE ₹106.15 = ₹246.75
- Exit:  CE ₹101.15 + PE ₹148.65 = ₹249.80
- Options: NIFTY2610626050CE, NIFTY2610626050PE

### 2025-12-30 (Tuesday)
**✅ P&L: ₹1032.99**

- NIFTY: 25932.35 → 25970.55 (+0.15%)
- Strike: 25950 (7 DTE, expires 2026-01-06)
- Entry: CE ₹142.45 + PE ₹105.05 = ₹247.50
- Exit:  CE ₹135.50 + PE ₹89.05 = ₹224.55
- Options: NIFTY2610625950CE, NIFTY2610625950PE

### 2025-12-31 (Wednesday)
**❌ P&L: ₹-2800.80**

- NIFTY: 25977.60 → 26141.85 (+0.63%)
- Strike: 26000 (6 DTE, expires 2026-01-06)
- Entry: CE ₹117.50 + PE ₹88.65 = ₹206.15
- Exit:  CE ₹220.00 + PE ₹39.90 = ₹259.90
- Options: NIFTY2610626000CE, NIFTY2610626000PE

### 2026-01-01 (Thursday)
**✅ P&L: ₹770.80**

- NIFTY: 26171.70 → 26140.25 (-0.12%)
- Strike: 26150 (12 DTE, expires 2026-01-13)
- Entry: CE ₹189.90 + PE ₹111.60 = ₹301.50
- Exit:  CE ₹174.15 + PE ₹109.55 = ₹283.70
- Options: NIFTY2611326150CE, NIFTY2611326150PE

### 2026-01-02 (Friday)
**❌ P&L: ₹-578.51**

- NIFTY: 26251.95 → 26335.70 (+0.32%)
- Strike: 26250 (11 DTE, expires 2026-01-13)
- Entry: CE ₹176.55 + PE ₹107.20 = ₹283.75
- Exit:  CE ₹205.45 + PE ₹87.50 = ₹292.95
- Options: NIFTY2611326250CE, NIFTY2611326250PE

---

*Report generated with REAL historical option data from Kite Connect*
