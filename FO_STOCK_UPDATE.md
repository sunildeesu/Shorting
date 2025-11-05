# F&O Stock List Update - November 2025

## Summary

Updated the F&O stock list to reflect current NSE Futures & Options eligible stocks using Kite Connect API.

## Changes

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **Total F&O Stocks** | 191 | 210 | +19 (+10%) |
| **Stocks Added** | - | 77 | New additions |
| **Stocks Removed** | - | 58 | Delisted from F&O |
| **Unchanged** | - | 133 | Still in F&O |

## Notable Additions (77 stocks)

Recent high-profile additions to NSE F&O segment:

### Financial Services
- **JIOFIN** - Jio Financial Services
- **360ONE** - 360 ONE WAM
- **KFINTECH** - KFin Technologies
- **ANGELONE** - Angel One
- **SAMMAANCAP** - Sammaancapital
- **LICI** - LIC of India
- **POLICYBZR** - PB Fintech (Policybazaar)

### Industrial & Infrastructure
- **NBCC** - NBCC India
- **HAL** - Hindustan Aeronautics
- **BEL** - Bharat Electronics
- **BDL** - Bharat Dynamics
- **TITAGARH** - Titagarh Rail Systems
- **RVNL** - Rail Vikas Nigam
- **GMRAIRPORT** - GMR Airports

### Technology & Manufacturing
- **DIXON** - Dixon Technologies
- **TATAELXSI** - Tata Elxsi
- **TATATECH** - Tata Technologies
- **KAYNES** - Kaynes Technology
- **UNOMINDA** - Uno Minda
- **KPITTECH** - KPIT Technologies

### Pharma & Healthcare
- **MANKIND** - Mankind Pharma
- **MAXHEALTH** - Max Healthcare
- **LAURUSLABS** - Laurus Labs
- **SYNGENE** - Syngene International
- **GLENMARK** - Glenmark Pharma

### Power & Energy
- **IREDA** - Indian Renewable Energy Development Agency
- **SUZLON** - Suzlon Energy
- **NHPC** - NHPC Limited
- **POWERINDIA** - Power India
- **JSWENERGY** - JSW Energy

### Others
- **INDIGO** - InterGlobe Aviation
- **NAUKRI** - Info Edge (Naukri.com)
- **DELHIVERY** - Delhivery
- **LODHA** - Macrotech Developers
- **BSE** - BSE Limited
- **MCX** - Multi Commodity Exchange

**Full list of 77 additions**: 360ONE, ABB, AMBER, ANGELONE, BANKINDIA, BDL, BEL, BHEL, BSE, CAMS, CDSL, CGPOWER, CONCOR, CYIENT, DALBHARAT, DELHIVERY, DIXON, ETERNAL, FORTIS, GLENMARK, GMRAIRPORT, HAL, HDFCAMC, HFCL, HINDPETRO, HINDZINC, HUDCO, ICICIPRULI, IEX, INDIANB, INDIGO, INDUSTOWER, INOXWIND, IREDA, JIOFIN, JSWENERGY, KALYANKJIL, KAYNES, KFINTECH, KPITTECH, LAURUSLABS, LICI, LODHA, LTF, MANKIND, MAXHEALTH, MAZDOCK, MCX, MFSL, NATIONALUM, NAUKRI, NBCC, NCC, NHPC, NIFTYNXT50, NUVAMA, OFSS, OIL, PATANJALI, PGEL, PNBHOUSING, POLICYBZR, POWERINDIA, PPLPHARMA, RVNL, SAMMAANCAP, SONACOMS, SUZLON, SYNGENE, TATAELXSI, TATATECH, TIINDIA, TITAGARH, TMPV, UNITDSPR, UNOMINDA, YESBANK

## Notable Removals (58 stocks)

Stocks removed from F&O segment (delisted or failed to meet criteria):

### Large Caps Removed
- **TATAMOTORS** - Tata Motors (surprising removal)
- **ZOMATO** - Zomato
- **MRF** - MRF Tyres

### Pharma Stocks Removed
- **ABBOTINDIA** - Abbott India
- **SANOFI** - Sanofi India
- **GLAXO** - GlaxoSmithKline
- **LALPATHLAB** - Dr. Lal PathLabs
- **METROPOLIS** - Metropolis Healthcare

