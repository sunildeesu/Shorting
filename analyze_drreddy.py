#!/usr/bin/env python3
"""
Analyze DRREDDY movement on October 29, 2025
Check if system would have detected the fall
"""

import sys
import logging
from datetime import datetime
from kiteconnect import KiteConnect
import pandas as pd
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def analyze_drreddy_oct29():
    """Analyze DRREDDY on Oct 29, 2025"""

    # Initialize Kite
    kite = KiteConnect(api_key=config.KITE_API_KEY)
    kite.set_access_token(config.KITE_ACCESS_TOKEN)

    # Get DRREDDY instrument token
    instruments = kite.instruments("NSE")
    drreddy_token = None
    for instrument in instruments:
        if instrument['tradingsymbol'] == 'DRREDDY' and instrument['segment'] == 'NSE':
            drreddy_token = instrument['instrument_token']
            break

    if not drreddy_token:
        logger.error("DRREDDY instrument token not found")
        return

    logger.info(f"DRREDDY Instrument Token: {drreddy_token}")

    # Fetch 5-minute candles for Oct 29, 2025
    from_date = datetime(2025, 10, 29, 9, 0, 0)
    to_date = datetime(2025, 10, 29, 15, 30, 0)

    logger.info(f"Fetching 5-minute candles for DRREDDY on Oct 29, 2025...")

    data = kite.historical_data(
        instrument_token=drreddy_token,
        from_date=from_date,
        to_date=to_date,
        interval="5minute"
    )

    if not data:
        logger.error("No data returned")
        return

    # Convert to DataFrame
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['date'])
    df = df.sort_values('timestamp')

    logger.info(f"\nTotal candles: {len(df)}")
    logger.info(f"Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    logger.info(f"Price range: ₹{df['close'].min():.2f} to ₹{df['close'].max():.2f}")

    # Calculate drop percentages for each 10-minute interval
    logger.info("\n" + "="*80)
    logger.info("ANALYZING 10-MINUTE INTERVALS (Same as live monitoring)")
    logger.info("="*80)

    drops_detected = []

    for i in range(2, len(df)):
        prev_candle = df.iloc[i-2]  # 10 minutes ago
        curr_candle = df.iloc[i]

        # Only same day
        if prev_candle['timestamp'].date() != curr_candle['timestamp'].date():
            continue

        prev_close = prev_candle['close']
        curr_close = curr_candle['close']

        if prev_close > 0:
            drop_percent = ((prev_close - curr_close) / prev_close) * 100
            change_percent = ((curr_close - prev_close) / prev_close) * 100

            # Show all intervals with > 1% movement
            if abs(change_percent) >= 1.0:
                direction = "📉 DROP" if drop_percent > 0 else "📈 RISE"
                alert_flag = " ⚠️ ALERT TRIGGERED!" if drop_percent >= 2.0 else ""

                logger.info(f"{curr_candle['timestamp']} | {direction} {abs(change_percent):.2f}% | "
                           f"₹{prev_close:.2f} → ₹{curr_close:.2f} | "
                           f"(10 min ago: {prev_candle['timestamp'].strftime('%H:%M')}){alert_flag}")

                if drop_percent >= 2.0:
                    drops_detected.append({
                        'time': curr_candle['timestamp'],
                        'prev_time': prev_candle['timestamp'],
                        'drop_percent': drop_percent,
                        'prev_price': prev_close,
                        'curr_price': curr_close,
                        'volume': curr_candle['volume']
                    })

    # Summary
    logger.info("\n" + "="*80)
    logger.info("SUMMARY")
    logger.info("="*80)

    if drops_detected:
        logger.info(f"✅ YES! System would have sent {len(drops_detected)} alert(s):\n")
        for idx, drop in enumerate(drops_detected, 1):
            logger.info(f"Alert {idx}:")
            logger.info(f"  Time: {drop['time'].strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"  Drop: {drop['drop_percent']:.2f}% in 10 minutes")
            logger.info(f"  Price: ₹{drop['prev_price']:.2f} → ₹{drop['curr_price']:.2f}")
            logger.info(f"  Change: ₹{drop['prev_price'] - drop['curr_price']:.2f}")
            logger.info(f"  Volume: {drop['volume']:,}")
            logger.info(f"  💊 PHARMA STOCK - Would have flagged as shorting opportunity!")
            logger.info("")
    else:
        logger.info("❌ No 2%+ drops in 10-minute intervals detected")
        logger.info("The fall may have been:")
        logger.info("  - Gradual decline over longer period")
        logger.info("  - Single large gap (not gradual 10-min decline)")
        logger.info("  - Less than 2% in any 10-minute window")

    # Show the biggest single drop
    logger.info("\n" + "="*80)
    logger.info("BIGGEST SINGLE 5-MINUTE DROP")
    logger.info("="*80)

    max_drop = 0
    max_drop_info = None

    for i in range(1, len(df)):
        prev = df.iloc[i-1]['close']
        curr = df.iloc[i]['close']
        drop = ((prev - curr) / prev) * 100

        if drop > max_drop:
            max_drop = drop
            max_drop_info = {
                'time': df.iloc[i]['timestamp'],
                'prev_price': prev,
                'curr_price': curr
            }

    if max_drop_info:
        logger.info(f"Time: {max_drop_info['time']}")
        logger.info(f"Drop: {max_drop:.2f}% in 5 minutes")
        logger.info(f"Price: ₹{max_drop_info['prev_price']:.2f} → ₹{max_drop_info['curr_price']:.2f}")

    # Show full price movement
    logger.info("\n" + "="*80)
    logger.info("COMPLETE PRICE MOVEMENT (5-MINUTE CANDLES)")
    logger.info("="*80)

    for idx, row in df.iterrows():
        logger.info(f"{row['timestamp'].strftime('%H:%M')} | "
                   f"O: ₹{row['open']:.2f} | H: ₹{row['high']:.2f} | "
                   f"L: ₹{row['low']:.2f} | C: ₹{row['close']:.2f} | "
                   f"Vol: {row['volume']:,}")

if __name__ == "__main__":
    try:
        analyze_drreddy_oct29()
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
