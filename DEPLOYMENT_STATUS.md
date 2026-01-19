# Central Data Collector - Deployment Status

**Date:** 2026-01-19
**Time:** 09:10 AM
**Status:** ✅ **DEPLOYED - Ready for Market Open**

---

## ✅ Deployment Complete

### **Phase 1: Testing & Deployment** ✓ COMPLETE

1. ✅ **Database Created**
   - Location: `data/central_quotes.db`
   - Size: 52 KB
   - Tables: stock_quotes, nifty_quotes, vix_quotes, metadata
   - WAL mode enabled

2. ✅ **Basic Tests Passed**
   - Database initialization: ✓
   - Market hours detection: ✓
   - Graceful closed market handling: ✓

3. ✅ **Simulated Data Tests Passed**
   - Write operations: 100% success
   - Read operations: 100% success
   - Data integrity: Verified
   - NIFTY/VIX data: Working

4. ✅ **LaunchAgent Deployed**
   - File: `~/Library/LaunchAgents/com.nse.central.collector.plist`
   - Status: Loaded
   - Schedule: Mon-Fri at 9:29 AM
   - Will start automatically tomorrow

---

## 📋 What Happens Next

### **Tomorrow (First Trading Day):**

**9:29 AM** - LaunchAgent starts `central_data_collector_continuous.py`

**9:30 AM** - First data collection cycle begins:
- Fetches 209 F&O stocks (equity + futures)
- Fetches NIFTY 50 spot data
- Fetches India VIX data
- Stores everything in `data/central_quotes.db`

**9:31 AM - 3:25 PM** - Continuous collection every 1 minute

**3:25 PM** - Collector exits gracefully

**3:30 PM** - Database cleanup (deletes data >1 day old)

---

## 📊 Monitoring Instructions

### **1. Check if Collector is Running**
```bash
launchctl list | grep central.collector
# Should show: <PID>  0  com.nse.central.collector
```

### **2. Monitor Live Logs**
```bash
tail -f logs/central_collector.log
# OR
tail -f logs/central-collector-stdout.log
```

### **3. Check Database Stats** (during market hours)
```bash
./venv/bin/python3 -c "
from central_quote_db import get_central_db
db = get_central_db()
stats = db.get_database_stats()
print(f'Stocks: {stats[\"unique_stocks\"]}')
print(f'NIFTY records: {stats[\"nifty_records\"]}')
print(f'VIX records: {stats[\"vix_records\"]}')
print(f'Last update: {stats[\"last_stock_update\"]}')
"
```

### **4. Verify Latest Data**
```bash
./venv/bin/python3 -c "
from central_quote_db import get_central_db
db = get_central_db()

# Check stocks
quotes = db.get_latest_stock_quotes(['RELIANCE', 'TCS', 'INFY'])
for symbol, data in quotes.items():
    print(f'{symbol}: ₹{data[\"price\"]:.2f}')

# Check NIFTY
nifty = db.get_nifty_latest()
if nifty:
    print(f'NIFTY: ₹{nifty[\"price\"]:.2f}')

# Check VIX
vix = db.get_vix_latest()
if vix:
    print(f'VIX: {vix[\"vix_value\"]:.2f}')
"
```

---

## 🔍 Expected Log Output (Normal Operation)

```
================================================================================
CENTRAL DATA COLLECTOR - CONTINUOUS MODE
================================================================================
✅ Trading day confirmed
✅ Collector initialized successfully
🚀 Starting continuous collection loop
📊 Market hours: 9:30 AM - 3:25 PM
⏱️  Collection interval: Every 60 seconds
================================================================================

================================================================================
CYCLE #1 - 09:30:15
================================================================================
Fetching quotes for 209 stocks...
Fetched 418 quotes in 3 API calls
Fetching NIFTY 50 quote...
Fetching India VIX quote...
Storing data in central database...
Stored 209 stock quotes at 2026-01-20 09:30:00
================================================================================
Collection cycle complete in 4.2s
  Stocks: 209/209
  NIFTY: ✓
  VIX: ✓
  API calls: 3
  Errors: 0
================================================================================
⏸️  Sleeping 45s until next collection...
```

---

## ⚠️ Troubleshooting

### **If collector doesn't start tomorrow:**

1. Check LaunchAgent status:
   ```bash
   launchctl list | grep central.collector
   ```

2. Check for errors:
   ```bash
   cat logs/central-collector-stderr.log
   ```

3. Manually start collector:
   ```bash
   ./venv/bin/python3 central_data_collector_continuous.py
   ```

### **If no data in database:**

1. Verify market is open (9:30 AM - 3:25 PM, Mon-Fri)
2. Check Kite token validity:
   ```bash
   python3 generate_kite_token.py
   ```
3. Check collector logs for API errors

### **If database grows too large:**

The cleanup runs automatically at 3:30 PM daily. Manual cleanup:
```bash
./venv/bin/python3 -c "
from central_quote_db import get_central_db
db = get_central_db()
db.cleanup_old_data(days=1)
"
```

---

## 📈 Success Metrics (Day 1)

Check these after first trading day:

- [ ] Collector ran for full market hours (9:30 AM - 3:25 PM)
- [ ] 209 stocks collected every minute (~360 cycles)
- [ ] NIFTY data collected every minute
- [ ] VIX data collected every minute
- [ ] Zero API errors in logs
- [ ] Database size reasonable (<50 MB for 1 day)
- [ ] No duplicate data (primary key constraints working)

---

## 🚀 Next Phase (Day 2)

After confirming Day 1 success:

1. **Migrate first service** - NIFTY Option Monitor (simplest)
2. **Verify alerts still work** - Compare with previous day
3. **Migrate remaining services** - One by one
4. **Stop redundant services** - Once all migrated

**Migration priority:**
1. NIFTY Option Monitor (easiest)
2. Sector Analyzer (medium)
3. 5-min/10-min Alerts (moderate)
4. 1-min Alerts (most complex)

---

## 📞 Support

**Architecture Docs:** `ARCHITECTURE_MIGRATION.md`
**Test Scripts:** `test_central_collector.py`, `test_db_with_simulated_data.py`
**Database Module:** `central_quote_db.py`
**Collector Module:** `central_data_collector.py`

---

**Status:** Ready for production
**Confidence Level:** HIGH ✅
**Risk Level:** LOW (runs in parallel with existing services)
