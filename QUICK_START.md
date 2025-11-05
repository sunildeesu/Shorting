# Quick Start Guide

## Daily Token Refresh (Every Morning Before 9:30 AM)

Run this command:

```bash
./generate_kite_token.py
```

Follow the prompts:
1. Enter your Kite API Key (from `.env` file)
2. Enter your Kite API Secret (from `.env` file)
3. Open the URL in your browser
4. Login to Zerodha Kite
5. Copy the `request_token` from redirected URL
6. Paste it back in the terminal
7. Choose 'y' to automatically update `.env` file

**Done!** Your token is now valid for 24 hours.

---

## Check System Status

```bash
./check_status.py
```

Shows comprehensive status:
- ✅ Monitoring status (running/stopped)
- ⏰ Last run time and last alert
- 📈 Market status (open/closed)
- 🔑 Token validity
- ⚙️ Cron job status
- ⚠️ Recent errors
- 💡 Recommendations

## Check Token Status Only

```bash
./token_manager.py
```

Shows:
- Token validity (valid/expired)
- Hours remaining until expiry
- Action required (if any)

---

## Install Daily Reminder (One-Time Setup)

```bash
./setup_token_reminder.sh
```

This will send you a Telegram alert every morning at 8:00 AM if your token needs refresh.

---

## Start Monitoring

```bash
./start_monitoring.sh
```

The monitoring system will automatically:
- Check if market is open
- Validate token before starting
- Send Telegram alert if token is invalid
- Exit gracefully with clear error messages

---

## Common Commands

| Task | Command |
|------|---------|
| **Check system status** | `./check_status.py` |
| Refresh token | `./generate_kite_token.py` |
| Check token status | `./token_manager.py` |
| Test daily reminder | `./check_token.py` |
| Start monitoring | `./start_monitoring.sh` |
| Install reminder | `./setup_token_reminder.sh` |
| View live logs | `tail -f logs/stock_monitor.log` |

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'kiteconnect'"

**Fixed!** All scripts now use the virtual environment automatically. Just run:

```bash
./generate_kite_token.py
```

No need to activate the virtual environment or use `python3` prefix.

### Token Expired

Simply run:

```bash
./generate_kite_token.py
```

### Not Getting Telegram Alerts

1. Check Telegram credentials in `.env`
2. Test manually: `./check_token.py`
3. View logs: `tail -f logs/token_reminder.log`

---

## Files Overview

| File | Purpose |
|------|---------|
| `generate_kite_token.py` | Generate new 24-hour token |
| `token_manager.py` | Check token status |
| `check_token.py` | Daily reminder script |
| `main.py` | Start stock monitoring |
| `setup_token_reminder.sh` | Install daily alerts |
| `TOKEN_MANAGEMENT.md` | Complete documentation |

---

## That's It!

The entire workflow is:

1. **Morning:** Run `./generate_kite_token.py` (takes 1 minute)
2. **Start:** Run `./start_monitoring.sh`
3. **Relax:** System monitors automatically every 5 minutes

You'll receive Telegram alerts for:
- Stock drops (10-min, 30-min, or volume spikes)
- Token expiry reminders (8:00 AM daily)
- System errors or issues

For detailed documentation, see `TOKEN_MANAGEMENT.md`.
