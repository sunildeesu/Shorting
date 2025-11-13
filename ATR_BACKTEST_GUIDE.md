# ATR Breakout Strategy - Backtesting Guide

Complete guide for backtesting the ATR breakout strategy and analyzing results.

---

## 🎯 What Gets Tested

The backtest simulates the exact ATR breakout strategy over historical data:

**Entry Rules:**
- Price crosses above Open + (2.5 × ATR(20))
- ATR(20) < ATR(30) (volatility contracting)

**Exit Rules:**
- Stop Loss: Entry - (0.5 × ATR(20))
- Friday close (if enabled)

**Strategy Parameters:**
- ATR_PERIOD_SHORT: 20
- ATR_PERIOD_LONG: 30
- ATR_ENTRY_MULTIPLIER: 2.5
- ATR_STOP_MULTIPLIER: 0.5
- ATR_FILTER_CONTRACTION: true
- ATR_FRIDAY_EXIT: true

---

## 🚀 Quick Start

### Basic Usage (12 months backtest)

```bash
./backtest_atr_strategy.py
```

This will:
- Test last 12 months of data
- Test all 191 F&O stocks
- Generate Excel report with full analysis
- Save to `data/backtest_results/`

### Custom Time Period

```bash
# Test last 6 months
./backtest_atr_strategy.py --months 6

# Test last 24 months (2 years)
./backtest_atr_strategy.py --months 24

# Test last 36 months (3 years)
./backtest_atr_strategy.py --months 36
```

### Quick Test (Few Stocks)

```bash
# Test only first 10 stocks (faster)
./backtest_atr_strategy.py --stocks 10

# Test first 30 stocks (6 months)
./backtest_atr_strategy.py --months 6 --stocks 30
```

---

## 📊 Excel Report Structure

The backtest generates a comprehensive Excel workbook with 5 sheets:

### Sheet 1: Summary

**Key Metrics:**
- Total trades, wins, losses
- Win rate percentage
- Total P&L and average P&L per trade
- Average win vs. average loss
- Risk/Reward ratio
- Average holding period
- Exit reason breakdown
- Best and worst trades

**Example:**
```
OVERALL PERFORMANCE
Total Trades:           318
Winning Trades:         172
Losing Trades:          146
Win Rate:               54.09%

PROFIT & LOSS
Total P&L:              +127.45%
Average P&L per Trade:  +0.40%
Average Win:            +2.15%
Average Loss:           -1.38%
Risk/Reward Ratio:      1.56

HOLDING PERIOD
Average Holding Days:   2.3

EXIT ANALYSIS
Stop Loss Exits:        198 (62.3%)
Friday Exits:           120 (37.7%)

BEST TRADE
RELIANCE: +8.45% (2024-03-15 → 2024-03-18)

WORST TRADE
TATASTEEL: -2.87% (2024-08-22 → 2024-08-22)
```

### Sheet 2: All Trades

**Detailed trade log with columns:**
- Symbol
- Entry Date & Day
- Exit Date & Day
- Holding Days
- Entry Price, Exit Price, Stop Loss
- P&L (₹ and %)
- Result (WIN/LOSS)
- Exit Reason
- ATR(20), ATR(30)
- Volatility Filter status
- Volume

**Color coding:**
- Green rows: Winning trades
- Red rows: Losing trades

### Sheet 3: Monthly Performance

**Month-by-month breakdown:**
- Number of trades per month
- Wins vs. losses
- Win rate
- Total P&L for the month
- Average P&L per trade

**Example:**
```
Month      Trades  Wins  Losses  Win Rate  Total P&L  Avg P&L
2024-01    28      16    12      57.14%    +12.35%    +0.44%
2024-02    25      13    12      52.00%    +8.12%     +0.32%
2024-03    31      18    13      58.06%    +15.87%    +0.51%
...
```

### Sheet 4: Stock Performance

**Per-stock analysis (sorted by total P&L):**
- Number of trades per stock
- Win rate per stock
- Total P&L per stock
- Average P&L per trade

