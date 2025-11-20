# Sector EOD Report - User Guide

## Overview
The Sector EOD (End-of-Day) Report provides comprehensive Excel-based analysis of sector performance and fund flow allocation. This report is automatically generated daily at **3:25 PM** (market close) and saved to organized monthly folders.

## Report Location
```
data/sector_eod_reports/YYYY/MM/sector_analysis_YYYYMMDD.xlsx
```

Example: `data/sector_eod_reports/2025/11/sector_analysis_20251120.xlsx`

## Report Structure

### Sheet 1: Summary
**Sector Performance Rankings**

| Column | Description |
|--------|-------------|
| Rank | Sector ranking by 10-min performance |
| Sector | Sector name |
| 10-Min Change % | Price change over last 10 minutes |
| 30-Min Change % | Price change over last 30 minutes |
| Momentum Score | Calculated momentum (price × volume × participation) |
| Volume Ratio | Current volume vs average (1.0 = average) |
| Market Cap (Cr) | Total market capitalization in crores |
| Stocks Up | Number of stocks with positive movement |
| Stocks Down | Number of stocks with negative movement |
| Total Stocks | Total stocks in sector |
| Breadth % | Percentage of stocks participating |
| Status | Fund flow status with color coding |

**Status Color Codes:**
- 🟢 **Green**: Strong Inflow (>0.5%)
- 🟡 **Light Green**: Moderate Inflow (0% to 0.5%)
- 🟠 **Orange**: Moderate Outflow (0% to -0.5%)
- 🔴 **Red**: Strong Outflow (<-0.5%)

### Sheet 2: Detailed Metrics
**Comprehensive Multi-Timeframe Analysis**

Includes all timeframes (5-min, 10-min, 30-min) with:
- Price changes across all timeframes
- Momentum scores for each timeframe
- Current and average volume
- Volume ratios
- Market cap data
- Participation percentages

**Use Case:** Deep dive into sector trends across multiple timeframes.

### Sheet 3: Fund Flow
**Capital Allocation Analysis**

| Column | Description |
|--------|-------------|
| Sector | Sector name |
| Market Cap (Cr) | Total market cap |
| % of Total | Percentage of overall market cap |
| 10-Min Change % | Recent price movement |
| Implied Flow (Cr) | Estimated fund inflow/outflow in crores |
| Volume Ratio | Volume vs average |
| Momentum | Momentum score |
| Flow Status | Fund flow classification with color coding |

**Implied Flow Calculation:**
```
Implied Flow = Market Cap × (Price Change % / 100)
```

**Flow Status Definitions:**
- **Strong Inflow**: Price change >0.5% AND volume ratio >1.2
- **Moderate Inflow**: Price change >0%
- **Moderate Outflow**: Price change between 0% and -0.5%
- **Strong Outflow**: Price change <-0.5%

## Configuration

### Enable/Disable EOD Reports
Edit `.env` file:
```bash
# Enable sector EOD reports (default: true)
ENABLE_SECTOR_EOD_REPORT=true

# Enable sector analysis (required for reports)
ENABLE_SECTOR_ANALYSIS=true
```

Or edit `config.py`:
```python
ENABLE_SECTOR_EOD_REPORT = True
ENABLE_SECTOR_ANALYSIS = True
```

## Automation

### Daily Generation
Reports are automatically generated at **3:25 PM** when:
1. Stock monitor is running
2. Sector analysis is enabled
3. EOD report generation is enabled

### Integration with Stock Monitor
The EOD report is generated alongside the Telegram summary:
1. At 3:25 PM, sector analysis runs
2. Telegram EOD summary is sent
3. Excel report is generated and saved
4. Both processes log completion

## Reading the Report

### Top Performers (Gainers)
1. Open Sheet 1 (Summary)
2. Check Rank 1-3 for top gaining sectors
3. Look at "Status" column for flow classification
4. Note the "Implied Flow (Cr)" in Sheet 3 for capital magnitude

### Fund Outflow Detection (Losers)
1. Scroll to bottom of Sheet 1 (Summary)
2. Check last 3 ranks for losing sectors
3. Red-colored status = strong outflow
4. Sheet 3 shows negative "Implied Flow" values

### Market Sentiment
**Sheet 3 - Market Summary Section:**
- Total Market Cap: Overall market size
- Stocks Up/Down: Breadth indicators
- Percentages: Market participation rates

**Interpretation:**
- >60% stocks up = Bullish sentiment
- 40-60% stocks up = Neutral/Mixed
- <40% stocks up = Bearish sentiment

### Sector Rotation Analysis
Compare Sheet 1 rankings with Sheet 3 fund flow:
1. Sectors with high positive flow = Money flowing IN
2. Sectors with high negative flow = Money flowing OUT
3. Volume ratio >1.5 = High conviction moves

## Use Cases

### 1. Trading Strategy
**Identify Strong Sectors:**
```
Filter: Status = "Strong Inflow" AND Volume Ratio > 1.5
Action: Look for individual stocks in these sectors for long positions
```

