#!/usr/bin/env python3
"""
Manual Volume Profile Runner - Bypasses trading day check
Use this to analyze historical data or run on weekends
"""

import sys
import logging
from datetime import datetime, timedelta, time as dt_time
from volume_profile_analyzer import VolumeProfileAnalyzer
from kiteconnect import KiteConnect
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/volume_profile_manual_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Run volume profile analysis - bypasses trading day check"""

    # Determine target date (yesterday)
    target_date = (datetime.now() - timedelta(days=1)).date()

    print("="*70)
    print("MANUAL VOLUME PROFILE ANALYSIS")
    print("="*70)
    print(f"Target Date: {target_date.strftime('%Y-%m-%d')} (Yesterday)")
    print(f"Data Range: 9:15 AM - 3:25 PM")
    print("="*70)
    print()

    try:
        # Create analyzer
        analyzer = VolumeProfileAnalyzer(execution_time="3:25PM")

        # Get components
        logger.info("Fetching stock list...")
        stocks = analyzer.fo_stocks
        logger.info(f"Loaded {len(stocks)} F&O stocks")

        # Override fetch method to use target date
        original_fetch = analyzer._fetch_intraday_1min_data

        def fetch_for_target_date(symbol):
            """Fetch data for specific target date"""
            if symbol not in analyzer.instrument_tokens:
                logger.warning(f"{symbol}: Instrument token not found")
                return []

            try:
                instrument_token = analyzer.instrument_tokens[symbol]

                # Use target date instead of today
                from_date = datetime.combine(target_date, dt_time(9, 15))
                to_date = datetime.combine(target_date, dt_time(15, 25))

                # Fetch 1-minute candles
                data = analyzer.kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=from_date,
                    to_date=to_date,
                    interval="minute"
                )

                if not data:
                    logger.warning(f"{symbol}: No data for {target_date}")
                    return []

                logger.debug(f"{symbol}: Fetched {len(data)} candles for {target_date}")
                return data

            except Exception as e:
                logger.error(f"{symbol}: Error fetching data - {e}")
                return []

        # Replace fetch method
        analyzer._fetch_intraday_1min_data = fetch_for_target_date

        # Run batch analysis
        logger.info(f"Starting volume profile analysis for {target_date}...")
        results = analyzer._batch_analyze(stocks)

        if not results:
            print("\n❌ No data available - market might be closed or API issue")
            return 1

        logger.info(f"Analysis complete: {len(results)} stocks processed")

        # Filter results
        successful = [r for r in results if r.get('success', False)]
        p_shaped = [r for r in successful if r['profile_shape'] == 'P-SHAPE']
        b_shaped = [r for r in successful if r['profile_shape'] == 'B-SHAPE']

        logger.info(f"Successful: {len(successful)}")
        logger.info(f"P-SHAPE: {len(p_shaped)}")
        logger.info(f"B-SHAPE: {len(b_shaped)}")

        # Generate report (use target date for filename)
        report_time = datetime.combine(target_date, dt_time(15, 25))
        report_path = analyzer.report_generator.generate_report(
            profile_results=successful,
            analysis_time=report_time,
            execution_window="3:25PM"
        )

        print(f"\n✅ Report generated: {report_path}")

        # Upload to Dropbox if enabled
        if config.VOLUME_PROFILE_ENABLE_DROPBOX:
            dropbox_link = analyzer._upload_to_dropbox(report_path)
            if dropbox_link:
                print(f"☁️  Dropbox link: {dropbox_link}")

        # Send Telegram if high-confidence patterns
        high_conf_p = [r for r in p_shaped if r['confidence'] >= config.VOLUME_PROFILE_MIN_CONFIDENCE]
        high_conf_b = [r for r in b_shaped if r['confidence'] >= config.VOLUME_PROFILE_MIN_CONFIDENCE]

        if high_conf_p or high_conf_b:
            try:
                analyzer.telegram.send_volume_profile_summary(
                    profile_results=successful,
                    analysis_time=report_time,
                    execution_window="3:25PM"
                )
                print("✅ Telegram alert sent")
            except Exception as e:
                logger.error(f"Telegram alert failed: {e}")

        print("\n" + "="*70)
        print("ANALYSIS COMPLETE")
        print("="*70)

        return 0

    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
