#!/usr/bin/env python3
"""
Regression test: absorption alerts must respect the minimum-price gate.

The absorption block used to sit ABOVE Gate 1 in _check_alerts() and `continue` past
it, so the ORDER_FLOW_MIN_STOCK_PRICE floor (Rs 50, there because tick size makes
sub-Rs 50 percentage moves meaningless) was applied to the directional alerts only -
and absorption is ~94% of all alert traffic. Measured over 15 trading days: 5 of 567
evaluable absorption alerts entered below Rs 50, the cheapest at Rs 12.77, and 20
below Rs 100.

The contract pinned here:
  * a stock below ORDER_FLOW_MIN_STOCK_PRICE that meets every absorption condition
    produces NO alert;
  * the identical setup above the floor still produces one, so the test is failing on
    price and not on a broken fixture.

Runs offline: no Kite client, no database, no Telegram - the notifier and db are
stubs and OrderFlowMonitor.__init__ is never called.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from order_flow_monitor import OrderFlowMonitor


class StubNotifier:
    """Records what would have been sent to Telegram."""

    def __init__(self):
        self.absorption_alerts = []
        self.directional_alerts = []

    def send_order_flow_absorption(self, symbol, signal_type, price, *args, **kwargs):
        self.absorption_alerts.append((symbol, signal_type, price))
        return True

    def send_order_flow_bearish(self, symbol, *args, **kwargs):
        self.directional_alerts.append(('BEARISH', symbol))
        return True

    def send_order_flow_bullish(self, symbol, *args, **kwargs):
        self.directional_alerts.append(('BULLISH', symbol))
        return True


class StubDB:
    """Nothing is on cooldown; every fire is recorded in memory."""

    def __init__(self):
        self.recorded = []

    def was_alert_sent_recently(self, symbol, alert_type, cooldown_minutes=None):
        return False

    def record_alert(self, symbol, alert_type):
        self.recorded.append((symbol, alert_type))


def absorbing_stock(symbol, price):
    """A metrics row that satisfies every absorption condition except, maybe, price."""
    return {
        'symbol': symbol,
        'last_price': price,
        'price_change_pct': 0.0,          # absorption = flow without price movement
        'buy_volume': 500_000,
        'sell_volume': 10_000,
        'volume_delta': 490_000,
        'depth_ratio': 4.0,
        'bai': 0.10,
        'bai_delta': 0.0,
        'cum_delta_pct': 0.0,
        'tick_velocity': 0.0,
        'tick_count': 50,
        'wall_ratio': config.ORDER_FLOW_ABSORPTION_WALL_MIN_RATIO + 20,
        'wall_side': 'BID',
        'wall_price': price * 0.99,
        'wall_qty': 250_000,
        'absorption_signal': 'BUY_ABSORPTION',
        'absorption_strength': config.ORDER_FLOW_ABSORPTION_MIN_STRENGTH + 0.04,
        'fut_tick_count': 0,
    }


class AbsorptionPriceGateTest(unittest.TestCase):

    def make_monitor(self):
        """A monitor with only the state _check_alerts touches - no __init__, no Kite."""
        monitor = OrderFlowMonitor.__new__(OrderFlowMonitor)
        monitor.notifier = StubNotifier()
        monitor.db = StubDB()
        monitor._cooldown_cache = {}
        return monitor

    def test_penny_stock_absorption_does_not_alert(self):
        monitor = self.make_monitor()
        cheap = config.ORDER_FLOW_MIN_STOCK_PRICE - 1.0

        monitor._check_alerts({'PENNY': absorbing_stock('PENNY', cheap)})

        self.assertEqual(monitor.notifier.absorption_alerts, [],
                         f"absorption must not fire at Rs {cheap:.2f}")
        self.assertEqual(monitor.db.recorded, [])

    def test_the_same_setup_above_the_floor_still_alerts(self):
        monitor = self.make_monitor()
        ok_price = config.ORDER_FLOW_MIN_STOCK_PRICE + 1.0

        monitor._check_alerts({'NORMAL': absorbing_stock('NORMAL', ok_price)})

        self.assertEqual(len(monitor.notifier.absorption_alerts), 1,
                         "the fixture must genuinely produce absorption above the floor")
        symbol, signal_type, price = monitor.notifier.absorption_alerts[0]
        self.assertEqual(symbol, 'NORMAL')
        self.assertEqual(signal_type, 'BUY_ABSORPTION')
        self.assertEqual(price, ok_price)
        self.assertEqual(monitor.db.recorded, [('NORMAL', 'ABSORPTION')])

    def test_cheap_stock_does_not_crowd_out_a_qualifying_one(self):
        """Only one absorption alert fires per cycle - it must not be the penny stock."""
        monitor = self.make_monitor()
        cheap = absorbing_stock('PENNY', config.ORDER_FLOW_MIN_STOCK_PRICE - 1.0)
        # Make the cheap one the strongest candidate, so it would win the per-cycle
        # ranking if it were ever allowed into the list.
        cheap['absorption_strength'] = 1.0

        monitor._check_alerts({
            'PENNY': cheap,
            'NORMAL': absorbing_stock('NORMAL', config.ORDER_FLOW_MIN_STOCK_PRICE + 1.0),
        })

        self.assertEqual([a[0] for a in monitor.notifier.absorption_alerts], ['NORMAL'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
