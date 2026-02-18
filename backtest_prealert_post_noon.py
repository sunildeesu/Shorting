#!/usr/bin/env python3
"""
Backtest: Pre-Alert (Early Warning) - First Alert Post 12 PM (2-Min Delayed Entry)

Strategy:
- Simulates pre-alert signals from raw minute-bar data
- Consider only the FIRST pre-alert per stock per day
- That first pre-alert must have come AFTER 12:00 PM IST
- Position taken 2 minutes after the pre-alert fires
- For DROP: short position (profit if price falls further)
- For RISE: long position (profit if price rises further)

Runs multiple scenarios:
1. STRICT: First pre-alert post 12 PM, excluding results days
2. WITH RESULTS: First pre-alert post 12 PM, including results days
3. ALL POST-NOON: All pre-alerts post 12 PM (not just first)
4. BENCHMARK: All pre-alerts (any time) for comparison
"""

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import statistics
import json
import os
import requests

import config

NOON_CUTOFF_HOUR = 12
ENTRY_DELAY_MINUTES = 2
EXIT_TIMES = [5, 10, 15, 20, 30]


class PreAlertBacktester:
    """Simulate pre-alert signals and backtest profitability."""

    def __init__(self):
        self.db_path = "data/central_quotes.db"
        self.conn = None

        # Early warning settings
        self.ew_threshold = config.EARLY_WARNING_THRESHOLD      # 1.0%
        self.ew_lookback = config.EARLY_WARNING_LOOKBACK        # 4 min
        self.ew_volume_mult = config.EARLY_WARNING_VOLUME_MULT  # 1.2x
        self.ew_cooldown = config.EARLY_WARNING_COOLDOWN        # 15 min

        # Filters
        self.require_obv = getattr(config, 'EARLY_WARNING_REQUIRE_OBV', True)
        self.require_vwap = getattr(config, 'EARLY_WARNING_REQUIRE_VWAP', True)

    def _get_db(self):
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, timeout=30)
        return self.conn

    def get_day_data(self, symbol: str, date_str: str):
        """Get all minute data for a symbol on a date."""
        cursor = self._get_db().cursor()
        cursor.execute("""
            SELECT timestamp, price, volume
            FROM stock_quotes
            WHERE symbol = ? AND date(timestamp) = ?
            AND time(timestamp) >= '09:15:00'
            AND time(timestamp) <= '15:30:00'
            ORDER BY timestamp ASC
        """, (symbol, date_str))
        return [{'timestamp': r[0], 'price': r[1], 'volume': r[2] or 0}
                for r in cursor.fetchall()]

    def calculate_obv(self, data):
        if len(data) < 2:
            return []
        obv = [0]
        for i in range(1, len(data)):
            v = data[i]['volume'] or 0
            if data[i]['price'] > data[i-1]['price']:
                obv.append(obv[-1] + v)
            elif data[i]['price'] < data[i-1]['price']:
                obv.append(obv[-1] - v)
            else:
                obv.append(obv[-1])
        return obv

    def check_obv_confirmation(self, data, idx, direction):
        if idx < 5:
            return True
        obv = self.calculate_obv(data[:idx+1])
        if len(obv) < 5:
            return True
        recent = obv[-5:]
        n = len(recent)
        x_mean = (n - 1) / 2
        y_mean = sum(recent) / n
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0
        avg_change = sum(abs(obv[i] - obv[i-1]) for i in range(1, len(obv))) / (len(obv) - 1) if len(obv) > 1 else 1
        normalized = slope / avg_change if avg_change > 0 else 0
        if direction == 'drop':
            return normalized < -0.1
        else:
            return normalized > 0.1

    def calculate_vwap(self, data, idx):
        total_pv = 0
        total_vol = 0
        for i in range(idx + 1):
            p = data[i]['price']
            v = data[i]['volume']
            if p and v and p > 0 and v > 0:
                total_pv += p * v
                total_vol += v
        return total_pv / total_vol if total_vol > 0 else 0

    def check_vwap_position(self, data, idx, direction):
        vwap = self.calculate_vwap(data, idx)
        if vwap == 0:
            return True
        price = data[idx]['price']
        if direction == 'drop':
            return price <= vwap * 1.002
        else:
            return price >= vwap * 0.998

    def check_signal(self, data, idx):
        """Check if early warning signal fires at index."""
        if idx < self.ew_lookback:
            return False, None, 0

        current = data[idx]
        prev = data[idx - self.ew_lookback]

        curr_price = current['price']
        prev_price = prev['price']
        curr_vol = current['volume']
        prev_vol = prev['volume']

        if not curr_price or not prev_price or curr_price <= 0 or prev_price <= 0:
            return False, None, 0

        # Volume check
        if prev_vol <= 0 or curr_vol <= 0:
            return False, None, 0
        if curr_vol / prev_vol < self.ew_volume_mult:
            return False, None, 0

        # Price change
        drop_pct = ((prev_price - curr_price) / prev_price) * 100
        rise_pct = ((curr_price - prev_price) / prev_price) * 100

        if drop_pct >= self.ew_threshold:
            if self.require_obv and not self.check_obv_confirmation(data, idx, 'drop'):
                return False, None, 0
            if self.require_vwap and not self.check_vwap_position(data, idx, 'drop'):
                return False, None, 0
            return True, 'DROP', drop_pct

        if rise_pct >= self.ew_threshold:
            if self.require_obv and not self.check_obv_confirmation(data, idx, 'rise'):
                return False, None, 0
            if self.require_vwap and not self.check_vwap_position(data, idx, 'rise'):
                return False, None, 0
            return True, 'RISE', rise_pct

        return False, None, 0

    def scan_all_prealerts(self, days: int = 60):
        """Scan all minute data and collect pre-alert signals."""
        cursor = self._get_db().cursor()
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT DISTINCT date(timestamp)
            FROM stock_quotes WHERE timestamp >= ?
            ORDER BY timestamp
        """, (cutoff,))
        dates = [r[0] for r in cursor.fetchall()]

        print(f"Scanning {len(dates)} trading days for pre-alert signals...")

        all_signals = []
        last_signal = {}  # symbol -> last signal timestamp for cooldown

        for date_idx, date_str in enumerate(dates):
            if date_idx % 3 == 0:
                print(f"  Processing {date_str}... ({date_idx+1}/{len(dates)})")

            cursor.execute("""
                SELECT DISTINCT symbol FROM stock_quotes
                WHERE date(timestamp) = ?
            """, (date_str,))
            symbols = [r[0] for r in cursor.fetchall()]

            for symbol in symbols:
                data = self.get_day_data(symbol, date_str)
                if len(data) < self.ew_lookback + max(EXIT_TIMES) + ENTRY_DELAY_MINUTES + 5:
                    continue

                for idx in range(self.ew_lookback, len(data)):
                    current_ts = data[idx]['timestamp']

                    # Cooldown check (15 min per stock)
                    cooldown_key = f"{symbol}_{date_str}"
                    if cooldown_key in last_signal:
                        try:
                            last_dt = datetime.strptime(last_signal[cooldown_key], '%Y-%m-%d %H:%M:%S')
                            curr_dt = datetime.strptime(current_ts, '%Y-%m-%d %H:%M:%S')
                            if (curr_dt - last_dt).total_seconds() < self.ew_cooldown * 60:
                                continue
                        except:
                            pass

                    fires, direction, signal_pct = self.check_signal(data, idx)
                    if not fires:
                        continue

                    signal_dt = datetime.strptime(current_ts, '%Y-%m-%d %H:%M:%S')

                    # Entry: 2 min after signal
                    entry_idx = idx + ENTRY_DELAY_MINUTES
                    if entry_idx >= len(data):
                        continue

                    entry_price = data[entry_idx]['price']
                    entry_time = data[entry_idx]['timestamp']

                    if not entry_price or entry_price <= 0:
                        continue

                    # Calculate P&L at each exit time
                    exits = {}
                    for exit_min in EXIT_TIMES:
                        exit_idx = entry_idx + exit_min
                        if exit_idx >= len(data):
                            continue

                        # Don't exit after 3:25 PM
                        exit_ts = data[exit_idx]['timestamp']
                        exit_dt = datetime.strptime(exit_ts, '%Y-%m-%d %H:%M:%S')
                        if exit_dt.hour > 15 or (exit_dt.hour == 15 and exit_dt.minute > 25):
                            continue

                        exit_price = data[exit_idx]['price']
                        if not exit_price or exit_price <= 0:
                            continue

                        if direction == 'DROP':
                            pnl_pct = ((entry_price - exit_price) / entry_price) * 100
                        else:
                            pnl_pct = ((exit_price - entry_price) / entry_price) * 100

                        exits[exit_min] = {
                            'exit_price': exit_price,
                            'exit_time': exit_ts,
                            'pnl_pct': pnl_pct,
                        }

                    if not exits:
                        continue

                    all_signals.append({
                        'symbol': symbol,
                        'date': date_str,
                        'direction': direction,
                        'signal_time': current_ts,
                        'signal_hour': signal_dt.hour,
                        'signal_pct': signal_pct,
                        'entry_price': entry_price,
                        'entry_time': entry_time,
                        'exits': exits,
                    })

                    # Update cooldown
                    last_signal[cooldown_key] = current_ts

        print(f"\nTotal pre-alert signals found: {len(all_signals)}")
        return all_signals

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


def load_results_schedule():
    historical_file = "data/results_cache/historical_results.json"
    if not os.path.exists(historical_file):
        return {}
    try:
        with open(historical_file, 'r') as f:
            data = json.load(f)
            return data.get('results_dates', {})
    except:
        return {}


def was_results_day(symbol, date, schedule):
    return date in schedule.get(symbol.upper(), [])


def filter_first_post_noon(signals):
    """Keep only first pre-alert per stock per day, if it's after noon."""
    by_stock_day = defaultdict(list)
    for s in signals:
        key = (s['symbol'], s['date'])
        by_stock_day[key].append(s)

    filtered = []
    for key, day_signals in by_stock_day.items():
        day_signals.sort(key=lambda x: x['signal_time'])
        first = day_signals[0]
        if first['signal_hour'] >= NOON_CUTOFF_HOUR:
            filtered.append(first)

    return filtered


