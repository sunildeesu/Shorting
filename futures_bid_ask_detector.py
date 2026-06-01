"""
Futures Bid/Ask Imbalance Detector

Every 5 minutes: fetches order book depth for all F&O futures contracts,
finds stocks where total bid quantity > total ask quantity, and sends
top 5 by ratio to the Telegram debug channel.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from telegram_notifiers.base_notifier import BaseNotifier

logger = logging.getLogger(__name__)


class FuturesBidAskDetector:
    """Scans futures order books for bid > ask imbalance every 5 collection cycles."""

    def __init__(self, kite, futures_mapper, notifier: BaseNotifier):
        self.kite = kite
        self.futures_mapper = futures_mapper
        self.notifier = notifier
        self._cycle = 0

        # Pre-build instrument list once
        self._instruments: List[str] = []   # ["NFO:RELIANCE26MAYFUT", ...]
        self._sym_map: Dict[str, str] = {}  # "NFO:RELIANCE26MAYFUT" -> "RELIANCE"

    def _build_instrument_list(self, stocks: List[str]) -> None:
        for symbol in stocks:
            fut = self.futures_mapper.get_futures_symbol(symbol)
            if fut:
                key = f"NFO:{fut}"
                self._instruments.append(key)
                self._sym_map[key] = symbol
        logger.info(f"FuturesBidAsk: {len(self._instruments)} futures instruments ready")

    def should_run(self) -> bool:
        self._cycle += 1
        return self._cycle % 5 == 0

    def run(self, stocks: List[str]) -> Optional[Dict]:
        if not self._instruments:
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
            bid_qty = sum(b.get('quantity', 0) for b in depth.get('buy', []))
            ask_qty = sum(s.get('quantity', 0) for s in depth.get('sell', []))

            if ask_qty > 0 and bid_qty > ask_qty:
                results.append({
                    'symbol':  symbol,
                    'bid_qty': bid_qty,
                    'ask_qty': ask_qty,
                    'ratio':   bid_qty / ask_qty,
                    'ltp':     quote.get('last_price', 0),
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
            f"📊 <b>Futures Bid &gt; Ask — Top 5</b>",
            f"⏰ {now} IST | {bid_dominant}/{total} stocks bid-dominant\n",
        ]
        medals = ['🥇', '🥈', '🥉', '4.', '5.']
        for medal, r in zip(medals, top5):
            lines.append(
                f"{medal} <b>{r['symbol']}</b>  "
                f"Bid: {r['bid_qty']:,} | Ask: {r['ask_qty']:,} | "
                f"<b>{r['ratio']:.2f}×</b>  ₹{r['ltp']:,.1f}"
            )
        return '\n'.join(lines)
