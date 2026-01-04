# Telegram Alert Color Coding & Visual Styling Guide

All Telegram alerts now use a **consistent color-coded badge system** plus **unique formatting styles** for instant visual recognition of alert types.

---

## 🎨 Visual Differentiation System

Each alert type has **TWO levels of visual differentiation**:

1. **🎨 Color Badges** - Colored circles indicating alert category
2. **✨ Unique Formatting** - Different separators, bold/italic combinations, monospace text

---

## 🎨 Color Scheme

### 🔴 RED - Critical/Urgent Alerts
**Action Required: IMMEDIATELY**

| Alert Type | Example | When You'll See It |
|------------|---------|-------------------|
| Volume Spike Drops | 🔴🔴🔴 PRIORITY ALERT | Stock dropping with unusual volume |
| Rapid 5-Min Drops | 🔴🔴 ALERT: Rapid 5-Min Drop! | Fast price decline |
| 30-Min Drops | 🔴 ALERT: Gradual 30-Min Drop! | Slower price decline |
| 1-Min Ultra-Fast Drops | 🔴🔴🔴 1-MIN ULTRA-FAST ALERT | Very rapid drops (1-min window) |
| **NIFTY Exit Signals** | 🔴🔴🔴 EXIT POSITION NOW | High urgency exit (critical risk) |
| | 🔴🔴 EXIT POSITION NOW | Moderate urgency exit |
| **NIFTY AVOID Signal** | 🔴🔴🔴 NIFTY OPTION SELLING SIGNAL | Don't trade - conditions unfavorable |

**What to do:** Take immediate action - review position, consider exiting, or avoid entry

---

### 🟢 GREEN - Good/Trade Signals
**Action: OPPORTUNITY TO TRADE**

| Alert Type | Example | When You'll See It |
|------------|---------|-------------------|
| Volume Spike Rises | 🟢🟢🟢 PRIORITY ALERT | Stock rising with unusual volume |
| Rapid 5-Min Rises | 🟢🟢 ALERT: Rapid 5-Min Rise! | Fast price increase |
| 30-Min Rises | 🟢 ALERT: Gradual 30-Min Rise! | Slower price increase |
| 1-Min Ultra-Fast Rises | 🟢🟢🟢 1-MIN ULTRA-FAST ALERT | Very rapid rises (1-min window) |
| **NIFTY SELL Signals** | 🟢🟢🟢 NIFTY OPTION SELLING SIGNAL | SELL_STRONG (best opportunity) |
| | 🟢🟢 NIFTY OPTION SELLING SIGNAL | SELL_MODERATE (good opportunity) |
| **NIFTY Add Position** | 🟢🟢 ADD TO POSITION - Layer 2 | Conditions improved - add more |
| | 🟢🟢 LATE ENTRY OPPORTUNITY | Entry signal after market opens |

**What to do:** Consider taking trades, add positions, or monitor for entry

---

### 🟠 ORANGE - Warning/Caution
**Action: MONITOR CLOSELY**

| Alert Type | Example | When You'll See It |
|------------|---------|-------------------|
| **NIFTY SELL_WEAK Signal** | 🟠🟠 NIFTY OPTION SELLING SIGNAL | Low IV Rank - weak signal |
| **NIFTY Consider Exit** | 🟠🟠 CONSIDER EXIT | Warning signs detected |

**What to do:** Be cautious, monitor position closely, prepare to act if conditions worsen

---

### 🟡 YELLOW - Hold/Neutral
**Action: MAINTAIN STATUS QUO**

| Alert Type | Example | When You'll See It |
|------------|---------|-------------------|
| **NIFTY HOLD Signal** | 🟡🟡 NIFTY OPTION SELLING SIGNAL | Conditions neutral - wait |

**What to do:** Hold current position or wait for better conditions

---

### 🔵 BLUE - Informational/Analysis
**Action: REVIEW & LEARN**

| Alert Type | Example | When You'll See It |
|------------|---------|-------------------|
| **EOD Sector Summary** | 🔵🔵🔵 EOD SECTOR SUMMARY | End-of-day sector performance (3:30 PM) |
| **EOD Pattern Detection** | 🔵🔵🔵 EOD PATTERN DETECTION | Daily chart patterns found (3:30 PM) |
| **NIFTY EOD Summary** | 🔵🔵 END OF DAY SUMMARY | Daily position summary (after market) |
| | 🔵🔵 POSITION ACTIVE | Your current position status |
| | 🔵🔵 POSITION EXITED | Position closed today |