def filter_all_post_noon(signals):
    """Keep all signals after noon."""
    return [s for s in signals if s['signal_hour'] >= NOON_CUTOFF_HOUR]


def analyze_scenario(signals, label):
    """Analyze a set of signals and print results."""
    results = {t: {'all': [], 'DROP': [], 'RISE': []} for t in EXIT_TIMES}
    day_results = defaultdict(lambda: {t: [] for t in EXIT_TIMES})

    for signal in signals:
        for exit_min in EXIT_TIMES:
            if exit_min not in signal['exits']:
                continue

            exit_data = signal['exits'][exit_min]
            trade = {
                'symbol': signal['symbol'],
                'date': signal['date'],
                'direction': signal['direction'],
                'signal_time': signal['signal_time'],
                'signal_hour': signal['signal_hour'],
                'entry_price': signal['entry_price'],
                'exit_price': exit_data['exit_price'],
                'pnl_pct': exit_data['pnl_pct'],
                'profitable': exit_data['pnl_pct'] > 0,
                'signal_pct': signal['signal_pct'],
            }

            results[exit_min]['all'].append(trade)
            results[exit_min][signal['direction']].append(trade)
            day_results[signal['date']][exit_min].append(trade)

    # Print results
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")
    print(f"  Signals: {len(signals)}")

    has_trades = any(results[t]['all'] for t in EXIT_TIMES)
    if not has_trades:
        print(f"  No trades found for this scenario.")
        return results, day_results

    print(f"\n  {'Exit':<7} {'Trades':<8} {'Win%':<8} {'Avg P&L':<10} {'Total P&L':<11} {'Avg Win':<10} {'Avg Loss':<10} {'MaxWin':<9} {'MaxLoss':<9}")
    print(f"  {'-'*85}")

    for exit_min in EXIT_TIMES:
        trades = results[exit_min]['all']
        if not trades:
            continue

        winners = [t for t in trades if t['profitable']]
        losers = [t for t in trades if not t['profitable']]
        all_pnl = [t['pnl_pct'] for t in trades]
        win_rate = len(winners) / len(trades) * 100
        avg_pnl = statistics.mean(all_pnl)
        total_pnl = sum(all_pnl)
        avg_win = statistics.mean([t['pnl_pct'] for t in winners]) if winners else 0
        avg_loss = statistics.mean([t['pnl_pct'] for t in losers]) if losers else 0

        print(f"  {exit_min}min{'':<3} {len(trades):<8} {win_rate:.1f}%{'':<3} {avg_pnl:+.3f}%{'':<3} {total_pnl:+.2f}%{'':<4} {avg_win:+.3f}%{'':<3} {avg_loss:+.3f}%{'':<3} {max(all_pnl):+.2f}%{'':<2} {min(all_pnl):+.2f}%")

    # Direction breakdown
    for direction in ['DROP', 'RISE']:
        dir_trades = results[10][direction]
        if not dir_trades:
            continue
        winners = [t for t in dir_trades if t['profitable']]
        all_pnl = [t['pnl_pct'] for t in dir_trades]
        win_rate = len(winners) / len(dir_trades) * 100
        avg_pnl = statistics.mean(all_pnl)
        total_pnl = sum(all_pnl)
        tag = "SHORT" if direction == "DROP" else "LONG"
        print(f"\n  {direction} ({tag}) @ 10min: {len(dir_trades)} trades | {win_rate:.1f}% win | {avg_pnl:+.3f}% avg | {total_pnl:+.2f}% total")

    # Print individual trades for small samples
    trades_10 = results[10]['all']
    if trades_10 and len(trades_10) <= 30:
        print(f"\n  Trade details (10min exit):")
        for t in sorted(trades_10, key=lambda x: x['date']):
            marker = "+" if t['profitable'] else "-"
            sig_time = t['signal_time'][11:16]
            print(f"    {marker} {t['date']} {t['symbol']:<15} {t['direction']:<5} Signal:{sig_time} Entry:Rs{t['entry_price']:>8.2f} Exit:Rs{t['exit_price']:>8.2f} P&L:{t['pnl_pct']:+.2f}%")

    return results, day_results