**Example:**
```
Symbol      Trades  Wins  Losses  Win Rate  Total P&L  Avg P&L
RELIANCE    12      8     4       66.67%    +18.45%    +1.54%
TCS         9       6     3       66.67%    +12.30%    +1.37%
INFY        11      6     5       54.55%    +8.20%     +0.75%
...
```

**Use this to identify:**
- Best performing stocks (high win rate + high P&L)
- Worst performing stocks (low win rate or negative P&L)
- Stocks to focus on or avoid

### Sheet 5: Analysis & Recommendations

**Automated analysis with actionable recommendations:**

**1. Win Rate Analysis:**
- Overall win rate evaluation
- Performance rating (Excellent/Good/Needs Improvement)

**2. Risk/Reward Analysis:**
- Average win vs. average loss
- R:R ratio evaluation
- Assessment of profitability

**3. Exit Strategy Analysis:**
- Stop loss effectiveness
- Friday exit impact
- Protection from large losses

**4. Recommendations:**
- Specific parameter adjustments
- Strategy improvements
- Filter suggestions

**Example Recommendations:**
```
✓ Win rate above 50% - Strategy is profitable
✓ R:R ratio of 1.56 is acceptable
• Consider tightening stop loss to improve R:R
• Add volume confirmation for better entry quality
• Test trailing stop for capturing larger moves
```

---

## 📈 Understanding the Results

### What is a Good Win Rate?

- **Above 60%**: Excellent - Strategy is very strong
- **50-60%**: Good - Strategy is profitable
- **40-50%**: Marginal - Needs R:R ratio above 1.5 to be profitable
- **Below 40%**: Poor - Strategy needs significant improvement

### What is a Good Risk/Reward Ratio?

- **Above 2.0**: Excellent - Can be profitable even with 40% win rate
- **1.5-2.0**: Good - Needs 45%+ win rate
- **1.0-1.5**: Marginal - Needs 55%+ win rate
- **Below 1.0**: Poor - Losing more on losses than gaining on wins

### Calculating Profitability

**Break-even win rate formula:**
```
Break-even = 1 / (1 + R:R ratio)
```

**Examples:**
- R:R = 2.0 → Need 33.3% win rate to break even
- R:R = 1.5 → Need 40% win rate to break even
- R:R = 1.0 → Need 50% win rate to break even

### Exit Reason Analysis

**Stop Loss Exits:**
- High percentage (>70%): Stop loss too tight
- Medium (40-70%): Balanced
- Low (<40%): Stop loss too wide or Friday exits dominating

**Friday Exits:**
- High percentage: Strategy holds positions for multiple days
- Check if Friday exits are profitable or cutting winners short

---

## 🔍 Example: Reading Your Results

### Scenario 1: High Win Rate, Low R:R

```
Win Rate: 65%
Avg Win: +1.2%
Avg Loss: -1.8%
R:R Ratio: 0.67
```

**Analysis:**
- Strategy picks good entries (65% win rate)
- BUT cutting winners too early (small wins)
- OR letting losses run too long (large losses)

**Fix:**
- Use trailing stop to capture larger moves
- Tighten stop loss to reduce loss size

### Scenario 2: Low Win Rate, High R:R

```
Win Rate: 42%
Avg Win: +4.5%
Avg Loss: -1.2%
R:R Ratio: 3.75
```

**Analysis:**
- Many false breakouts (42% win rate)
- BUT winners are very profitable (3.75:1 R:R)
- Strategy is still profitable overall

**Fix:**
- Add volume confirmation filter
- Increase ATR_ENTRY_MULTIPLIER to reduce false breakouts

### Scenario 3: Balanced Performance

```
Win Rate: 55%
Avg Win: +2.1%
Avg Loss: -1.3%
R:R Ratio: 1.62
```

**Analysis:**
- Good balance of win rate and R:R
- Strategy is profitable
- Minor optimizations possible

**Fix:**
- Test different ATR multipliers
- Consider position sizing strategies