**What to do:** Review for learning, no immediate action needed

---

### 🟣 PURPLE - Pre-Market/Planning
**Action: PREPARE FOR NEXT DAY**

| Alert Type | Example | When You'll See It |
|------------|---------|-------------------|
| **Pre-Market Patterns** | 🟣🟣🟣 PRE-MARKET PATTERN ALERT | Chart patterns before market open (8-9 AM) |
| **Sector Rotation** | 🟣🟣🟣 SECTOR ROTATION DETECTED | Fund flows between sectors |
| **Weekly Backtest Report** | 🟣🟣🟣 WEEKLY BACKTEST REPORT | Every Friday 4 PM - strategy performance |

**What to do:** Plan ahead, prepare watchlist, review strategy performance

---

## ✨ Unique Formatting Styles by Alert Type

Each alert category uses a distinctive visual style that you can recognize at a glance:

### 📊 NIFTY Option Selling Alerts
```
🟢🟢🟢 NIFTY OPTION SELLING SIGNAL 🟢🟢🟢
═══════════════════════════════════════
(Double-line separators + Bold + Italic headers)
```
**Style Features:**
- Header: Bold + Italic (`<b><i>`)
- Separators: Double lines (`═══`)
- Used for: All NIFTY option signals, ADD POSITION, EXIT NOW

---

### 🔄 Sector & Market Alerts
```
🟣🟣🟣 SECTOR ROTATION DETECTED 🟣🟣🟣
▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔
(Top bar separators + Bold + Underline headers)
```
**Style Features:**
- Header: Bold + Underline (`<b><u>`)
- Separators: Top bars (`▔▔▔`)
- Used for: Sector rotation, Pre-market patterns, Weekly backtests

---

### 📊 EOD Analysis Alerts
```
🔵🔵🔵 EOD PATTERN DETECTION 🔵🔵🔵
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
(Dotted separators + Bold + Monospace headers)
```
**Style Features:**
- Header: Bold + Monospace (`<b><code>`)
- Separators: Dotted lines (`┄┄┄`)
- Used for: EOD patterns, EOD sector summary, EOD position summaries

---

### ⚡ Ultra-Fast Alerts
```
🔴🔴🔴 ⚡ 1-MIN ULTRA-FAST ALERT ⚡ 🔴🔴🔴
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
(Solid thick bars + Bold + Italic + Lightning emoji)
```
**Style Features:**
- Header: Bold + Italic with ⚡ emoji (`<b><i>⚡`)
- Separators: Solid thick bars (`▬▬▬`)
- Used for: 1-minute ultra-fast stock alerts

---

### 📈 Regular Stock Alerts
```
🔴🔴🔴 PRIORITY ALERT 🔴🔴🔴
━━━━━━━━━━━━━━━━━━━━━━━━━━
(Standard dashed lines + Bold headers)
```
**Style Features:**
- Header: Bold (`<b>`)
- Separators: Standard dashes (`━━━`)
- Used for: 5-min, 30-min volume spike alerts

---

## 📱 Quick Reference Chart

```
URGENCY LEVEL         COLOR        WHAT TO DO
═══════════════════════════════════════════════════════════
🔴🔴🔴 CRITICAL       RED          ACT IMMEDIATELY
🔴🔴   HIGH           RED          ACT QUICKLY
🔴     MODERATE       RED          REVIEW & ACT
🟠🟠   WARNING        ORANGE       MONITOR CLOSELY
🟡🟡   NEUTRAL        YELLOW       WAIT & WATCH
🟢🟢🟢 EXCELLENT      GREEN        STRONG OPPORTUNITY
🟢🟢   GOOD           GREEN        GOOD OPPORTUNITY
🔵🔵🔵 INFO (HIGH)    BLUE         REVIEW & LEARN
🔵🔵   INFO (MED)     BLUE         READ WHEN CONVENIENT
🟣🟣🟣 PLANNING       PURPLE       PREPARE AHEAD
```

---

## 💡 Visual Priority System

### Number of Badges = Urgency/Importance

- **3 badges (🔴🔴🔴)**: Highest priority - critical action needed
- **2 badges (🟢🟢)**: Medium-high priority - good opportunity or important info
- **1 badge (🔴)**: Standard alert - review and decide