def print_detailed(results, day_results, label):
    """Print detailed analysis for a scenario."""
    trades_10 = results[10]['all']
    if not trades_10 or len(trades_10) < 5:
        return

    print(f"\n\n{'#'*80}")
    print(f"  DETAILED ANALYSIS: {label}")
    print(f"{'#'*80}")

    # P&L Distribution
    print(f"\n  P&L Distribution (10 min exit):")
    ranges = [
        ('Big Loss (< -2%)', lambda x: x < -2),
        ('Loss (-2% to -1%)', lambda x: -2 <= x < -1),
        ('Small Loss (-1% to 0%)', lambda x: -1 <= x < 0),
        ('Small Win (0% to 0.5%)', lambda x: 0 <= x < 0.5),
        ('Win (0.5% to 1%)', lambda x: 0.5 <= x < 1),
        ('Good Win (1% to 2%)', lambda x: 1 <= x < 2),
        ('Big Win (> 2%)', lambda x: x >= 2),
    ]
    for label_r, cond in ranges:
        count = sum(1 for t in trades_10 if cond(t['pnl_pct']))
        pct = count / len(trades_10) * 100
        bar = '#' * int(pct / 2)
        print(f"    {label_r:<25} {count:>4} ({pct:>5.1f}%) {bar}")

    # Time-of-day analysis
    print(f"\n  Time-of-Day (10min exit):")
    hour_buckets = defaultdict(list)
    for t in trades_10:
        hour_buckets[t['signal_hour']].append(t['pnl_pct'])

    print(f"    {'Hour':<10} {'Trades':<8} {'Win%':<8} {'Avg P&L':<10}")
    print(f"    {'-'*40}")
    for hour in sorted(hour_buckets.keys()):
        pnls = hour_buckets[hour]
        winners = sum(1 for p in pnls if p > 0)
        win_rate = winners / len(pnls) * 100
        avg_p = statistics.mean(pnls)
        print(f"    {hour}:00{'':<5} {len(pnls):<8} {win_rate:.1f}%{'':<3} {avg_p:+.3f}%")

    # Day-by-day
    print(f"\n  Day-by-Day (10min exit):")
    print(f"    {'Date':<12} {'Trades':<8} {'Win%':<8} {'Total P&L':<12} {'Avg P&L':<10}")
    print(f"    {'-'*55}")

    winning_days = 0
    total_days = 0
    cumulative = 0

    for date in sorted(day_results.keys()):
        trades = day_results[date][10]
        if not trades:
            continue
        total_days += 1
        pnls = [t['pnl_pct'] for t in trades]
        day_total = sum(pnls)
        cumulative += day_total
        winners = sum(1 for p in pnls if p > 0)
        win_rate = winners / len(pnls) * 100
        if day_total > 0:
            winning_days += 1
        marker = "+" if day_total > 0 else "-"
        print(f"    {date:<12} {len(trades):<8} {win_rate:.0f}%{'':<4} {day_total:+.2f}%{'':<5} {statistics.mean(pnls):+.3f}%  {marker}")

    if total_days > 0:
        print(f"\n    Winning Days: {winning_days}/{total_days} ({winning_days/total_days*100:.0f}%)")
        print(f"    Cumulative P&L: {cumulative:+.2f}%")

    # Top winners/losers
    sorted_trades = sorted(trades_10, key=lambda x: -x['pnl_pct'])
    n = min(5, len(sorted_trades))

    print(f"\n  Top {n} Winners (10min):")
    for t in sorted_trades[:n]:
        print(f"    {t['date']} {t['symbol']:<15} {t['direction']:<5} P&L: {t['pnl_pct']:+.2f}%")

    print(f"\n  Top {n} Losers (10min):")
    for t in sorted_trades[-n:]:
        print(f"    {t['date']} {t['symbol']:<15} {t['direction']:<5} P&L: {t['pnl_pct']:+.2f}%")


