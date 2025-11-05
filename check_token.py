#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Daily Token Validity Checker
Runs every morning to check Kite Connect token validity and send alerts
"""

import sys
import logging
from datetime import datetime
from token_manager import TokenManager, check_token_and_alert

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    """Check token validity and send alerts"""
    logger.info("=" * 70)
    logger.info("Daily Kite Connect Token Check")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    try:
        # Check token and send alert if needed
        is_valid = check_token_and_alert()

        if is_valid:
            logger.info("✅ Token is valid - no action needed")
            return 0
        else:
            logger.warning("⚠️ Token is expired or expiring soon!")
            logger.warning("Telegram alert has been sent")
            logger.warning("Action required: Run python3 generate_kite_token.py")
            return 1

    except Exception as e:
        logger.error(f"Error checking token: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