### Examples:

1. **🔴🔴🔴 VOLUME SPIKE DROP** - Immediate attention! Unusual activity detected
2. **🟢🟢 ADD TO POSITION** - Good opportunity to add more
3. **🔵🔵 EOD SUMMARY** - Review at your convenience

---

## 🎯 How to Use This System

### Morning (9:00-9:15 AM)
- **🟣 PURPLE alerts** = Review pre-market patterns, plan your day

### During Market Hours (9:15 AM - 3:30 PM)
- **🔴 RED alerts** = Immediate attention required (drops, exits)
- **🟢 GREEN alerts** = Trading opportunities (rises, entry signals)
- **🟠 ORANGE alerts** = Caution - monitor closely

### After Market Hours (3:30 PM onwards)
- **🔵 BLUE alerts** = Review daily performance and analysis
- **🟣 PURPLE alerts** (Fridays 4 PM) = Weekly backtest results

### Weekend Planning
- **🟣 PURPLE alerts** = Strategy performance review, plan next week

---

## 🚀 Pro Tips

1. **Prioritize by color when you have multiple alerts:**
   - 🔴 RED first (critical)
   - 🟢 GREEN second (opportunities)
   - 🟠 ORANGE third (warnings)
   - 🔵 BLUE & 🟣 PURPLE later (informational)

2. **Set Telegram notification priorities:**
   - Critical: 🔴🔴🔴 alerts (sound + vibrate)
   - Important: 🟢🟢🟢, 🔴🔴 (sound only)
   - Normal: All others (silent notification)

3. **Filter by color in Telegram search:**
   - Search "🔴" to see all critical alerts
   - Search "🟢" to review all opportunities
   - Search "🟣" to find all backtest reports

---

## 📊 Alert Type Summary

| Color | Total Alert Types | Primary Use Case |
|-------|-------------------|------------------|
| 🔴 RED | 8 types | Urgent actions, exits, critical drops |
| 🟢 GREEN | 7 types | Trading opportunities, entry signals |
| 🟠 ORANGE | 2 types | Caution and weak signals |
| 🟡 YELLOW | 1 type | Hold/neutral status |
| 🔵 BLUE | 6 types | Daily summaries and analysis |
| 🟣 PURPLE | 3 types | Planning and strategy review |

---

## 🔍 Visual Recognition Quick Guide

**Separator Style = Alert Category:**

| Separator | Category | Examples |
|-----------|----------|----------|
| `═══` Double lines | **Options Trading** | NIFTY signals, ADD POSITION, EXIT |
| `▔▔▔` Top bars | **Market Analysis** | Sector rotation, Pre-market, Backtests |
| `┄┄┄` Dotted lines | **EOD Reports** | EOD patterns, EOD summaries |
| `▬▬▬` Thick bars | **Ultra-Fast** | 1-minute alerts |
| `━━━` Standard dashes | **Regular Stock** | 5-min, 30-min volume spikes |

**Text Style = Alert Importance:**

| Format | When Used | Example |
|--------|-----------|---------|
| **Bold + Italic** | Option trading signals | NIFTY signals, Entry/Exit |
| **Bold + Underline** | Sector/Market analysis | Sector rotation, Pre-market |
| **Bold + Monospace** | EOD analysis | EOD summaries, Pattern detection |
| **Bold** | Regular stock alerts | Volume spikes, Price movements |

---

## 💡 Pro Tips for Visual Recognition

1. **Glance at separators first:**
   - Double lines (`═══`) = Options → Check immediately if trading options
   - Dotted lines (`┄┄┄`) = EOD → Read at leisure after market
   - Thick bars (`▬▬▬`) = Ultra-fast → Urgent stock movement

2. **Color + Separator combo:**
   - 🟢 + `═══` = Good options trade signal
   - 🔴 + `═══` = Exit options position NOW
   - 🔵 + `┄┄┄` = EOD analysis (informational)
   - 🟣 + `▔▔▔` = Planning/Analysis (weekend/pre-market)

3. **Text formatting hints:**
   - Italic headers = Action required (trading signals)
   - Monospace headers = Informational (reviews/analysis)
   - Underline headers = Contextual info (market conditions)

---

**Last Updated:** January 4, 2026
**Version:** 2.0 (Added unique formatting styles)
