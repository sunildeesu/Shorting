#!/Users/sunilkumar/myProjects/ShortIndicator/venv/bin/python3
"""
Bull Flag Pattern Monitor — EOD Screener

Scans the NSE universe for bull flag (Stage 3) setups on daily charts.
Runs once after market close (~4 PM IST).

Stock universe and OHLCV cache are stored in SQLite (data/flag_pattern.db).
Run build_smallmid_universe.py first to seed the database.

Workflow:
  1. Load stock universe from flag_pattern.db
  2. For each stock: use cached OHLCV if fresh, else fetch from Kite and cache
  3. Detect flag patterns via FlagPatternDetector
  4. Send Telegram alerts for qualifying setups (with 3-day cooldown)
  5. Log all detections to flag_detections table

Author: Sunil Kumar Durganaik
"""

import logging
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd
from kiteconnect import KiteConnect

import config
from alert_history_manager import AlertHistoryManager
from flag_pattern_db import FlagPatternDB
from flag_pattern_detector import FlagPatternDetector
from telegram_notifiers.flag_alerts import FlagAlertNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


class FlagPatternMonitor:
    """EOD screener for bull flag Stage 3 setups."""

    def __init__(self):
        if not config.KITE_API_KEY or not config.KITE_ACCESS_TOKEN:
            raise ValueError("KITE_API_KEY and KITE_ACCESS_TOKEN must be set in .env")

        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        self.db = FlagPatternDB(config.FLAG_DB_PATH)
        self.detector = FlagPatternDetector()
        self.notifier = FlagAlertNotifier()
        self.alert_history = AlertHistoryManager()

        # Load universe from DB
        stocks_data = self.db.get_all_stocks(include_smallmid=config.FLAG_INCLUDE_SMALLMID)
        if not stocks_data:
            logger.warning(
                "Stock universe is empty! Run build_smallmid_universe.py first."
            )
        self.stocks_data = stocks_data  # list of dicts with symbol, instrument_token, segment

        counts = self.db.stock_count()
        logger.info(
            f"FlagPatternMonitor ready — {len(stocks_data)} stocks "
            f"(large_mid={counts.get('large_mid', 0)}, "
            f"smallmid={counts.get('smallmid', 0)})"
        )

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    def _fetch_from_kite(self, symbol: str, token: int) -> Optional[pd.DataFrame]:
        """Fetch ~100 trading days of daily OHLCV from Kite API."""
        to_dt = date.today()
        from_dt = to_dt - timedelta(days=config.FLAG_LOOKBACK_DAYS)

        try:
            data = self.kite.historical_data(
                instrument_token=token,
                from_date=from_dt,
                to_date=to_dt,
                interval='day',
            )
        except Exception as e:
            logger.warning(f"{symbol}: Kite fetch failed — {e}")
            return None

        if not data:
            return None

        df = pd.DataFrame(data)
        df.columns = df.columns.str.lower()
        return df

    def _get_ohlcv(self, symbol: str, token: int) -> Optional[pd.DataFrame]:
        """Return OHLCV DataFrame: use DB cache if fresh, else fetch and cache."""
        from_date = (date.today() - timedelta(days=config.FLAG_LOOKBACK_DAYS)).isoformat()

        if self.db.is_cache_fresh(symbol):
            df = self.db.get_ohlcv(symbol, from_date)
            if df is not None and len(df) >= 30:
                return df

        # Cache miss or stale — fetch from Kite
        df = self._fetch_from_kite(symbol, token)
        if df is None:
            return None

        # Persist to DB
        self.db.upsert_ohlcv(symbol, df)
        time.sleep(0.35)  # ~3 req/sec — stay within Kite rate limit

        return df

    # ------------------------------------------------------------------
    # Main scan
    # ------------------------------------------------------------------

    def run(self):
        logger.info("=" * 60)
        logger.info("Bull Flag Monitor — EOD Scan")
        logger.info(
            f"Universe: {len(self.stocks_data)} stocks | "
            f"smallmid={config.FLAG_INCLUDE_SMALLMID}"
        )
        logger.info(
            f"Filters: pole>={config.FLAG_MIN_POLE_PCT}% | "
            f"pullback<={config.FLAG_MAX_PULLBACK_PCT}% | "
            f"score>={config.FLAG_MIN_SCORE}"
        )
        logger.info("=" * 60)

        setups_found: List[Dict] = []
        alerts_sent = 0
        fetch_errors = 0
        cooldown_minutes = config.FLAG_COOLDOWN_DAYS * 24 * 60

        for i, stock in enumerate(self.stocks_data, 1):
            symbol = stock['symbol']
            token = stock['instrument_token']

            if i % 100 == 0:
                logger.info(
                    f"Progress: {i}/{len(self.stocks_data)} scanned, "
                    f"{len(setups_found)} setups so far"
                )

            df = self._get_ohlcv(symbol, token)
            if df is None or len(df) < 60:
                if df is None:
                    fetch_errors += 1
                continue

            result = self.detector.detect(df, symbol)
            if result is None:
                continue

            # Annotate with segment for logging context
            result['segment'] = stock.get('segment', 'unknown')
            setups_found.append(result)

            logger.info(
                f"FLAG: {symbol} [{stock.get('segment', '?')}] "
                f"score={result['score']} "
                f"pole={result['pole_gain_pct']}% "
                f"pullback={result['pullback_depth_pct']}% "
                f"flag={result['flag_days']}d"
            )

            # Cooldown check (3-day suppression per stock)
            should_alert = self.alert_history.should_send_alert(
                symbol, 'flag_pattern', cooldown_minutes=cooldown_minutes
            )

            telegram_sent = False
            if should_alert and config.ENABLE_FLAG_PATTERN_ALERTS:
                telegram_sent = self.notifier.send_alert(result)
                if telegram_sent:
                    alerts_sent += 1
            elif not should_alert:
                logger.debug(f"{symbol}: in cooldown — Telegram skipped")

            self.db.log_detection(result, telegram_sent)

        # Summary
        logger.info("=" * 60)
        logger.info(f"Scan complete: {len(self.stocks_data)} stocks scanned")
        logger.info(f"Flag setups found: {len(setups_found)}")
        logger.info(f"Telegram alerts sent: {alerts_sent}")
        logger.info(f"Fetch errors: {fetch_errors}")

        if setups_found:
            logger.info("Top setups by score:")
            for r in sorted(setups_found, key=lambda x: x['score'], reverse=True)[:10]:
                logger.info(
                    f"  {r['symbol']} [{r.get('segment','?')}]: "
                    f"score={r['score']} "
                    f"pole={r['pole_gain_pct']}% "
                    f"flag={r['flag_days']}d "
                    f"pullback={r['pullback_depth_pct']}%"
                )
        logger.info("=" * 60)

        return setups_found


def main():
    monitor = FlagPatternMonitor()
    monitor.run()


if __name__ == '__main__':
    main()