---

## 🛠️ Optimizing Parameters

Based on backtest results, you can adjust parameters in `.env`:

### If Win Rate Too Low (<50%)

**Problem:** Too many false breakouts

**Solutions:**
```bash
# Increase entry threshold (fewer but higher quality signals)
ATR_ENTRY_MULTIPLIER=3.0  # Up from 2.5

# Enable volatility filter if disabled
ATR_FILTER_CONTRACTION=true

# Increase minimum volume filter
ATR_MIN_VOLUME=75  # Up from 50
```

### If R:R Ratio Too Low (<1.5)

**Problem:** Wins too small or losses too large

**Solutions:**
```bash
# Tighten stop loss
ATR_STOP_MULTIPLIER=0.3  # Down from 0.5

# Or use wider target (not in current implementation)
# Consider adding trailing stop
```

### If Stop Loss Hit Too Often (>70%)

**Problem:** Stop too tight

**Solutions:**
```bash
# Widen stop loss
ATR_STOP_MULTIPLIER=0.7  # Up from 0.5

# Or adjust entry to better price
ATR_ENTRY_MULTIPLIER=2.3  # Down from 2.5
```

### If Average Holding Period Too Long (>3 days)

**Problem:** Capital tied up too long

**Solutions:**
```bash
# Disable Friday exit to close faster
ATR_FRIDAY_EXIT=false

# Or add time-based exit in code (e.g., 3 days max)
```

---

## 📊 Re-running After Changes

After adjusting parameters:

1. **Update `.env` file** with new parameters
2. **Re-run backtest** with same time period:
   ```bash
   ./backtest_atr_strategy.py --months 12
   ```
3. **Compare results** side by side
4. **Keep the better performing config**

**Example comparison:**
```
Original (ATR_ENTRY=2.5):
- Win Rate: 54%
- R:R: 1.56
- Total P&L: +127.45%

Modified (ATR_ENTRY=3.0):
- Win Rate: 61%
- R:R: 1.72
- Total P&L: +145.30%

✓ Use modified config (better results)
```

---

## 🎯 Best Practices

### 1. Test Sufficient Data

- **Minimum:** 6 months (tests different market conditions)
- **Recommended:** 12 months (full year cycle)
- **Ideal:** 24-36 months (captures bull and bear markets)

```bash
# Recommended
./backtest_atr_strategy.py --months 12
```

### 2. Quick Test First

Before full backtest, test with limited stocks:

```bash
# Quick test (5 minutes)
./backtest_atr_strategy.py --stocks 20 --months 6

# If results look good, run full test
./backtest_atr_strategy.py --months 12
```

### 3. Consider Market Regime

Check Monthly Performance sheet:
- Bull market months: Higher win rate expected
- Bear market months: Lower win rate, but strategy should still be profitable
- Consistent monthly performance = robust strategy

### 4. Focus on Quality, Not Quantity

Better to have:
- 300 trades with 55% win rate and 1.6 R:R
- Than 1000 trades with 48% win rate and 1.2 R:R

### 5. Validate Stock Performance

Check Sheet 4 (Stock Performance):
- Avoid stocks with consistently low win rate
- Focus on stocks with high win rate + high total P&L
- Consider filtering stocks in `fo_stocks.json`

---

## 🕒 Expected Runtime

**Time estimates:**

```
10 stocks × 6 months    = ~2-3 minutes
30 stocks × 6 months    = ~6-8 minutes
50 stocks × 12 months   = ~12-15 minutes
191 stocks × 12 months  = ~30-45 minutes
191 stocks × 36 months  = ~90-120 minutes
```

**Factors affecting speed:**
- Number of stocks
- Time period length
- API rate limiting (0.4s delay per call)
- Historical data cache availability

---

## 📁 Output Location

All backtest results are saved to:

```
data/backtest_results/
├── atr_backtest_12months_20251112_143052.xlsx
├── atr_backtest_12months_20251112_153420.xlsx
└── ...
```

