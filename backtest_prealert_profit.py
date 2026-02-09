#!/usr/bin/env python3
"""
Backtest Pre-Alert Profitability

For each pre-alert signal:
1. Record entry price at signal time
2. Check price after 10 minutes
3. Calculate profit/loss based on direction

This measures actual trading profitability, not just alert accuracy.

Author: Claude Opus 4.5
Date: 2026-02-09
"""

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

import config


class ProfitabilityBacktester:
    """Backtest pre-alert profitability."""

    def __init__(self):
        self.db_path = "data/central_quotes.db"
        self.conn = None

        # Early warning settings (from config)
        self.ew_threshold = config.EARLY_WARNING_THRESHOLD  # 1.0%
        self.ew_lookback = config.EARLY_WARNING_LOOKBACK    # 4 min
        self.ew_volume_mult = config.EARLY_WARNING_VOLUME_MULT  # 1.2x

        # Filters
        self.require_obv = getattr(config, 'EARLY_WARNING_REQUIRE_OBV', True)
        self.require_vwap = getattr(config, 'EARLY_WARNING_REQUIRE_VWAP', True)

        # Holding period
        self.hold_minutes = 10

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
            AND time(timestamp) >= '09:25:00'
            AND time(timestamp) <= '15:30:00'
            ORDER BY timestamp ASC
        """, (symbol, date_str))

        return [{'timestamp': r[0], 'price': r[1], 'volume': r[2] or 0}
                for r in cursor.fetchall()]

    def calculate_obv(self, data):
        """Calculate OBV series."""
        if len(data) < 2:
            return []
        obv = [0]
        for i in range(1, len(data)):
            prev_price = data[i-1]['price']
            curr_price = data[i]['price']
            volume = data[i]['volume'] or 0
            if curr_price > prev_price:
                obv.append(obv[-1] + volume)
            elif curr_price < prev_price:
                obv.append(obv[-1] - volume)
            else:
                obv.append(obv[-1])
        return obv

    def check_obv_confirmation(self, data, idx, direction):
        """Check if OBV confirms price direction."""
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

        obv_up = normalized > 0.1
        obv_down = normalized < -0.1

        if direction == 'drop':
            return obv_down
        else:
            return obv_up

    def calculate_vwap(self, data, idx):
        """Calculate VWAP up to index."""
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
        """Check if price position relative to VWAP confirms move."""
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
        vol_ratio = curr_vol / prev_vol
        if vol_ratio < self.ew_volume_mult:
            return False, None, 0

        # Price change
        drop_pct = ((prev_price - curr_price) / prev_price) * 100
        rise_pct = ((curr_price - prev_price) / prev_price) * 100

        if drop_pct >= self.ew_threshold:
            # Check filters
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

    def run_backtest(self, days: int = 30):
        """Run profitability backtest."""
        print(f"\n{'='*70}")
        print("PRE-ALERT PROFITABILITY BACKTEST")
        print(f"{'='*70}")
        print(f"\nSettings:")
        print(f"  - Early Warning: {self.ew_threshold}% in {self.ew_lookback} min")
        print(f"  - Volume: {self.ew_volume_mult}x required")
        print(f"  - Filters: OBV={self.require_obv}, VWAP={self.require_vwap}")
        print(f"  - Hold Period: {self.hold_minutes} minutes")
        print(f"  - Analysis: Last {days} days\n")

        cursor = self._get_db().cursor()
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Get trading dates
        cursor.execute("""
            SELECT DISTINCT date(timestamp)
            FROM stock_quotes
            WHERE timestamp >= ?
            ORDER BY timestamp
        """, (cutoff,))
        dates = [r[0] for r in cursor.fetchall()]

        print(f"Scanning {len(dates)} trading days...\n")

        # Results storage
        trades = []
        last_signal = {}  # symbol -> timestamp (for cooldown)

        for date_idx, date_str in enumerate(dates):
            if date_idx % 5 == 0:
                print(f"  Processing {date_str}...")

            # Get symbols for this date
            cursor.execute("""
                SELECT DISTINCT symbol
                FROM stock_quotes
                WHERE date(timestamp) = ?
            """, (date_str,))
            symbols = [r[0] for r in cursor.fetchall()]

            for symbol in symbols:
                data = self.get_day_data(symbol, date_str)
                if len(data) < self.ew_lookback + self.hold_minutes + 5:
                    continue

                for idx in range(self.ew_lookback, len(data) - self.hold_minutes):
                    # Check cooldown (15 min)
                    current_ts = data[idx]['timestamp']
                    if symbol in last_signal:
                        try:
                            last_dt = datetime.strptime(last_signal[symbol], '%Y-%m-%d %H:%M:%S')
                            curr_dt = datetime.strptime(current_ts, '%Y-%m-%d %H:%M:%S')
                            if (curr_dt - last_dt).total_seconds() < 900:
                                continue
                        except:
                            pass

                    # Check for signal
                    fires, direction, signal_pct = self.check_signal(data, idx)
                    if not fires:
                        continue

                    # Record entry
                    entry_price = data[idx]['price']
                    entry_time = data[idx]['timestamp']

                    # Get exit price (10 min later)
                    exit_idx = idx + self.hold_minutes
                    if exit_idx >= len(data):
                        continue

                    exit_price = data[exit_idx]['price']
                    exit_time = data[exit_idx]['timestamp']

                    if not entry_price or not exit_price:
                        continue

                    # Calculate P&L
                    if direction == 'DROP':
                        # For DROP, we'd short: profit if price goes down
                        pnl_pct = ((entry_price - exit_price) / entry_price) * 100
                    else:
                        # For RISE, we'd long: profit if price goes up
                        pnl_pct = ((exit_price - entry_price) / entry_price) * 100

                    trades.append({
                        'symbol': symbol,
                        'direction': direction,
                        'entry_time': entry_time,
                        'entry_price': entry_price,
                        'exit_time': exit_time,
                        'exit_price': exit_price,
                        'signal_pct': signal_pct,
                        'pnl_pct': pnl_pct,
                        'profitable': pnl_pct > 0
                    })

                    # Update cooldown
                    last_signal[symbol] = current_ts

        # Analyze results
        self.print_results(trades)
        return trades

    def print_results(self, trades):
        """Print backtest results."""
        if not trades:
            print("\nNo trades found!")
            return

        print(f"\n{'='*70}")
        print("RESULTS SUMMARY")
        print(f"{'='*70}\n")

        total = len(trades)
        winners = [t for t in trades if t['profitable']]
        losers = [t for t in trades if not t['profitable']]

        win_rate = len(winners) / total * 100
        loss_rate = len(losers) / total * 100

        all_pnl = [t['pnl_pct'] for t in trades]
        avg_pnl = statistics.mean(all_pnl)
        median_pnl = statistics.median(all_pnl)
        total_pnl = sum(all_pnl)

        winner_pnl = [t['pnl_pct'] for t in winners] if winners else [0]
        loser_pnl = [t['pnl_pct'] for t in losers] if losers else [0]

        avg_win = statistics.mean(winner_pnl) if winner_pnl else 0
        avg_loss = statistics.mean(loser_pnl) if loser_pnl else 0

        print(f"Total Trades: {total}")
        print(f"  Winners: {len(winners)} ({win_rate:.1f}%)")
        print(f"  Losers:  {len(losers)} ({loss_rate:.1f}%)")

        print(f"\n{'─'*70}")
        print("PROFIT/LOSS ANALYSIS")
        print(f"{'─'*70}")
        print(f"  Average P&L per trade: {avg_pnl:+.2f}%")
        print(f"  Median P&L per trade:  {median_pnl:+.2f}%")
        print(f"  Total P&L (sum):       {total_pnl:+.2f}%")
        print(f"\n  Average Winner: {avg_win:+.2f}%")
        print(f"  Average Loser:  {avg_loss:+.2f}%")

        # Risk/Reward ratio
        if avg_loss != 0:
            rr_ratio = abs(avg_win / avg_loss)
            print(f"  Risk/Reward Ratio: {rr_ratio:.2f}")

        # By direction
        print(f"\n{'─'*70}")
        print("BY DIRECTION")
        print(f"{'─'*70}")

        for direction in ['DROP', 'RISE']:
            dir_trades = [t for t in trades if t['direction'] == direction]
            if not dir_trades:
                continue

            dir_winners = [t for t in dir_trades if t['profitable']]
            dir_pnl = [t['pnl_pct'] for t in dir_trades]

            print(f"\n  {direction}:")
            print(f"    Trades: {len(dir_trades)}")
            print(f"    Win Rate: {len(dir_winners)/len(dir_trades)*100:.1f}%")
            print(f"    Avg P&L: {statistics.mean(dir_pnl):+.2f}%")
            print(f"    Total P&L: {sum(dir_pnl):+.2f}%")

        # P&L Distribution
        print(f"\n{'─'*70}")
        print("P&L DISTRIBUTION")
        print(f"{'─'*70}")

        ranges = [
            ('Big Loss (< -2%)', lambda x: x < -2),
            ('Loss (-2% to -1%)', lambda x: -2 <= x < -1),
            ('Small Loss (-1% to 0%)', lambda x: -1 <= x < 0),
            ('Small Win (0% to 1%)', lambda x: 0 <= x < 1),
            ('Win (1% to 2%)', lambda x: 1 <= x < 2),
            ('Big Win (> 2%)', lambda x: x >= 2),
        ]

        for label, condition in ranges:
            count = sum(1 for t in trades if condition(t['pnl_pct']))
            pct = count / total * 100
            bar = '█' * int(pct / 2)
            print(f"  {label:<25} {count:>4} ({pct:>5.1f}%) {bar}")

        # Sample trades
        print(f"\n{'─'*70}")
        print("SAMPLE WINNING TRADES")
        print(f"{'─'*70}")
        sorted_wins = sorted(winners, key=lambda x: -x['pnl_pct'])[:5]
        for t in sorted_wins:
            print(f"  {t['symbol']:<12} {t['direction']:<5} "
                  f"₹{t['entry_price']:>8.2f} → ₹{t['exit_price']:>8.2f} "
                  f"P&L: {t['pnl_pct']:+.2f}%")

        print(f"\n{'─'*70}")
        print("SAMPLE LOSING TRADES")
        print(f"{'─'*70}")
        sorted_losses = sorted(losers, key=lambda x: x['pnl_pct'])[:5]
        for t in sorted_losses:
            print(f"  {t['symbol']:<12} {t['direction']:<5} "
                  f"₹{t['entry_price']:>8.2f} → ₹{t['exit_price']:>8.2f} "
                  f"P&L: {t['pnl_pct']:+.2f}%")

        # Verdict
        print(f"\n{'='*70}")
        print("VERDICT")
        print(f"{'='*70}")

        if win_rate >= 55 and avg_pnl > 0:
            print(f"✅ PROFITABLE STRATEGY")
            print(f"   Win rate {win_rate:.1f}% with positive average P&L ({avg_pnl:+.2f}%)")
        elif win_rate >= 50 and avg_pnl > 0:
            print(f"⚠️  MARGINALLY PROFITABLE")
            print(f"   Win rate {win_rate:.1f}% with slight positive P&L ({avg_pnl:+.2f}%)")
        elif win_rate >= 45:
            print(f"⚠️  BREAK-EVEN STRATEGY")
            print(f"   Win rate {win_rate:.1f}% - needs optimization")
        else:
            print(f"❌ UNPROFITABLE STRATEGY")
            print(f"   Win rate {win_rate:.1f}% with negative P&L ({avg_pnl:+.2f}%)")

        print(f"\n{'='*70}\n")

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--hold", type=int, default=10, help="Hold period in minutes")
    args = parser.parse_args()

    bt = ProfitabilityBacktester()
    bt.hold_minutes = args.hold

    try:
        bt.run_backtest(days=args.days)
    finally:
        bt.close()


if __name__ == "__main__":
    main()