def generate_telegram_report(scenario_results):
    """Generate HTML-formatted Telegram report."""
    lines = []
    lines.append("<b>PRE-ALERT BACKTEST: POST 12PM</b>")
    lines.append("<b>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</b>")
    lines.append("")
    lines.append(f"<b>Signal:</b> Pre-alert (1% in 4min + OBV/VWAP)")
    lines.append(f"<b>Filter:</b> First per stock/day, post 12 PM")
    lines.append(f"<b>Entry:</b> 2 min after signal")
    lines.append(f"<b>Period:</b> Last 2 months")
    lines.append("")

    # Scenario comparison
    lines.append("<b>SCENARIO COMPARISON (10min exit)</b>")
    lines.append("<pre>")
    lines.append(f"{'Scenario':<28}{'N':<5}{'Win%':<7}{'AvgP&L':<9}")
    lines.append("-" * 49)

    scenario_labels = [
        ("s1", "1. First Post-12PM (NoRes)"),
        ("s2", "2. First Post-12PM (InclRes)"),
        ("s3", "3. All Post-12PM"),
        ("s4", "4. All (Benchmark)"),
    ]

    for key, label in scenario_labels:
        res = scenario_results.get(key, {})
        trades = res.get(10, {}).get('all', []) if res else []
        if trades:
            winners = [t for t in trades if t['profitable']]
            win_rate = len(winners) / len(trades) * 100
            avg_pnl = statistics.mean([t['pnl_pct'] for t in trades])
            lines.append(f"{label:<28}{len(trades):<5}{win_rate:.0f}%{'':<3}{avg_pnl:+.2f}%")
        else:
            lines.append(f"{label:<28}{'0':<5}{'N/A':<7}{'N/A'}")

    lines.append("</pre>")

    # Best scenario details
    for key in ['s1', 's2', 's3', 's4']:
        res = scenario_results.get(key, {})
        trades_10 = res.get(10, {}).get('all', []) if res else []
        if len(trades_10) >= 3:
            lines.append("")
            lines.append(f"<b>DETAILED: {dict(scenario_labels)[key]}</b>")
            lines.append("<pre>")
            lines.append(f"{'Exit':<6}{'N':<5}{'Win%':<7}{'AvgP&L':<9}{'Total':<9}")
            lines.append("-" * 36)

            for exit_min in EXIT_TIMES:
                trades = res.get(exit_min, {}).get('all', [])
                if not trades:
                    continue
                winners = [t for t in trades if t['profitable']]
                all_pnl = [t['pnl_pct'] for t in trades]
                win_rate = len(winners) / len(trades) * 100
                avg_pnl = statistics.mean(all_pnl)
                total_pnl = sum(all_pnl)
                lines.append(f"{exit_min}min {len(trades):<5}{win_rate:.0f}%{'':<3}{avg_pnl:+.2f}%{'':<3}{total_pnl:+.1f}%")

            lines.append("</pre>")

            for direction in ['DROP', 'RISE']:
                dir_trades = res.get(10, {}).get(direction, [])
                if not dir_trades:
                    continue
                dir_winners = [t for t in dir_trades if t['profitable']]
                dir_win_rate = len(dir_winners) / len(dir_trades) * 100
                dir_avg_pnl = statistics.mean([t['pnl_pct'] for t in dir_trades])
                emoji = "🔴" if direction == "DROP" else "🟢"
                lines.append(f"{emoji} {direction}: {len(dir_trades)} trades, {dir_win_rate:.0f}% win, {dir_avg_pnl:+.2f}% avg")

            break

    # Verdict
    lines.append("")
    lines.append("<b>VERDICT</b>")

    best_res = None
    for key in ['s1', 's3', 's4']:
        res = scenario_results.get(key, {})
        if res and res.get(10, {}).get('all', []):
            best_res = res
            break

    if best_res:
        trades = best_res[10]['all']
        winners = [t for t in trades if t['profitable']]
        win_rate = len(winners) / len(trades) * 100
        avg_pnl = statistics.mean([t['pnl_pct'] for t in trades])

        if win_rate >= 55 and avg_pnl > 0:
            lines.append("✅ WORTH TAKING - Pre-alert has edge post noon")
        elif win_rate >= 50 and avg_pnl > 0:
            lines.append("⚠️ MARGINAL - Use with risk mgmt")
        elif win_rate >= 45:
            lines.append("⚠️ WEAK - Need additional filters")
        else:
            lines.append("❌ AVOID - Not profitable post noon")

        lines.append(f"Win: {win_rate:.0f}% | Avg P&L: {avg_pnl:+.2f}%")

        if len(trades) < 20:
            lines.append(f"⚠️ Small sample ({len(trades)} trades)")
    else:
        lines.append("❌ Insufficient data")

    lines.append("")
    lines.append(f"<i>Generated: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}</i>")

    return "\n".join(lines)