**Filename format:**
```
atr_backtest_{months}months_{timestamp}.xlsx
```

**Logs saved to:**
```
logs/atr_backtest.log
```

---

## 🔍 Troubleshooting

### No trades generated

**Possible causes:**
1. Date range has no market data (weekends/holidays)
2. ATR filters too strict (no breakouts in period)
3. Instrument tokens missing

**Solutions:**
```bash
# Check logs
tail -100 logs/atr_backtest.log

# Verify instrument tokens exist
ls data/instrument_tokens.json

# Try shorter period or fewer stocks
./backtest_atr_strategy.py --months 3 --stocks 10
```

### API rate limit errors

**Error:** `Too many requests` or `Rate limit exceeded`

**Solution:**
- Increase `REQUEST_DELAY_SECONDS` in config.py
- Or run with fewer stocks: `--stocks 50`

### Very low win rate (<30%)

**Possible causes:**
1. Bear market period tested
2. Parameters not optimized
3. Strategy not suitable for certain stocks

**Solutions:**
- Check Monthly Performance for market regime
- Adjust parameters (increase ATR_ENTRY_MULTIPLIER)
- Filter to liquid stocks only

### Backtest taking too long

**Solutions:**
```bash
# Test subset first
./backtest_atr_strategy.py --stocks 30

# Or use cached data if available
# (Unified cache will speed up repeated backtests)
```

---

## 📚 Advanced Analysis

### Compare Different Configurations

Run multiple backtests with different parameters:

```bash
# Test 1: Original
./backtest_atr_strategy.py --months 12

# Test 2: Higher entry threshold
# Edit .env: ATR_ENTRY_MULTIPLIER=3.0
./backtest_atr_strategy.py --months 12

# Test 3: Tighter stop
# Edit .env: ATR_STOP_MULTIPLIER=0.3
./backtest_atr_strategy.py --months 12

# Compare all Excel reports side by side
```

### Analyze by Market Cap

Filter stocks in Sheet 4 by:
- Large cap (>50,000 Cr): More stable, lower volatility
- Mid cap (10,000-50,000 Cr): Balanced
- Small cap (<10,000 Cr): Higher volatility, bigger moves

### Analyze by Sector

Group stocks from Sheet 4 by sector:
- IT stocks: TCS, INFY, WIPRO, etc.
- Banking: HDFCBANK, ICICIBANK, SBIN, etc.
- Auto: MARUTI, M&M, TATAMOTORS, etc.

Check if strategy works better in certain sectors.

---

## 🎓 Key Takeaways

**What the backtest tells you:**
✓ If the strategy is profitable historically
✓ Expected win rate and average profit per trade
✓ How often stop loss gets hit
✓ Which stocks perform best with this strategy
✓ Parameter adjustments needed

**What it doesn't tell you:**
✗ Future performance (past ≠ future)
✗ Impact of slippage and fees
✗ Gap risk (backtests assume fills at exact levels)
✗ Market regime changes

**Use backtest for:**
- Strategy validation
- Parameter optimization
- Stock selection
- Understanding risk/reward
- Building confidence in the approach

---

## 🚀 Next Steps After Backtesting

1. **Review results** thoroughly (all 5 sheets)
2. **Adjust parameters** based on recommendations
3. **Re-backtest** to validate improvements
4. **Paper trade** with live data before real money
5. **Start small** with optimized parameters
6. **Track live performance** vs. backtest expectations

---

## 📝 Quick Command Reference

```bash
# Standard 12-month backtest
./backtest_atr_strategy.py

# Custom periods
./backtest_atr_strategy.py --months 6
./backtest_atr_strategy.py --months 24

# Quick test
./backtest_atr_strategy.py --stocks 20 --months 6

# View logs
tail -f logs/atr_backtest.log

# Find latest report
ls -lt data/backtest_results/ | head -5
```

---

**Happy Backtesting! 🎯**

*Remember: Past performance is not indicative of future results. Always validate with paper trading before risking real capital.*
