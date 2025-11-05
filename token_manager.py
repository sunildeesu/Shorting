#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
Kite Connect Token Manager
Handles token validation, expiry tracking, and easy refresh workflow
"""

import os
import json
import logging
from datetime import datetime, timedelta
import webbrowser
from kiteconnect import KiteConnect
import config

logger = logging.getLogger(__name__)

TOKEN_METADATA_FILE = 'data/token_metadata.json'

class TokenManager:
    """Manages Kite Connect token lifecycle"""

    def __init__(self):
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.metadata_file = TOKEN_METADATA_FILE

    def save_token_metadata(self, access_token: str):
        """Save token generation timestamp"""
        metadata = {
            'access_token': access_token,
            'generated_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
        }

        os.makedirs(os.path.dirname(self.metadata_file), exist_ok=True)
        with open(self.metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Token metadata saved. Expires at: {metadata['expires_at']}")

    def load_token_metadata(self):
        """Load token metadata"""
        if not os.path.exists(self.metadata_file):
            return None

        try:
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        except:
            return None

    def is_token_valid(self) -> tuple:
        """
        Check if current token is valid

        Returns:
            Tuple of (is_valid: bool, message: str, hours_remaining: float)
        """
        if not config.KITE_ACCESS_TOKEN:
            return False, "No access token found in .env", 0

        # Check metadata
        metadata = self.load_token_metadata()

        if metadata:
            expires_at = datetime.fromisoformat(metadata['expires_at'])
            now = datetime.now()

            if now >= expires_at:
                return False, "Token has expired", 0

            hours_remaining = (expires_at - now).total_seconds() / 3600

            if hours_remaining < 1:
                return False, f"Token expires in {hours_remaining*60:.0f} minutes", hours_remaining

            return True, f"Token valid for {hours_remaining:.1f} hours", hours_remaining

        # No metadata, try to validate with API
        try:
            self.kite.set_access_token(config.KITE_ACCESS_TOKEN)
            profile = self.kite.profile()

            if profile:
                logger.warning("Token works but no metadata found. Assuming expires in 24h.")
                # Save metadata assuming token was just generated
                self.save_token_metadata(config.KITE_ACCESS_TOKEN)
                return True, "Token valid (no metadata, assumed fresh)", 24.0
        except Exception as e:
            return False, f"Token validation failed: {str(e)}", 0

        return False, "Unable to validate token", 0

    def get_expiry_warning_message(self) -> str:
        """Get formatted warning message for token expiry"""
        is_valid, message, hours_remaining = self.is_token_valid()

        if not is_valid:
            return f"""
⚠️ KITE TOKEN EXPIRED!

{message}

Action Required:
1. Run: python3 generate_kite_token.py
2. Follow the browser login
3. Token will be automatically updated

The monitoring system will NOT work until token is refreshed!
"""

        if hours_remaining < 2:
            return f"""
⚠️ KITE TOKEN EXPIRING SOON!

Token expires in {hours_remaining:.1f} hours

Recommended Action:
Run: python3 generate_kite_token.py

This will refresh your token for another 24 hours.
"""

        return None

    def open_token_refresh_browser(self):
        """Open browser for token refresh"""
        login_url = self.kite.login_url()
        logger.info(f"Opening browser for Kite Connect login...")
        logger.info(f"URL: {login_url}")

        try:
            webbrowser.open(login_url)
            return True
        except Exception as e:
            logger.error(f"Failed to open browser: {e}")
            return False

    def update_env_file(self, access_token: str):
        """Update .env file with new access token"""
        env_path = '.env'

        if not os.path.exists(env_path):
            logger.error(".env file not found")
            return False

        # Read current .env
        with open(env_path, 'r') as f:
            lines = f.readlines()

        # Update KITE_ACCESS_TOKEN line
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('KITE_ACCESS_TOKEN='):
                lines[i] = f'KITE_ACCESS_TOKEN={access_token}\n'
                updated = True
                break

        if not updated:
            # Add if not exists
            lines.append(f'KITE_ACCESS_TOKEN={access_token}\n')

        # Write back
        with open(env_path, 'w') as f:
            f.writelines(lines)

        logger.info("✅ Updated .env file with new access token")
        return True


def check_token_and_alert():
    """
    Check token validity and send Telegram alert if needed

    Returns:
        bool: True if token is valid, False otherwise
    """
    manager = TokenManager()
    is_valid, message, hours_remaining = manager.is_token_valid()

    warning_message = manager.get_expiry_warning_message()

    if warning_message:
        logger.warning(warning_message)

        # Send Telegram alert
        try:
            from telegram_notifier import TelegramNotifier
            telegram = TelegramNotifier()
            telegram._send_message(warning_message)
            logger.info("Sent token expiry alert via Telegram")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    return is_valid


if __name__ == "__main__":
    # Quick token check
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    manager = TokenManager()
    is_valid, message, hours_remaining = manager.is_token_valid()

    print("=" * 70)
    print("KITE CONNECT TOKEN STATUS")
    print("=" * 70)
    print(f"Status: {'✅ VALID' if is_valid else '❌ INVALID/EXPIRED'}")
    print(f"Message: {message}")

    if is_valid:
        print(f"Hours Remaining: {hours_remaining:.1f}")
        print(f"Expires At: {(datetime.now() + timedelta(hours=hours_remaining)).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("\n⚠️ Action Required:")
        print("Run: python3 generate_kite_token.py")

    print("=" * 70)