**Avoid Weak Sectors:**
```
Filter: Status = "Strong Outflow" AND Momentum < -1.0
Action: Avoid or short stocks in these sectors
```

### 2. Portfolio Rebalancing
- Review Sheet 3 for market cap distribution
- Compare your portfolio allocation vs sector performance
- Reduce exposure to sectors with consistent outflows
- Increase exposure to sectors with strong inflows

### 3. Risk Management
- Monitor sectors with volatile fund flows
- Check breadth % to validate sector moves
- Low breadth + high price change = Narrow rally (risky)
- High breadth + high price change = Broad rally (safer)

### 4. Daily Review
**End-of-Day Routine:**
1. Open today's report
2. Check Summary sheet for top 3 gainers/losers
3. Review Fund Flow sheet for implied flows
4. Note sectors with >2% divergence for tomorrow

## Technical Details

### Data Source
- **ZERO additional API calls**
- Reads from existing `price_cache.json` (updated every 5 minutes)
- Leverages sector mappings from `stock_sectors.json`
- Uses market cap data from `shares_outstanding.json`

### Metrics Calculation

**Price Change:**
```python
price_change = ((current_price - previous_price) / previous_price) × 100
```

**Market-Cap Weighted Sector Price:**
```python
sector_change = Σ(stock_change × stock_market_cap) / total_sector_market_cap
```

**Momentum Score:**
```python
momentum = price_change × volume_ratio × (participation% / 100)
```

**Volume Ratio:**
```python
volume_ratio = current_volume / average_volume
```

### File Management
- Reports organized by year/month for easy archiving
- Each day generates one file (overwrites if re-run same day)
- Recommended to keep last 3 months for trend analysis
- Archive older reports to reduce storage

## Troubleshooting

### Report Not Generated
**Check:**
1. Stock monitor is running at 3:25 PM
2. `ENABLE_SECTOR_ANALYSIS=true` in config
3. `ENABLE_SECTOR_EOD_REPORT=true` in config
4. Sector analysis cache exists: `data/sector_analysis_cache.json`

### Empty or Missing Data
**Possible causes:**
1. Price cache is empty (monitor not running long enough)
2. Less than 3 stocks per sector (check `MIN_SECTOR_STOCKS` config)
3. Market closed (no price updates)

**Solution:** Run stock monitor for at least 30 minutes before EOD.

### Incorrect Market Cap
**Check:**
1. `data/shares_outstanding.json` exists and is up to date
2. Stock symbols match between `fo_stocks.json` and `shares_outstanding.json`

### Manual Report Generation
Run test script:
```bash
./venv/bin/python3 test_sector_eod_report.py
```

## Integration with Other Features

### Works With:
- ✅ Stock drop/rise alerts (provides sector context)
- ✅ Sector rotation alerts (9:30, 12:30, 15:15)
- ✅ EOD Telegram summary (parallel generation)
- ✅ RSI analysis (complementary indicators)
- ✅ Volume spike detection (confirms sector moves)

### Independent Of:
- ❌ EOD stock analysis (separate report system)
- ❌ ATR breakout monitoring (different strategy)

## Best Practices

1. **Review Daily:** Make it part of your EOD routine
2. **Compare Historical:** Keep 1-2 months to spot trends
3. **Cross-Reference:** Use with stock-level EOD reports
4. **Focus on Extremes:** Pay attention to >2% moves
5. **Validate with Volume:** Ignore low volume sector moves
6. **Track Rotation:** Watch for money shifting between sectors

## Sample Insights

### Example 1: Tech Rally
```
Sheet 1: IT sector ranked #1 with +1.8% (Green status)
Sheet 3: Implied Flow = +₹6,048 Cr
Breadth: 14/16 stocks up (87.5%)
Volume Ratio: 1.4x

Insight: Strong broad-based IT rally with conviction
Action: Consider IT stock longs
```

### Example 2: Bank Weakness
```
Sheet 1: Banking sector ranked #12 with -1.2% (Red status)
Sheet 3: Implied Flow = -₹6,417 Cr
Breadth: 3/18 stocks up (16.7%)
Volume Ratio: 1.3x

Insight: Broad banking sector selloff with high volume
Action: Avoid banking longs, consider defensive sectors
```

## Advanced Usage

### Sector Pair Trading
1. Find diverging sectors (one strong inflow, one strong outflow)
2. Check correlation history
3. Long strong sector, short weak sector
4. Use momentum scores to time entry/exit

### Correlation Analysis
- Track which sectors move together
- Identify leading vs lagging sectors
- Use for diversification decisions

### Trend Detection
- Compare current vs previous day's report
- Identify persistent sector trends (3+ days same direction)
- Strong trends = continuation, reversals = rotation opportunities

## Support and Updates

For questions or issues:
1. Check logs: `logs/stock_monitor.log`
2. Verify sector analysis cache: `data/sector_analysis_cache.json`
3. Run test: `./venv/bin/python3 test_sector_eod_report.py`
4. Review configuration: `config.py`

---

**Generated by:** Sector EOD Report System
**Version:** 1.0
**Last Updated:** November 2025
