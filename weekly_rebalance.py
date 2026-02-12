#!/usr/bin/env python3
"""
Weekly Momentum Portfolio Rebalancer
Executes weekly rebalancing of momentum strategy portfolio

Features:
1. Runs every Monday at 9:30 AM
2. Compares new top 20 vs current holdings
3. Generates sell orders for stocks falling out
4. Generates buy orders for new entrants
5. Sends Telegram alert with portfolio changes
6. Optional auto-execution via Kite API
7. Skips stocks with earnings in next 7 days
8. Enforces max 5% allocation per stock

Author: Claude Opus 4.5
Date: 2026-02-12
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from kiteconnect import KiteConnect
import logging
import requests
import config
from momentum_strategy import MomentumScreener
from quarterly_results_checker import get_results_checker, QuarterlyResultsChecker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/weekly_rebalance.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Configuration
PORTFOLIO_STATE_FILE = "data/momentum_portfolio_state.json"
REBALANCE_HISTORY_FILE = "data/momentum_rebalance_history.json"
MAX_POSITION_PCT = 5.0  # Maximum 5% per stock
EARNINGS_BLACKOUT_DAYS = 7  # Skip stocks with earnings in next 7 days


class WeeklyRebalancer:
    """
    Weekly momentum portfolio rebalancer.
    Handles execution of momentum strategy with risk management.
    """

    def __init__(
        self,
        capital: float = 500000,  # 5 lakh default
        top_n: int = 20,
        auto_execute: bool = False,  # Set True for live trading
        paper_mode: bool = True,
    ):
        """
        Initialize the rebalancer.

        Args:
            capital: Total capital allocated to strategy
            top_n: Number of stocks to hold
            auto_execute: Execute trades via Kite API
            paper_mode: Log trades without executing (for testing)
        """
        self.capital = capital
        self.top_n = top_n
        self.auto_execute = auto_execute
        self.paper_mode = paper_mode

        # Initialize Kite Connect
        self.kite = KiteConnect(api_key=config.KITE_API_KEY)
        self.kite.set_access_token(config.KITE_ACCESS_TOKEN)

        # Initialize momentum screener
        self.screener = MomentumScreener(top_n=top_n)

        # Initialize results checker
        self.results_checker = get_results_checker()

        # Load current portfolio state
        self.current_holdings = self._load_portfolio_state()

        # Telegram config
        self.telegram_token = config.TELEGRAM_BOT_TOKEN
        self.telegram_channel = config.TELEGRAM_CHANNEL_ID

        logger.info(f"WeeklyRebalancer initialized: capital=₹{capital:,.0f}, top_n={top_n}")
        logger.info(f"Auto-execute: {auto_execute}, Paper mode: {paper_mode}")

    def _load_portfolio_state(self) -> Dict:
        """Load current portfolio state from file"""
        if os.path.exists(PORTFOLIO_STATE_FILE):
            try:
                with open(PORTFOLIO_STATE_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load portfolio state: {e}")

        # Default empty state
        return {
            'holdings': {},  # {symbol: {shares, avg_price, cost_basis}}
            'cash': self.capital,
            'last_rebalance': None,
            'last_value': self.capital
        }

    def _save_portfolio_state(self):
        """Save current portfolio state to file"""
        os.makedirs(os.path.dirname(PORTFOLIO_STATE_FILE), exist_ok=True)
        try:
            with open(PORTFOLIO_STATE_FILE, 'w') as f:
                json.dump(self.current_holdings, f, indent=2)
            logger.info("Portfolio state saved")
        except Exception as e:
            logger.error(f"Failed to save portfolio state: {e}")

    def _save_rebalance_history(self, record: Dict):
        """Append rebalance record to history"""
        history = []
        if os.path.exists(REBALANCE_HISTORY_FILE):
            try:
                with open(REBALANCE_HISTORY_FILE, 'r') as f:
                    history = json.load(f)
            except:
                pass

        history.append(record)

        os.makedirs(os.path.dirname(REBALANCE_HISTORY_FILE), exist_ok=True)
        with open(REBALANCE_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)

    def get_current_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Get current prices for a list of symbols"""
        prices = {}
        try:
            # Build instrument tokens
            token_map = {}
            for symbol in symbols:
                if symbol in self.screener.instrument_tokens:
                    token_map[self.screener.instrument_tokens[symbol]] = symbol

            if not token_map:
                return prices

            # Fetch quotes
            quotes = self.kite.quote(list(token_map.keys()))

            for token, data in quotes.items():
                symbol = token_map.get(int(token.replace('NSE:', '')))
                if symbol:
                    prices[symbol] = data['last_price']

        except Exception as e:
            logger.error(f"Failed to get prices: {e}")

        return prices

    def calculate_portfolio_value(self) -> Tuple[float, Dict[str, float]]:
        """
        Calculate current portfolio value.

        Returns:
            Tuple of (total_value, {symbol: current_value})
        """
        holdings = self.current_holdings.get('holdings', {})
        cash = self.current_holdings.get('cash', 0)

        if not holdings:
            return cash, {}

        # Get current prices
        symbols = list(holdings.keys())
        prices = self.get_current_prices(symbols)

        # Calculate values
        position_values = {}
        total_value = cash

        for symbol, position in holdings.items():
            if symbol in prices:
                current_value = position['shares'] * prices[symbol]
                position_values[symbol] = current_value
                total_value += current_value
            else:
                # Use last known price
                position_values[symbol] = position.get('cost_basis', 0)
                total_value += position_values[symbol]

        return total_value, position_values

    def filter_by_earnings(self, symbols: List[str]) -> List[str]:
        """
        Filter out stocks with earnings in next 7 days.

        Args:
            symbols: List of candidate symbols

        Returns:
            Filtered list excluding stocks with upcoming earnings
        """
        filtered = []
        earnings_blackout = []

        for symbol in symbols:
            results_info = self.results_checker.get_results_info(symbol)

            if results_info['has_results']:
                earnings_blackout.append(f"{symbol} ({results_info['date']})")
                logger.info(f"Excluding {symbol}: Results on {results_info['date']}")
            else:
                filtered.append(symbol)

        if earnings_blackout:
            logger.info(f"Excluded {len(earnings_blackout)} stocks due to earnings: {earnings_blackout}")

        return filtered

    def generate_rebalance_orders(
        self,
        target_portfolio: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Generate buy and sell orders for rebalancing.

        Args:
            target_portfolio: List of {symbol, weight_pct, current_price, ...}

        Returns:
            Tuple of (sell_orders, buy_orders)
        """
        sell_orders = []
        buy_orders = []

        current_holdings = self.current_holdings.get('holdings', {})
        cash = self.current_holdings.get('cash', self.capital)

        # Calculate total portfolio value
        total_value, position_values = self.calculate_portfolio_value()

        # Get target symbols
        target_symbols = {p['symbol'] for p in target_portfolio}
        current_symbols = set(current_holdings.keys())

        # Get current prices
        all_symbols = list(target_symbols | current_symbols)
        prices = self.get_current_prices(all_symbols)

        # SELLS: Stocks no longer in target portfolio
        for symbol in current_symbols - target_symbols:
            if symbol in current_holdings:
                position = current_holdings[symbol]
                price = prices.get(symbol, position.get('avg_price', 0))
                if price > 0:
                    sell_orders.append({
                        'symbol': symbol,
                        'action': 'SELL',
                        'shares': position['shares'],
                        'price': price,
                        'value': position['shares'] * price,
                        'reason': 'NO_LONGER_IN_TOP_N'
                    })

        # Calculate cash after sells
        cash_after_sells = cash + sum(o['value'] for o in sell_orders)

        # BUYS: New stocks entering portfolio
        # Equal weight allocation with max 5% cap
        weight_per_stock = min(100.0 / self.top_n, MAX_POSITION_PCT)
        target_value_per_stock = total_value * weight_per_stock / 100

        for target in target_portfolio:
            symbol = target['symbol']
            price = prices.get(symbol, target.get('current_price', 0))

            if price <= 0:
                continue

            if symbol not in current_symbols:
                # New position
                target_shares = int(target_value_per_stock / price)
                if target_shares > 0:
                    buy_orders.append({
                        'symbol': symbol,
                        'action': 'BUY',
                        'shares': target_shares,
                        'price': price,
                        'value': target_shares * price,
                        'reason': 'NEW_ENTRY',
                        'momentum_rank': target.get('rank', 0)
                    })

            else:
                # Existing position - check if rebalancing needed
                current_shares = current_holdings[symbol]['shares']
                target_shares = int(target_value_per_stock / price)
                diff = target_shares - current_shares

                # Only rebalance if difference is significant (>10%)
                if abs(diff) > current_shares * 0.1:
                    if diff > 0:
                        buy_orders.append({
                            'symbol': symbol,
                            'action': 'BUY',
                            'shares': diff,
                            'price': price,
                            'value': diff * price,
                            'reason': 'REBALANCE_UP'
                        })
                    elif diff < 0:
                        sell_orders.append({
                            'symbol': symbol,
                            'action': 'SELL',
                            'shares': abs(diff),
                            'price': price,
                            'value': abs(diff) * price,
                            'reason': 'REBALANCE_DOWN'
                        })

        # Ensure we have enough cash for buys
        total_buy_value = sum(o['value'] for o in buy_orders)
        if total_buy_value > cash_after_sells:
            # Scale down buy orders
            scale_factor = cash_after_sells / total_buy_value * 0.95  # 5% buffer
            for order in buy_orders:
                order['shares'] = int(order['shares'] * scale_factor)
                order['value'] = order['shares'] * order['price']

        return sell_orders, buy_orders

    def execute_orders(
        self,
        sell_orders: List[Dict],
        buy_orders: List[Dict]
    ) -> bool:
        """
        Execute orders via Kite API.

        Args:
            sell_orders: List of sell orders
            buy_orders: List of buy orders

        Returns:
            True if all orders executed successfully
        """
        if self.paper_mode:
            logger.info("PAPER MODE: Orders logged but not executed")
            return self._paper_execute(sell_orders, buy_orders)

        if not self.auto_execute:
            logger.info("Auto-execute disabled. Orders generated but not executed.")
            return True

        success = True

        # Execute sells first
        for order in sell_orders:
            try:
                order_id = self.kite.place_order(
                    tradingsymbol=order['symbol'],
                    exchange="NSE",
                    transaction_type="SELL",
                    quantity=order['shares'],
                    order_type="MARKET",
                    product="CNC",  # Delivery
                    variety="regular"
                )
                logger.info(f"SELL {order['symbol']}: {order['shares']} shares @ ₹{order['price']:.2f} - Order ID: {order_id}")
                order['order_id'] = order_id
            except Exception as e:
                logger.error(f"SELL {order['symbol']} FAILED: {e}")
                success = False

        # Execute buys
        for order in buy_orders:
            try:
                order_id = self.kite.place_order(
                    tradingsymbol=order['symbol'],
                    exchange="NSE",
                    transaction_type="BUY",
                    quantity=order['shares'],
                    order_type="MARKET",
                    product="CNC",  # Delivery
                    variety="regular"
                )
                logger.info(f"BUY {order['symbol']}: {order['shares']} shares @ ₹{order['price']:.2f} - Order ID: {order_id}")
                order['order_id'] = order_id
            except Exception as e:
                logger.error(f"BUY {order['symbol']} FAILED: {e}")
                success = False

        return success

    def _paper_execute(
        self,
        sell_orders: List[Dict],
        buy_orders: List[Dict]
    ) -> bool:
        """
        Paper trade execution - update state without real trades.
        """
        holdings = self.current_holdings.get('holdings', {})
        cash = self.current_holdings.get('cash', self.capital)

        # Process sells
        for order in sell_orders:
            symbol = order['symbol']
            if symbol in holdings:
                # Add proceeds to cash
                cash += order['value']
                # Remove or reduce position
                if order['reason'] == 'NO_LONGER_IN_TOP_N':
                    del holdings[symbol]
                else:
                    holdings[symbol]['shares'] -= order['shares']
                logger.info(f"PAPER SELL: {symbol} - {order['shares']} shares @ ₹{order['price']:.2f}")

        # Process buys
        for order in buy_orders:
            symbol = order['symbol']
            if order['value'] > cash:
                logger.warning(f"Insufficient cash for {symbol}, skipping")
                continue

            cash -= order['value']

            if symbol in holdings:
                # Add to existing position
                old_cost = holdings[symbol]['cost_basis']
                old_shares = holdings[symbol]['shares']
                new_shares = old_shares + order['shares']
                new_cost = old_cost + order['value']
                holdings[symbol] = {
                    'shares': new_shares,
                    'avg_price': new_cost / new_shares,
                    'cost_basis': new_cost
                }
            else:
                # New position
                holdings[symbol] = {
                    'shares': order['shares'],
                    'avg_price': order['price'],
                    'cost_basis': order['value']
                }
            logger.info(f"PAPER BUY: {symbol} - {order['shares']} shares @ ₹{order['price']:.2f}")

        # Update state
        self.current_holdings['holdings'] = holdings
        self.current_holdings['cash'] = cash
        self._save_portfolio_state()

        return True

    def send_telegram_alert(
        self,
        sell_orders: List[Dict],
        buy_orders: List[Dict],
        portfolio_value: float
    ):
        """Send rebalance summary to Telegram"""
        try:
            today = datetime.now().strftime('%d-%b-%Y')

            message = (
                f"📊 <b>MOMENTUM REBALANCE - {today}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )

            # Portfolio summary
            message += f"💰 <b>Portfolio Value:</b> ₹{portfolio_value:,.0f}\n"
            message += f"📈 <b>Stocks Held:</b> {len(self.current_holdings.get('holdings', {}))}\n\n"

            # Sells
            if sell_orders:
                message += f"🔴 <b>SELLS ({len(sell_orders)}):</b>\n"
                for order in sell_orders:
                    message += f"   • {order['symbol']}: {order['shares']} @ ₹{order['price']:.2f}\n"
                message += "\n"

            # Buys
            if buy_orders:
                message += f"🟢 <b>BUYS ({len(buy_orders)}):</b>\n"
                for order in buy_orders:
                    rank_info = f" (Rank #{order.get('momentum_rank', '-')})" if order.get('momentum_rank') else ""
                    message += f"   • {order['symbol']}: {order['shares']} @ ₹{order['price']:.2f}{rank_info}\n"
                message += "\n"

            # Costs
            sell_value = sum(o['value'] for o in sell_orders)
            buy_value = sum(o['value'] for o in buy_orders)
            turnover = sell_value + buy_value
            message += f"📊 <b>Turnover:</b> ₹{turnover:,.0f}\n"

            if self.paper_mode:
                message += "\n⚠️ <i>PAPER MODE - No real trades executed</i>"

            # Send
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_channel,
                "text": message,
                "parse_mode": "HTML"
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            logger.info("Telegram alert sent successfully")

        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def run_rebalance(self) -> bool:
        """
        Run the weekly rebalance.

        Returns:
            True if rebalance completed successfully
        """
        logger.info("=" * 80)
        logger.info("WEEKLY MOMENTUM REBALANCE STARTED")
        logger.info("=" * 80)

        # Step 1: Run momentum screener
        logger.info("Step 1: Running momentum screener...")
        screener_results = self.screener.screen_stocks()

        if len(screener_results) == 0:
            logger.error("Screener returned no results. Aborting rebalance.")
            return False

        # Step 2: Get target portfolio
        logger.info("Step 2: Building target portfolio...")
        target_portfolio = self.screener.get_top_stocks()

        # Step 3: Filter by earnings
        logger.info("Step 3: Filtering out stocks with upcoming earnings...")
        self.results_checker.refresh_if_needed()

        filtered_symbols = self.filter_by_earnings([p['symbol'] for p in target_portfolio])

        # If we lost too many stocks to earnings, adjust
        target_portfolio = [p for p in target_portfolio if p['symbol'] in filtered_symbols]

        # Fill remaining slots from next best stocks
        if len(target_portfolio) < self.top_n:
            remaining = self.top_n - len(target_portfolio)
            additional = screener_results[~screener_results['symbol'].isin(filtered_symbols)]
            additional = additional[~additional['symbol'].isin([p['symbol'] for p in target_portfolio])]
            additional = additional.head(remaining * 2)  # Get extra candidates

            for _, row in additional.iterrows():
                if len(target_portfolio) >= self.top_n:
                    break
                if row['symbol'] not in self.filter_by_earnings([row['symbol']]):
                    continue
                target_portfolio.append({
                    'symbol': row['symbol'],
                    'rank': int(row['rank']),
                    'weight_pct': 100.0 / self.top_n,
                    'momentum_score': row['momentum_score'],
                    'return_6m': row['return_6m'],
                    'return_12m': row['return_12m'],
                    'volatility': row['volatility'],
                    'current_price': row['current_price']
                })

        logger.info(f"Target portfolio: {len(target_portfolio)} stocks")

        # Step 4: Generate orders
        logger.info("Step 4: Generating rebalance orders...")
        sell_orders, buy_orders = self.generate_rebalance_orders(target_portfolio)

        logger.info(f"Generated {len(sell_orders)} sells, {len(buy_orders)} buys")

        # Step 5: Execute orders
        logger.info("Step 5: Executing orders...")
        success = self.execute_orders(sell_orders, buy_orders)

        # Step 6: Update state
        portfolio_value, _ = self.calculate_portfolio_value()
        self.current_holdings['last_rebalance'] = datetime.now().isoformat()
        self.current_holdings['last_value'] = portfolio_value
        self._save_portfolio_state()

        # Step 7: Save history
        self._save_rebalance_history({
            'date': datetime.now().isoformat(),
            'portfolio_value': portfolio_value,
            'sell_orders': sell_orders,
            'buy_orders': buy_orders,
            'target_stocks': [p['symbol'] for p in target_portfolio],
            'paper_mode': self.paper_mode
        })

        # Step 8: Send Telegram alert
        logger.info("Step 6: Sending Telegram alert...")
        self.send_telegram_alert(sell_orders, buy_orders, portfolio_value)

        # Print summary
        self._print_summary(sell_orders, buy_orders, target_portfolio, portfolio_value)

        logger.info("=" * 80)
        logger.info("WEEKLY REBALANCE COMPLETE")
        logger.info("=" * 80)

        return success

    def _print_summary(
        self,
        sell_orders: List[Dict],
        buy_orders: List[Dict],
        target_portfolio: List[Dict],
        portfolio_value: float
    ):
        """Print rebalance summary to console"""
        print("\n" + "=" * 80)
        print("WEEKLY MOMENTUM REBALANCE SUMMARY")
        print("=" * 80)
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"Portfolio Value: ₹{portfolio_value:,.0f}")
        print("-" * 40)

        if sell_orders:
            print("\nSELLS:")
            for order in sell_orders:
                print(f"  {order['symbol']}: {order['shares']} shares @ ₹{order['price']:.2f} = ₹{order['value']:,.0f}")

        if buy_orders:
            print("\nBUYS:")
            for order in buy_orders:
                print(f"  {order['symbol']}: {order['shares']} shares @ ₹{order['price']:.2f} = ₹{order['value']:,.0f}")

        print("\nTARGET PORTFOLIO:")
        for i, p in enumerate(target_portfolio[:10], 1):
            print(f"  {i}. {p['symbol']}: Score={p['momentum_score']:.2f}, 6M={p['return_6m']:.1f}%, 12M={p['return_12m']:.1f}%")

        if len(target_portfolio) > 10:
            print(f"  ... and {len(target_portfolio) - 10} more")

        print("=" * 80)


def is_rebalance_day() -> bool:
    """Check if today is a rebalance day (Monday)"""
    return datetime.now().weekday() == 0


def is_rebalance_time() -> bool:
    """Check if it's rebalance time (9:30 AM IST)"""
    now = datetime.now()
    return now.hour == 9 and 25 <= now.minute <= 35


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Weekly Momentum Rebalancer')
    parser.add_argument('--capital', type=float, default=500000, help='Capital in INR (default: 5 lakh)')
    parser.add_argument('--top', type=int, default=20, help='Number of stocks (default: 20)')
    parser.add_argument('--force', action='store_true', help='Force rebalance regardless of day/time')
    parser.add_argument('--live', action='store_true', help='Execute real trades (default: paper mode)')
    parser.add_argument('--auto', action='store_true', help='Auto-execute trades via Kite')
    parser.add_argument('--dry-run', action='store_true', help='Show what would happen without executing')
    args = parser.parse_args()

    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    os.makedirs('data', exist_ok=True)

    # Check if it's rebalance day/time
    if not args.force:
        if not is_rebalance_day():
            logger.info(f"Not a rebalance day (today is {datetime.now().strftime('%A')})")
            print("Today is not Monday. Use --force to run anyway.")
            return

    logger.info("=" * 80)
    logger.info("WEEKLY MOMENTUM REBALANCER")
    logger.info("=" * 80)
    logger.info(f"Capital: ₹{args.capital:,.0f}")
    logger.info(f"Top N: {args.top}")
    logger.info(f"Paper Mode: {not args.live}")
    logger.info(f"Auto-Execute: {args.auto}")
    logger.info("=" * 80)

    # Create rebalancer
    rebalancer = WeeklyRebalancer(
        capital=args.capital,
        top_n=args.top,
        auto_execute=args.auto,
        paper_mode=not args.live
    )

    # Run rebalance
    if args.dry_run:
        logger.info("DRY RUN MODE - Showing what would happen...")
        # Just run screener and show results
        portfolio = rebalancer.screener.get_top_stocks()
        rebalancer.screener.print_portfolio(portfolio)
    else:
        rebalancer.run_rebalance()


if __name__ == "__main__":
    main()
