#!/usr/bin/env python3
"""
Test Token Validation Flow
Simulates what happens in main.py when checking token
"""

import sys
import logging
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def test_token_validation():
    """Test the token validation logic from main.py"""

    logger.info("=" * 70)
    logger.info("Testing Token Validation Flow")
    logger.info("=" * 70)

    # Check Kite Connect token validity
    if config.DATA_SOURCE == 'kite':
        logger.info("Data source is Kite - checking token validity...")
        try:
            from token_manager import TokenManager
            manager = TokenManager()
            is_valid, message, hours_remaining = manager.is_token_valid()

            if not is_valid:
                logger.error(f"Kite Connect token is invalid: {message}")
                logger.error("=" * 60)
                logger.error("ACTION REQUIRED: Run the following command to refresh your token:")
                logger.error("  python3 generate_kite_token.py")
                logger.error("=" * 60)

                # Send Telegram alert
                warning = manager.get_expiry_warning_message()
                if warning:
                    try:
                        from telegram_notifier import TelegramNotifier
                        telegram = TelegramNotifier()
                        telegram._send_message(warning)
                        logger.info("✅ Sent token expiry alert via Telegram")
                    except Exception as e:
                        logger.error(f"Failed to send Telegram alert: {e}")

                logger.info("\n❌ TEST RESULT: Token validation would BLOCK monitoring startup")
                return False
            else:
                logger.info(f"✅ Token valid: {message}")
                if hours_remaining < 2:
                    logger.warning(f"⚠️ Token expires soon! ({hours_remaining:.1f} hours remaining)")
                    logger.warning("Consider refreshing token before next run: python3 generate_kite_token.py")

                logger.info("\n✅ TEST RESULT: Token validation would ALLOW monitoring to proceed")
                return True

        except Exception as e:
            logger.error(f"Error checking token validity: {e}")
            logger.warning("Proceeding anyway, but monitoring may fail if token is invalid.")
            return None
    else:
        logger.info(f"Data source is '{config.DATA_SOURCE}' - token validation not needed")
        return True

if __name__ == "__main__":
    logger.info("")
    result = test_token_validation()
    logger.info("")
    logger.info("=" * 70)

    if result is True:
        logger.info("✅ Token is valid - monitoring would start normally")
        sys.exit(0)
    elif result is False:
        logger.info("❌ Token is invalid - monitoring would be blocked")
        sys.exit(1)
    else:
        logger.info("⚠️ Token validation encountered an error")
        sys.exit(2)
