#!/usr/bin/env python3
"""
Replay the hammer/shooting-star + confirmation logic over TODAY's 5-min candles (from the
central DB) to count how many alerts the live monitor would have fired today.

Each of today's bars is evaluated once as the confirmation bar (exactly as the live monitor
sees the latest closed bar each cycle), with the same per-(symbol,direction) cooldown.
"""
import json
from datetime import datetime
import config
from central_quote_db import get_central_db
from candle_confirmation_monitor import detect_reversal_confirmation, HammerDetector, ShootingStarDetector

H = HammerDetector(config.CANDLE_MIN_CONFIDENCE, 14, 2.0, 1.0)
S = ShootingStarDetector(config.CANDLE_MIN_CONFIDENCE, 14, 2.0, 1.0)
COOLDOWN_MIN = config.CANDLE_COOLDOWN_MINUTES

db = get_central_db()
stocks = json.load(open('fo_stocks.json'))['stocks']
candles_by = db.get_intraday_candles_batch(stocks, config.INTRADAY_CANDLE_INTERVAL, limit=200)
today = datetime.now().date().isoformat()

alerts = []
for symbol, candles in candles_by.items():
    if len(candles) < 12:
        continue
    last_alert = {}  # direction -> datetime of last alert (for cooldown)
    for i in range(11, len(candles)):
        ts = candles[i]['date']
        if not str(ts).startswith(today):     # only count confirmations that happened TODAY
            continue
        sig = detect_reversal_confirmation(candles[:i + 1], H, S)
        if not sig:
            continue
        t = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
        d = sig['direction']
        prev = last_alert.get(d)
        if prev and (t - prev).total_seconds() / 60 < COOLDOWN_MIN:
            continue  # cooldown suppresses, same as live
        last_alert[d] = t
        alerts.append({
            'symbol': symbol, 'time': t.strftime('%H:%M'), 'dir': d,
            'pattern': sig['pattern'], 'entry': sig['entry'], 'stop': sig['stop'],
            'target': sig['target'], 'vol': sig['volume_ratio'], 'conf': sig['confidence'],
        })

alerts.sort(key=lambda a: a['time'])
bull = [a for a in alerts if a['dir'] == 'BULLISH']
bear = [a for a in alerts if a['dir'] == 'BEARISH']
print(f"=== Candle reversal replay for {today} (up to now) ===")
print(f"Universe: {len(candles_by)} stocks with candles | vol≥{config.CANDLE_CONFIRM_VOLUME_MULT}× avg, "
      f"conf≥{config.CANDLE_MIN_CONFIDENCE}, cooldown {COOLDOWN_MIN}m")
print(f"TOTAL alerts today: {len(alerts)}  ({len(bull)} bullish hammer, {len(bear)} bearish star)")
print()
for a in alerts:
    rr = abs(a['target'] - a['entry']) / abs(a['entry'] - a['stop']) if a['entry'] != a['stop'] else 0
    arrow = '🟢' if a['dir'] == 'BULLISH' else '🔴'
    print(f"  {a['time']} {arrow} {a['symbol']:<14} {a['pattern']:<14} "
          f"entry {a['entry']:.2f} stop {a['stop']:.2f} tgt {a['target']:.2f} "
          f"(R:R {rr:.1f}) vol {a['vol']:.1f}× conf {a['conf']:.1f}")
