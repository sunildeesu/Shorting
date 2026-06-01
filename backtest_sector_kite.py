#!/usr/bin/env python3
"""
Proper backtest: Sector context vs short signal quality (Kite API version).

Uses Kite's historical candle API to get the EXACT sector index % change
from day open to alert time — eliminating the snapshot timing problem.

Sector → NSE Index mapping:
  BANKING / FINANCIAL_SERVICES → NIFTY BANK  (260105)
  IT                           → NIFTY IT    (5459490)  [adjust if needed]
  PHARMA                       → NIFTY PHARMA (5577794)
  AUTO                         → NIFTY AUTO   (5582082)
  ENERGY / INFRASTRUCTURE      → NIFTY ENERGY  (14385)
  METAL                        → NIFTY METAL   (234249)
  FMCG / CONSUMER              → NIFTY FMCG    (6426369)
  CAPITAL_GOODS                → NIFTY INDIA MANUFACTURING (not listed)
  (unmapped sectors use NIFTY 50 as fallback)

Run: venv/bin/python3 backtest_sector_kite.py

Requires valid KITE_ACCESS_TOKEN in environment.
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta, date, time as dt_time
from collections import defaultdict

import openpyxl
from kiteconnect import KiteConnect

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Sector → NSE Index instrument token mapping ────────────────────────────────
# These are Kite instrument tokens for NSE sectoral indices.
# Verify / update via: kite.instruments("NSE") filtered by instrument_type="EQ", segment="INDICES"
SECTOR_INDEX_TOKENS = {
    "BANKING":            260105,   # NIFTY BANK
    "FINANCIAL_SERVICES": 260105,   # NIFTY BANK (closest proxy)
    "IT":                 5459490,  # NIFTY IT — verify this token
    "PHARMA":             5577794,  # NIFTY PHARMA — verify this token
    "AUTO":               5582082,  # NIFTY AUTO — verify this token
    "ENERGY":             14385,    # NIFTY ENERGY — verify this token
    "INFRASTRUCTURE":     14385,    # NIFTY INFRASTRUCTURE
    "METAL":              234249,   # NIFTY METAL — verify this token
    "FMCG":               6426369,  # NIFTY FMCG — verify this token
    "CONSUMER":           6426369,  # NIFTY FMCG as proxy
}
NIFTY50_TOKEN = config.NIFTY_50_TOKEN  # 256265 — fallback for unmapped sectors

PNL_FILE = "data/alerts/alert_pnl_tracker.xlsx"
SECTOR_MAP_FILE = "data/stock_sectors.json"
CANDLE_CACHE_FILE = "data/backtest_sector_kite_cache.json"

LOOKBACK_DAYS = 90  # How many calendar days of history to fetch


def load_pnl_alerts():
    """Load clean drop alerts from alert_pnl_tracker.xlsx."""
    wb = openpyxl.load_workbook(PNL_FILE)
    ws = wb.active
    alerts = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]: continue
        direction = str(row[4]).lower() if row[4] else ""
        if "drop" not in direction: continue
        date_str = str(row[0])
        time_str = str(row[1]) if row[1] else "09:25"
        symbol = row[2]
        alert_price = row[6]
        pnl_15m = row[10]
        pnl_30m = row[11]
        if not alert_price or pnl_15m is None: continue
        try:
            alert_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except Exception:
            try:
                alert_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
        alerts.append({
            "date": date_str,
            "datetime": alert_dt,
            "symbol": symbol,
            "alert_price": float(alert_price),
            "pnl_15m": float(pnl_15m),
            "pnl_30m": float(pnl_30m) if pnl_30m is not None else None,
        })
    return alerts


def load_candle_cache():
    if os.path.exists(CANDLE_CACHE_FILE):
        with open(CANDLE_CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_candle_cache(cache):
    with open(CANDLE_CACHE_FILE, "w") as f:
        json.dump(cache, f)


def get_day_open_and_price_at(kite, token, target_date: date, target_time: dt_time, cache) -> tuple:
    """
    Get the day's open price and the index price at target_time on target_date.
    Returns (day_open, price_at_time) or (None, None) on failure.
    Uses cache to avoid repeated API calls.
    """
    cache_key = f"{token}_{target_date}"
    if cache_key in cache:
        candles = cache[cache_key]
    else:
        try:
            from_dt = datetime.combine(target_date, dt_time(9, 0))
            to_dt = datetime.combine(target_date, dt_time(15, 30))
            raw = kite.historical_data(token, from_dt, to_dt, "5minute")
            candles = [
                {"date": c["date"].isoformat() if hasattr(c["date"], "isoformat") else str(c["date"]),
                 "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
                for c in raw
            ]
            cache[cache_key] = candles
            time.sleep(0.3)  # Respect Kite rate limits
        except Exception as e:
            logger.warning(f"Failed to fetch candles for token {token} on {target_date}: {e}")
            return None, None

    if not candles:
        return None, None

    # Day open = first candle's open
    day_open = candles[0]["open"]

    # Price at target_time = close of the candle that contains target_time
    price_at = None
    for c in candles:
        try:
            candle_dt = datetime.fromisoformat(c["date"]) if isinstance(c["date"], str) else c["date"]
            candle_time = candle_dt.time()
        except Exception:
            continue
        # Each 5-min candle covers candle_time to candle_time+5min
        candle_end = (datetime.combine(target_date, candle_time) + timedelta(minutes=5)).time()
        if candle_time <= target_time < candle_end:
            price_at = c["close"]
            break
        elif candle_time <= target_time:
            price_at = c["close"]  # keep updating; last one before target_time wins

    return day_open, price_at


def calc_stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "win_rate": None, "avg": None, "n_wins": 0, "n_losses": 0}
    wins = [v for v in vals if v < 0]
    losses = [v for v in vals if v >= 0]
    return {
        "n": len(vals),
        "win_rate": len(wins) / len(vals) * 100,
        "avg": sum(vals) / len(vals),
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "n_wins": len(wins),
        "n_losses": len(losses),
    }


def run():
    if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
        print("ERROR: KITE_API_KEY and KITE_ACCESS_TOKEN required.")
        print("Set them in environment and retry.")
        return

    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)
    logger.info("Kite connected")

    with open(SECTOR_MAP_FILE) as f:
        sector_map = json.load(f)

    alerts = load_pnl_alerts()
    cache = load_candle_cache()

    # Filter to last LOOKBACK_DAYS
    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    alerts = [a for a in alerts if a["datetime"] >= cutoff]
    logger.info(f"Loaded {len(alerts)} drop alerts in last {LOOKBACK_DAYS} days")

    buckets = {
        "RISING": {"15m": [], "30m": [], "sector_pcts": []},
        "FLAT": {"15m": [], "30m": [], "sector_pcts": []},
        "FALLING": {"15m": [], "30m": [], "sector_pcts": []},
    }
    skipped = 0

    for i, a in enumerate(alerts):
        symbol = a["symbol"]
        sector = sector_map.get(symbol)
        token = SECTOR_INDEX_TOKENS.get(sector, NIFTY50_TOKEN)

        alert_date = a["datetime"].date()
        alert_time = a["datetime"].time()

        day_open, price_at_alert = get_day_open_and_price_at(kite, token, alert_date, alert_time, cache)

        if day_open is None or price_at_alert is None or day_open == 0:
            logger.debug(f"  Skipped {symbol} on {alert_date}: no index data")
            skipped += 1
            continue

        sector_pct = (price_at_alert - day_open) / day_open * 100

        if sector_pct < -0.3:
            cat = "FALLING"
        elif sector_pct > 0.3:
            cat = "RISING"
        else:
            cat = "FLAT"

        buckets[cat]["15m"].append(a["pnl_15m"])
        buckets[cat]["30m"].append(a["pnl_30m"])
        buckets[cat]["sector_pcts"].append(sector_pct)

        logger.info(f"  [{i+1}/{len(alerts)}] {symbol} ({sector or 'unknown'}) "
                    f"sector={sector_pct:+.2f}% → {cat} | P&L 15m: {a['pnl_15m']:+.2f}%")

        # Save cache every 10 alerts
        if (i + 1) % 10 == 0:
            save_candle_cache(cache)

    save_candle_cache(cache)

    # ── Results ──────────────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("BACKTEST RESULTS: Sector Context vs Short Signal Quality")
    print(f"{'='*72}")
    print(f"Alerts analyzed: {len(alerts) - skipped} | Skipped (no index data): {skipped}")
    print(f"\nSector state at alert time (from Kite intraday index data):")
    print(f"  RISING  = index +0.3%+ from day open   ← stock drop is stock-specific")
    print(f"  FLAT    = -0.3% to +0.3%")
    print(f"  FALLING = index -0.3%- from day open   ← broad market/sector weakness")

    print(f"\n{'─'*72}")
    print(f"{'Category':<12}  {'N':>4}  {'AvgSector':>10}  {'WinRate15m':>11}  {'Avg15m':>8}  {'WinRate30m':>11}  {'Avg30m':>8}")
    print(f"{'─'*72}")

    for cat in ["RISING", "FLAT", "FALLING"]:
        b = buckets[cat]
        s15 = calc_stats(b["15m"])
        s30 = calc_stats(b["30m"])
        sp = b["sector_pcts"]
        avg_s = sum(sp) / len(sp) if sp else 0

        wr15 = f"{s15['win_rate']:.0f}%" if s15["win_rate"] is not None else "N/A"
        avg15 = f"{s15['avg']:+.2f}%" if s15["avg"] is not None else "N/A"
        wr30 = f"{s30['win_rate']:.0f}%" if s30["win_rate"] is not None else "N/A"
        avg30 = f"{s30['avg']:+.2f}%" if s30["avg"] is not None else "N/A"

        print(f"{cat:<12}  {s15['n']:>4}  {avg_s:>+9.2f}%  {wr15:>11}  {avg15:>8}  {wr30:>11}  {avg30:>8}")

    # Verdict
    rising = calc_stats(buckets["RISING"]["15m"])
    falling = calc_stats(buckets["FALLING"]["15m"])

    print(f"\n{'─'*72}")
    print("VERDICT:")
    if rising["n"] >= 5 and falling["n"] >= 5:
        diff = (rising["win_rate"] or 0) - (falling["win_rate"] or 0)
        avg_diff = (rising["avg"] or 0) - (falling["avg"] or 0)
        if diff > 5:
            print(f"  ✅ CONFIRMED (+{diff:.0f}pp): Stock-specific drops (vs rising sector) ARE better shorts")
        elif diff > 0:
            print(f"  ⚠️  MARGINAL (+{diff:.0f}pp): Slight edge for stock-specific drops")
        elif diff < -5:
            print(f"  ❌ NOT CONFIRMED ({diff:.0f}pp): Sector-wide weakness produced better shorts")
        else:
            print(f"  ➖ NEUTRAL ({diff:+.0f}pp): No meaningful difference from sector context")
        print(f"     Avg 15m return: RISING sector={rising['avg']:+.2f}% vs FALLING sector={falling['avg']:+.2f}%")
    else:
        print(f"  ⚠️  Small samples — need more data. Accumulate ~30+ alerts per category.")
        print(f"     Current: RISING={rising['n']}, FLAT={calc_stats(buckets['FLAT']['15m'])['n']}, FALLING={falling['n']}")

    print(f"{'='*72}\n")


if __name__ == "__main__":
    run()