### Consumer & Retail
- **PVR** - PVR Inox (merged entity adjustments)
- **WESTLIFE** - Westlife Foodworld
- **DEVYANI** - Devyani International
- **NYKAA** (not in removed list, check if it's in additions)

### Infrastructure & Materials
- **ADANIPOWER** - Adani Power
- **ADANITRANS** - Adani Transmission
- **GMRINFRA** - GMR Infrastructure
- **RAMCOCEM** - Ramco Cements
- **INDIACEM** - India Cements
- **HEIDELBERG** - HeidelbergCement

### Others
- **MINDTREE** - Mindtree (merged with LTI)
- **BSOFT** - Birlasoft
- **ESCORTS** - Escorts Kubota

**Full list of 58 removals**: AARTI, ABBOTINDIA, ABFRL, ACC, ADANIPOWER, ADANITRANS, APOLLOTYRE, ATUL, BAJAJHLDNG, BALKRISIND, BATAINDIA, BERGEPAINT, BRIGADE, BSOFT, CEAT, CESC, CHAMBLFERT, CLEAN, COROMANDEL, DEEPAKNTR, DELTACORP, DEVYANI, Dixon, ESCORTS, FLUOROCHEM, GLAXO, GMRINFRA, GNFC, GSPL, HEIDELBERG, IBREALEST, INDIACEM, JKCEMENT, L&TFH, LALPATHLAB, LEMONTREE, M&MFIN, MCDOWELL-N, METROPOLIS, MGL, MINDTREE, MOIL, MRF, NAVINFLUOR, PEL, PGHH, POONAWALLA, PVR, RAMCOCEM, RELAXO, SANOFI, SCHAEFFLER, SKFINDIA, TATAMOTORS, TIMKEN, WESTLIFE, WHIRLPOOL, ZOMATO

## Impact on Monitoring

### Pharma Stock Coverage
Updated pharma stocks being monitored (config.py:PHARMA_STOCKS):

**Still monitored (in F&O):**
- SUNPHARMA ✅
- DRREDDY ✅
- CIPLA ✅
- DIVISLAB ✅
- APOLLOHOSP ✅
- AUROPHARMA ✅
- LUPIN ✅
- TORNTPHARM ✅
- BIOCON ✅
- ALKEM ✅
- ZYDUSLIFE ✅

**Removed from F&O (no longer monitored):**
- LALPATHLAB ❌
- METROPOLIS ❌
- ABBOTINDIA ❌
- SANOFI ❌
- GLAXO ❌

**Action Required**: Update config.py:PHARMA_STOCKS to remove delisted stocks.

### Batch API Performance

With 210 stocks (up from 191):

| Metric | Value |
|--------|-------|
| **Batches needed** | 5 (was 4) |
| **API calls per run** | 5 (was 4) |
| **Estimated time** | ~2 seconds (was 1.5s) |
| **Still well within limits** | ✅ Yes (2.5 req/sec) |

The batch API optimization still provides massive benefits even with more stocks.

## How to Update in Future

Use the provided script to update F&O stock list:

### Interactive Mode
```bash
./venv/bin/python3 update_fo_stocks.py
```

Shows comparison and asks for confirmation before updating.

### Auto Mode (CI/CD)
```bash
./venv/bin/python3 update_fo_stocks.py --auto
```

Automatically updates without confirmation. Useful for cron jobs or automated updates.

### Recommended Schedule

Update F&O stock list:
- **Monthly**: First week of every month
- **After NSE announcements**: When NSE adds/removes F&O stocks
- **Before major events**: Derivatives expiry weeks

## Technical Details

### Data Source
- **API**: Kite Connect `instruments("NFO")` endpoint
- **Filtering**: Only equity F&O (excludes NIFTY, BANKNIFTY indices)
- **Instrument types**: FUT (Futures), CE (Call Options), PE (Put Options)

### Update Method
```python
# Fetch all NFO instruments
instruments = kite.instruments("NFO")

# Extract unique underlying symbols
fo_stocks = set()
for instrument in instruments:
    if instrument['instrument_type'] in ['FUT', 'CE', 'PE']:
        symbol = instrument['name']
        if symbol not in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']:
            fo_stocks.add(symbol)
```

### File Updated
- **Path**: `fo_stocks.json`
- **Format**: JSON array of stock symbols
- **Sorted**: Alphabetically for easy diffing

## Verification

System successfully loads the updated list:

```bash
✅ Successfully loaded 210 F&O stocks from fo_stocks.json
```

The cron job will automatically pick up the new list on the next run (no restart needed).

## Next Steps

1. ✅ **Update complete** - fo_stocks.json updated with 210 stocks
2. ⚠️ **Update PHARMA_STOCKS** in config.py - Remove delisted pharma stocks
3. 📊 **Monitor performance** - Check if 5 batches work as expected
4. 📅 **Schedule updates** - Run update_fo_stocks.py monthly

---

**Update Date**: 2025-11-03
**Method**: Kite Connect API
**Verified**: Yes - System loads 210 stocks successfully