def send_telegram(message):
    bot_token = config.TELEGRAM_BOT_TOKEN
    channel_id = config.TELEGRAM_CHANNEL_ID
    if not bot_token or not channel_id:
        print("Telegram not configured!")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    chunks = [message] if len(message) <= 4096 else []
    if not chunks:
        current = ""
        for line in message.split("\n"):
            if len(current) + len(line) + 1 > 4000:
                chunks.append(current)
                current = line
            else:
                current += "\n" + line if current else line
        if current:
            chunks.append(current)

    for chunk in chunks:
        try:
            resp = requests.post(url, json={
                "chat_id": channel_id, "text": chunk, "parse_mode": "HTML"
            }, timeout=10)
            resp.raise_for_status()
            print(f"Telegram sent ({len(chunk)} chars)")
        except Exception as e:
            print(f"Telegram failed: {e}")
            return False
    return True


def run_backtest(days=60, send_telegram_flag=False):
    bt = PreAlertBacktester()

    print(f"\n{'='*80}")
    print(f"  PRE-ALERT BACKTEST: POST 12 PM (2-MIN DELAYED ENTRY)")
    print(f"  Signal: {bt.ew_threshold}% in {bt.ew_lookback}min + Vol {bt.ew_volume_mult}x + OBV={bt.require_obv} VWAP={bt.require_vwap}")
    print(f"  Entry: {ENTRY_DELAY_MINUTES} min after signal | Period: Last {days} days")
    print(f"{'='*80}")

    try:
        # Scan all pre-alerts
        all_signals = bt.scan_all_prealerts(days)

        if not all_signals:
            print("No pre-alert signals found!")
            return

        # Load results schedule
        schedule = load_results_schedule()
        non_results = [s for s in all_signals if not was_results_day(s['symbol'], s['date'], schedule)]
        results_excluded = len(all_signals) - len(non_results)
        print(f"Excluded {results_excluded} signals on results days")

        # Count post-noon distribution
        post_noon_total = sum(1 for s in all_signals if s['signal_hour'] >= NOON_CUTOFF_HOUR)
        print(f"Post-noon signals: {post_noon_total}/{len(all_signals)} ({post_noon_total/len(all_signals)*100:.1f}%)")

        # Hour distribution
        hour_dist = defaultdict(int)
        for s in all_signals:
            hour_dist[s['signal_hour']] += 1
        print(f"\nSignal hour distribution:")
        for h in sorted(hour_dist.keys()):
            print(f"  {h}:00 - {hour_dist[h]} signals")

        # ===== SCENARIOS =====
        scenario_results = {}

        # S1: First post noon, excl results
        s1 = filter_first_post_noon(non_results)
        s1_res, s1_days = analyze_scenario(s1, "SCENARIO 1: First Pre-Alert Post 12PM (Excl Results)")
        scenario_results['s1'] = s1_res

        # S2: First post noon, incl results
        s2 = filter_first_post_noon(all_signals)
        s2_res, s2_days = analyze_scenario(s2, "SCENARIO 2: First Pre-Alert Post 12PM (Incl Results)")
        scenario_results['s2'] = s2_res

        # S3: All post noon, excl results
        s3 = filter_all_post_noon(non_results)
        s3_res, s3_days = analyze_scenario(s3, "SCENARIO 3: ALL Pre-Alerts Post 12PM (Excl Results)")
        scenario_results['s3'] = s3_res

        # S4: All alerts, benchmark
        s4_res, s4_days = analyze_scenario(non_results, "SCENARIO 4: ALL Pre-Alerts Any Time (Benchmark)")
        scenario_results['s4'] = s4_res

        # Detailed analysis for best scenario
        for label, res, dr in [
            ("Scenario 1 (First Post-Noon)", s1_res, s1_days),
            ("Scenario 3 (All Post-Noon)", s3_res, s3_days),
            ("Scenario 4 (Benchmark)", s4_res, s4_days),
        ]:
            if len(res.get(10, {}).get('all', [])) >= 5:
                print_detailed(res, dr, label)
                break

        # Recommendation
        print(f"\n{'='*80}")
        print("RECOMMENDATION")
        print(f"{'='*80}\n")

        # Use post-noon data if available, otherwise benchmark
        rec_res = s3_res if s3_res[10]['all'] else (s1_res if s1_res[10]['all'] else s4_res)
        rec_label = "Post-Noon Pre-Alerts" if s3_res[10]['all'] else ("First Post-Noon" if s1_res[10]['all'] else "All Pre-Alerts")

        if rec_res[10]['all']:
            trades = rec_res[10]['all']
            winners = [t for t in trades if t['profitable']]
            win_rate = len(winners) / len(trades) * 100
            avg_pnl = statistics.mean([t['pnl_pct'] for t in trades])
            total_pnl = sum([t['pnl_pct'] for t in trades])

            print(f"  Based on {rec_label} (10min exit):")
            print(f"  Trades: {len(trades)} | Win Rate: {win_rate:.1f}% | Avg P&L: {avg_pnl:+.3f}% | Total P&L: {total_pnl:+.2f}%")

            for direction in ['DROP', 'RISE']:
                dir_trades = rec_res[10][direction]
                if not dir_trades:
                    continue
                dir_winners = [t for t in dir_trades if t['profitable']]
                dir_win_rate = len(dir_winners) / len(dir_trades) * 100
                dir_avg_pnl = statistics.mean([t['pnl_pct'] for t in dir_trades])

                if dir_win_rate >= 55 and dir_avg_pnl > 0:
                    verdict = "PROFITABLE - Worth taking positions"
                elif dir_win_rate >= 50 and dir_avg_pnl > 0:
                    verdict = "MARGINAL - Proceed with caution"
                elif dir_win_rate >= 45:
                    verdict = "WEAK - Not recommended without filters"
                else:
                    verdict = "UNPROFITABLE - Avoid"

                print(f"\n  {direction}: {verdict}")
                print(f"    Trades: {len(dir_trades)}, Win Rate: {dir_win_rate:.1f}%, Avg P&L: {dir_avg_pnl:+.3f}%")

            print(f"\n  OVERALL:")
            if win_rate >= 55 and avg_pnl > 0:
                print(f"  The pre-alert post-noon strategy shows POSITIVE edge. Worth taking positions.")
            elif win_rate >= 50 and avg_pnl > 0:
                print(f"  The strategy shows MARGINAL edge. Can be taken with strict risk management.")
            elif win_rate >= 45:
                print(f"  WEAK results. Not recommended without additional confirmation signals.")
            else:
                print(f"  UNPROFITABLE. Do NOT take positions based on post-noon pre-alerts alone.")

            if len(trades) < 20:
                print(f"\n  WARNING: Small sample ({len(trades)} trades). Need 30+ for reliability.")
        else:
            print("  Insufficient data for recommendation.")

        print(f"\n{'='*80}\n")

        # Telegram
        if send_telegram_flag:
            print("Sending to Telegram...")
            report = generate_telegram_report(scenario_results)
            if report:
                send_telegram(report)

        return scenario_results

    finally:
        bt.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backtest pre-alerts post 12 PM")
    parser.add_argument("--days", type=int, default=60, help="Days to analyze")
    parser.add_argument("--send-telegram", action="store_true", help="Send to Telegram")
    parser.add_argument("--noon-hour", type=int, default=12, help="Cutoff hour")
    args = parser.parse_args()

    NOON_CUTOFF_HOUR = args.noon_hour
    run_backtest(args.days, args.send_telegram)
