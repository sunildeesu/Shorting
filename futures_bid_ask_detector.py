"""
Futures Depth Imbalance Detector

Every 5 minutes: fetches order book depth for all F&O futures contracts,
finds stocks where the summed 5-level bid quantity exceeds the summed
5-level ask quantity, and sends the top 5 by ratio to the Telegram debug
channel. This is depth resting across 5 price levels, not top-of-book
pressure — the message prints top-of-book alongside for comparison.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from telegram_notifiers.base_notifier import BaseNotifier

logger = logging.getLogger(__name__)

# NFO symbols that are index futures, not equity futures — fo_stocks.json can
# carry these (see NIFTYNXT50), and they don't belong in a scan captioned "stocks".
_INDEX_SYMBOLS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX', 'NIFTYIT'}


class FuturesBidAskDetector:
    """Scans futures order books for 5-level depth imbalance every 5 collection cycles."""

    def __init__(self, kite, futures_mapper, notifier: BaseNotifier):
        self.kite = kite
        self.futures_mapper = futures_mapper
        self.notifier = notifier
        self._cycle = 0

        # Pre-built instrument list, rebuilt whenever the input stock universe changes
        self._instruments: List[str] = []   # ["NFO:RELIANCE26MAYFUT", ...]
        self._sym_map: Dict[str, str] = {}  # "NFO:RELIANCE26MAYFUT" -> "RELIANCE"
        self._built_from: Optional[List[str]] = None  # stocks list the above was built from

    def _build_instrument_list(self, stocks: List[str]) -> None:
        self._instruments = []
        self._sym_map = {}
        for symbol in stocks:
            if symbol in _INDEX_SYMBOLS:
                continue
            fut = self.futures_mapper.get_futures_symbol(symbol)
            if fut:
                key = f"NFO:{fut}"
                self._instruments.append(key)
                self._sym_map[key] = symbol
        self._built_from = list(stocks)
        logger.info(f"FuturesBidAsk: {len(self._instruments)} futures instruments ready")

    def should_run(self) -> bool:
        self._cycle += 1
        return self._cycle % 5 == 0

    def run(self, stocks: List[str]) -> Optional[Dict]:
        if stocks != self._built_from:
            self._build_instrument_list(stocks)

        if not self._instruments:
            return None

        try:
            quotes = self.kite.quote(self._instruments)
        except Exception as e:
            logger.error(f"FuturesBidAsk: quote() failed: {e}")
            return None

        results = []
        for inst_key, quote in quotes.items():
            symbol = self._sym_map.get(inst_key)
            if not symbol:
                continue

            depth = quote.get('depth', {})
            buy_levels = depth.get('buy', [])
            sell_levels = depth.get('sell', [])
            bid_qty = sum(b.get('quantity', 0) for b in buy_levels)
            ask_qty = sum(s.get('quantity', 0) for s in sell_levels)

            if ask_qty > 0 and bid_qty > ask_qty:
                top_bid_level = max((b.get('quantity', 0) for b in buy_levels), default=0)
                results.append({
                    'symbol':        symbol,
                    'bid_qty':       bid_qty,
                    'ask_qty':       ask_qty,
                    'ratio':         bid_qty / ask_qty,
                    'ltp':           quote.get('last_price', 0),
                    'l1_bid':        buy_levels[0].get('quantity', 0) if buy_levels else 0,
                    'l1_ask':        sell_levels[0].get('quantity', 0) if sell_levels else 0,
                    'concentration': (top_bid_level / bid_qty * 100) if bid_qty > 0 else 0.0,
                })

        top5 = sorted(results, key=lambda x: x['ratio'], reverse=True)[:5]

        stats = {
            'scanned':      len(quotes),
            'bid_dominant': len(results),
            'top5':         top5,
        }

        logger.info(
            f"FuturesBidAsk: {len(results)}/{len(quotes)} bid-dominant "
            f"| top: {[r['symbol'] for r in top5]}"
        )

        if top5:
            self.notifier.send_debug(self._format(top5, len(quotes), len(results)))

        return stats

    def _format(self, top5: List[Dict], total: int, bid_dominant: int) -> str:
        now = datetime.now().strftime('%H:%M')
        lines = [
            f"📊 <b>Futures Depth Imbalance (5 levels) — Top 5</b>",
            f"⏰ {now} IST | {bid_dominant}/{total} stocks bid-depth-heavy\n",
        ]
        medals = ['🥇', '🥈', '🥉', '4.', '5.']
        for medal, r in zip(medals, top5):
            lines.append(
                f"{medal} <b>{r['symbol']}</b>  "
                f"L1 {r['l1_bid']:,} / {r['l1_ask']:,} · "
                f"5-lvl {r['bid_qty']:,} / {r['ask_qty']:,} "
                f"(<b>{r['ratio']:.2f}×</b>)  ₹{r['ltp']:,.1f}\n"
                f"    top level = {r['concentration']:.0f}% of bid"
            )
        return '\n'.join(lines)
