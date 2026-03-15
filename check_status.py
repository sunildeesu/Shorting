#!/Users/sunildeesu/myProjects/ShortIndicator/venv/bin/python3
"""
System Status Checker
Shows if the monitoring system is active and running correctly
"""

import sys
import os
import subprocess
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

def check_cron_job():
    """Check if monitoring cron job is installed"""
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        if result.returncode == 0:
            cron_lines = result.stdout
            if 'main.py' in cron_lines:
                # Extract the cron schedule
                for line in cron_lines.split('\n'):
                    if 'main.py' in line and not line.strip().startswith('#'):
                        schedule = line.split()[0:5]
                        return True, ' '.join(schedule), line.strip()
                return False, None, None
            else:
                return False, None, None
        else:
            return False, None, None
    except Exception as e:
        return False, None, str(e)

def check_running_process():
    """Check if monitoring is currently running"""
    try:
        result = subprocess.run(['pgrep', '-f', 'main.py'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return True, pids
        return False, []
    except Exception as e:
        return False, []

def get_last_run_time():
    """Get timestamp of last monitoring run"""
    log_file = 'logs/stock_monitor.log'
    if os.path.exists(log_file):
        try:
            result = subprocess.run(['tail', '-100', log_file], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')

            # Find last "NSE Stock Monitor Starting" line
            for line in reversed(lines):
                if 'NSE Stock Monitor Starting' in line:
                    # Extract timestamp (first part of log line)
                    timestamp_str = line.split(' - ')[0] if ' - ' in line else None
                    return timestamp_str, True

            # If no start message, check for any recent activity
            if lines:
                last_line = lines[-1]
                timestamp_str = last_line.split(' - ')[0] if ' - ' in last_line else None
                return timestamp_str, False

        except Exception as e:
            return None, False
    return None, False

def get_last_alert_time():
    """Get timestamp of last alert sent"""
    log_file = 'logs/stock_monitor.log'
    if os.path.exists(log_file):
        try:
            result = subprocess.run(['tail', '-200', log_file], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')

            # Find last alert
            for line in reversed(lines):
                if 'Telegram message sent successfully' in line or 'ALERT:' in line:
                    timestamp_str = line.split(' - ')[0] if ' - ' in line else None
                    return timestamp_str

        except Exception as e:
            return None
    return None

def check_token_status():
    """Check Kite token validity"""
    try:
        from token_manager import TokenManager
        manager = TokenManager()
        is_valid, message, hours_remaining = manager.is_token_valid()
        return is_valid, message, hours_remaining
    except Exception as e:
        return None, f"Error: {e}", 0

def check_market_status():
    """Check if market is currently open"""
    try:
        from market_utils import is_market_open, get_market_status
        status = get_market_status()
        return status['is_open'], status
    except Exception as e:
        return None, None

def check_daily_reminder():
    """Check if daily token reminder is installed"""
    try:
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
        if 'com.nse.token.reminder' in result.stdout:
            return True
        return False
    except Exception as e:
        return False

def check_vwap_monitor_service():
    """Check if VWAP mover monitor launchd service is registered and running."""
    try:
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
        lines = result.stdout.split('\n')
        for line in lines:
            if 'com.shortindicator.vwapmovermonitor' in line:
                parts = line.split('\t')
                # parts: [PID or '-', last_exit_code, label]
                pid = parts[0].strip() if len(parts) >= 1 else '-'
                exit_code = parts[1].strip() if len(parts) >= 2 else '?'
                is_running = pid != '-' and pid != ''
                return True, is_running, pid, exit_code
        return False, False, None, None
    except Exception as e:
        return False, False, None, str(e)

def check_vwap_monitor_process():
    """Check if vwap_mover_monitor.py Python process is currently running."""
    try:
        result = subprocess.run(['pgrep', '-f', 'vwap_mover_monitor.py'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return True, pids
        return False, []
    except Exception as e:
        return False, []

def get_vwap_monitor_last_log():
    """Get last few lines from today's VWAP monitor log."""
    today = datetime.now().strftime('%Y%m%d')
    log_file = f'logs/vwap_mover_monitor_{today}.log'
    if os.path.exists(log_file):
        try:
            result = subprocess.run(['tail', '-5', log_file], capture_output=True, text=True)
            return log_file, result.stdout.strip()
        except Exception:
            return log_file, None
    return log_file, None

def get_recent_errors():
    """Get recent errors from log"""
    log_file = 'logs/stock_monitor.log'
    if os.path.exists(log_file):
        try:
            result = subprocess.run(['tail', '-100', log_file], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')

            errors = []
            for line in reversed(lines):
                if 'ERROR' in line or 'CRITICAL' in line:
                    errors.append(line)
                    if len(errors) >= 5:  # Show last 5 errors
                        break

            return list(reversed(errors))
        except Exception as e:
            return []
    return []

def main():
    """Display comprehensive system status"""

    logger.info("=" * 70)
    logger.info("NSE Stock Monitor - System Status")
    logger.info("=" * 70)
    logger.info("")

    # Check current time
    now = datetime.now()
    logger.info(f"📅 Current Time: {now.strftime('%Y-%m-%d %H:%M:%S %A')}")
    logger.info("")

    # === MONITORING STATUS ===
    logger.info("🔍 MONITORING STATUS")
    logger.info("-" * 70)

    # Check if running
    is_running, pids = check_running_process()
    if is_running:
        logger.info(f"✅ Status: RUNNING (PID: {', '.join(pids)})")
    else:
        logger.info("⚪ Status: Not currently running")

    # Check last run
    last_run, is_start = get_last_run_time()
    if last_run:
        status_text = "started" if is_start else "activity"
        logger.info(f"⏰ Last {status_text}: {last_run}")
    else:
        logger.info("⚪ Last run: No logs found")

    # Check last alert
    last_alert = get_last_alert_time()
    if last_alert:
        logger.info(f"📢 Last alert: {last_alert}")
    else:
        logger.info("⚪ Last alert: No alerts sent yet")

    logger.info("")

    # === CRON JOB STATUS ===
    logger.info("⏰ CRON JOB (Auto-run every 5 minutes)")
    logger.info("-" * 70)

    cron_installed, schedule, full_line = check_cron_job()
    if cron_installed:
        logger.info(f"✅ Cron job: INSTALLED")
        logger.info(f"   Schedule: {schedule} (every 5 minutes during market hours)")
        logger.info(f"   Command: {full_line}")
    else:
        logger.info("❌ Cron job: NOT INSTALLED")
        logger.info("   Run: ./start_monitoring.sh to install")

    logger.info("")

    # === MARKET STATUS ===
    logger.info("📈 MARKET STATUS")
    logger.info("-" * 70)

    is_open, market_status = check_market_status()
    if market_status:
        if is_open:
            logger.info("✅ Market: OPEN (monitoring active)")
        else:
            logger.info("⚪ Market: CLOSED (monitoring paused)")

        logger.info(f"   Trading day: {market_status['is_trading_day']}")
        logger.info(f"   Market hours: {market_status['is_market_hours']}")
    else:
        logger.info("⚠️ Market: Unable to check status")

    logger.info("")

    # === TOKEN STATUS ===
    logger.info("🔑 KITE CONNECT TOKEN")
    logger.info("-" * 70)

    import config
    if config.DATA_SOURCE == 'kite':
        is_valid, message, hours_remaining = check_token_status()
        if is_valid:
            logger.info(f"✅ Token: VALID ({message})")
            if hours_remaining < 2:
                logger.info(f"   ⚠️ WARNING: Token expires in {hours_remaining:.1f} hours!")
                logger.info(f"   Run: ./generate_kite_token.py")
        elif is_valid is False:
            logger.info(f"❌ Token: INVALID")
            logger.info(f"   Reason: {message}")
            logger.info(f"   Action: Run ./generate_kite_token.py")
        else:
            logger.info(f"⚠️ Token: Unable to validate")
    else:
        logger.info(f"⚪ Data source: {config.DATA_SOURCE} (token not needed)")

    logger.info("")

    # === DAILY REMINDER ===
    logger.info("⏰ DAILY TOKEN REMINDER (8:00 AM)")
    logger.info("-" * 70)

    reminder_installed = check_daily_reminder()
    if reminder_installed:
        logger.info("✅ Daily reminder: INSTALLED")
        logger.info("   Sends Telegram alert at 8:00 AM if token expired")
    else:
        logger.info("⚪ Daily reminder: NOT INSTALLED")
        logger.info("   Run: ./setup_token_reminder.sh to install")

    logger.info("")

    # === VWAP MOVER MONITOR ===
    logger.info("📊 VWAP MOVER MONITOR (LaunchAgent — 9:12 AM Mon–Fri)")
    logger.info("-" * 70)

    svc_registered, svc_running, svc_pid, svc_exit = check_vwap_monitor_service()
    proc_running, proc_pids = check_vwap_monitor_process()

    if not svc_registered:
        logger.info("❌ LaunchAgent: NOT REGISTERED")
        logger.info("   Run: launchctl load ~/Library/LaunchAgents/com.shortindicator.vwapmovermonitor.plist")
    elif svc_running:
        logger.info(f"✅ LaunchAgent: REGISTERED + RUNNING (PID: {svc_pid})")
    else:
        last_exit = f", last exit={svc_exit}" if svc_exit and svc_exit != '0' else ""
        logger.info(f"✅ LaunchAgent: REGISTERED (idle{last_exit})")
        logger.info("   Fires at 9:12 AM on market days")

    if proc_running:
        logger.info(f"✅ Monitor process: RUNNING (PID: {', '.join(proc_pids)})")
    else:
        logger.info("⚪ Monitor process: Not currently running")

    log_path, log_tail = get_vwap_monitor_last_log()
    if log_tail:
        logger.info(f"📄 Today's log ({log_path}):")
        for line in log_tail.split('\n'):
            logger.info(f"   {line}")
    else:
        logger.info(f"⚪ Today's log: {log_path} (not found)")

    logger.info("")

    # === RECENT ERRORS ===
    logger.info("⚠️ RECENT ERRORS")
    logger.info("-" * 70)

    errors = get_recent_errors()
    if errors:
        logger.info(f"Found {len(errors)} recent error(s):")
        logger.info("")
        for error in errors:
            logger.info(f"   {error}")
    else:
        logger.info("✅ No recent errors found")

    logger.info("")
    logger.info("=" * 70)

    # === SUMMARY ===
    logger.info("📊 SUMMARY")
    logger.info("-" * 70)

    issues = []

    if not cron_installed:
        issues.append("⚠️ Cron job not installed - run ./start_monitoring.sh")

    if config.DATA_SOURCE == 'kite':
        is_valid, _, hours_remaining = check_token_status()
        if not is_valid:
            issues.append("❌ Token expired - run ./generate_kite_token.py")
        elif hours_remaining < 2:
            issues.append("⚠️ Token expiring soon - refresh recommended")

    if not reminder_installed:
        issues.append("💡 Daily reminder not installed (optional)")

    if errors:
        issues.append(f"⚠️ {len(errors)} recent error(s) found - check logs")

    if issues:
        logger.info("Issues found:")
        for issue in issues:
            logger.info(f"  {issue}")
    else:
        if is_open:
            logger.info("✅ All systems operational - monitoring is active!")
        else:
            logger.info("✅ All systems ready - waiting for market to open")

    logger.info("")
    logger.info("=" * 70)
    logger.info("")
    logger.info("Useful Commands:")
    logger.info("  - View live logs:    tail -f logs/stock_monitor.log")
    logger.info("  - Refresh token:     ./generate_kite_token.py")
    logger.info("  - Check token:       ./token_manager.py")
    logger.info("  - Install cron:      ./start_monitoring.sh")
    logger.info("  - Manual run:        ./main.py")
    logger.info("")

if __name__ == "__main__":
    main()
