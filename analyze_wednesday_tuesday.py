#!/usr/bin/env python3
"""
Wednesday-Tuesday Direction Analysis

Hypothesis: If Wednesday closes UP, Tuesday expiry closes HIGHER than Wednesday close.
            If Wednesday closes DOWN, Tuesday expiry closes LOWER than Wednesday close.
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
import sys

from dotenv import load_dotenv
load_dotenv()

from kiteconnect import KiteConnect

# Setup Kite connection
API_KEY = os.getenv('KITE_API_KEY')
ACCESS_TOKEN = os.getenv('KITE_ACCESS_TOKEN')

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# Fetch 1 year of Nifty daily data
NIFTY_TOKEN = 256265
end_date = datetime.now()
start_date = end_date - timedelta(days=400)  # ~13 months for safety

print("=" * 80)
print("WEDNESDAY → TUESDAY EXPIRY CONTINUATION ANALYSIS")
print("=" * 80)
print(f"\nFetching Nifty daily data from {start_date.date()} to {end_date.date()}...")

nifty_data = kite.historical_data(
    instrument_token=NIFTY_TOKEN,
    from_date=start_date,
    to_date=end_date,
    interval='day'
)

print(f"Fetched {len(nifty_data)} trading days")
print(f"Date range: {nifty_data[0]['date'].date()} to {nifty_data[-1]['date'].date()}")

# Create a date-indexed dictionary
date_to_data = {d['date'].date(): d for d in nifty_data}
dates_list = sorted(date_to_data.keys())

# Find all Wednesdays and their corresponding Tuesdays
wednesdays = [d for d in dates_list if d.weekday() == 2]  # Wednesday = 2
tuesdays = [d for d in dates_list if d.weekday() == 1]    # Tuesday = 1

print(f"\nFound {len(wednesdays)} Wednesdays and {len(tuesdays)} Tuesdays in the data")

# Analysis: For each Wednesday, find the NEXT Tuesday (expiry)
results = []

for wed in wednesdays:
    # Find the next Tuesday after this Wednesday
    next_tuesday = None
    for tue in tuesdays:
        if tue > wed:
            next_tuesday = tue
            break

    if next_tuesday is None:
        continue

    # Also need the day BEFORE Wednesday for direction calculation
    wed_idx = dates_list.index(wed)
    if wed_idx == 0:
        continue
    prev_day = dates_list[wed_idx - 1]

    # Get data
    wed_data = date_to_data[wed]
    tue_data = date_to_data[next_tuesday]
    prev_data = date_to_data[prev_day]

    # Wednesday direction: Close vs Previous Close
    wed_direction = "UP" if wed_data['close'] > prev_data['close'] else "DOWN"
    wed_change = ((wed_data['close'] - prev_data['close']) / prev_data['close']) * 100

    # Tuesday vs Wednesday close (the key metric)
    tue_vs_wed = tue_data['close'] - wed_data['close']
    tue_vs_wed_pct = (tue_vs_wed / wed_data['close']) * 100

    # Did the move continue in the same direction?
    continuation = (wed_direction == "UP" and tue_vs_wed > 0) or (wed_direction == "DOWN" and tue_vs_wed < 0)

    results.append({
        'wednesday': wed,
        'tuesday': next_tuesday,
        'wed_direction': wed_direction,
        'wed_change': wed_change,
        'wed_close': wed_data['close'],
        'tue_close': tue_data['close'],
        'tue_vs_wed': tue_vs_wed,
        'tue_vs_wed_pct': tue_vs_wed_pct,
        'continuation': continuation
    })

# Calculate statistics
total = len(results)
continuations = sum(1 for r in results if r['continuation'])
accuracy = (continuations / total * 100) if total > 0 else 0

print("\n" + "=" * 80)
print("HYPOTHESIS: Wednesday direction continues till Tuesday expiry")
print("=" * 80)

# Breakdown by Wednesday direction
wed_up = [r for r in results if r['wed_direction'] == "UP"]
wed_down = [r for r in results if r['wed_direction'] == "DOWN"]

wed_up_continued = sum(1 for r in wed_up if r['continuation'])
wed_down_continued = sum(1 for r in wed_down if r['continuation'])

print(f"\n┌─────────────────────────────────────────────────────────────────────────────┐")
print(f"│  WHEN WEDNESDAY CLOSES UP ({len(wed_up)} weeks)                                        │")
print(f"├─────────────────────────────────────────────────────────────────────────────┤")
print(f"│  Tuesday expiry > Wednesday close: {wed_up_continued} times ({wed_up_continued/len(wed_up)*100:.1f}%)                        │")
print(f"│  Tuesday expiry < Wednesday close: {len(wed_up) - wed_up_continued} times ({(len(wed_up) - wed_up_continued)/len(wed_up)*100:.1f}%)                        │")
print(f"└─────────────────────────────────────────────────────────────────────────────┘")

print(f"\n┌─────────────────────────────────────────────────────────────────────────────┐")
print(f"│  WHEN WEDNESDAY CLOSES DOWN ({len(wed_down)} weeks)                                      │")
print(f"├─────────────────────────────────────────────────────────────────────────────┤")
print(f"│  Tuesday expiry < Wednesday close: {wed_down_continued} times ({wed_down_continued/len(wed_down)*100:.1f}%)                        │")
print(f"│  Tuesday expiry > Wednesday close: {len(wed_down) - wed_down_continued} times ({(len(wed_down) - wed_down_continued)/len(wed_down)*100:.1f}%)                        │")
print(f"└─────────────────────────────────────────────────────────────────────────────┘")

print(f"\n{'='*80}")
print(f"OVERALL: Direction continues {continuations}/{total} times = {accuracy:.1f}%")
print(f"{'='*80}")

# Detailed table
print(f"\n--- Last 15 Weeks (Detailed) ---")
print(f"{'Wednesday':<12} {'Wed Close':<12} {'Direction':<10} {'Tuesday':<12} {'Tue Close':<12} {'Tue vs Wed':<12} {'Continued?':<10}")
print("-" * 95)
for r in results[-15:]:
    continued_str = "✓ YES" if r['continuation'] else "✗ NO"
    print(f"{r['wednesday']!s:<12} {r['wed_close']:<12.2f} {r['wed_direction']:<10} {r['tuesday']!s:<12} {r['tue_close']:<12.2f} {r['tue_vs_wed_pct']:>+8.2f}%    {continued_str}")

# Average moves
print(f"\n--- Average Moves (Wed Close → Tue Expiry) ---")
avg_tue_move_after_wed_up = sum(r['tue_vs_wed_pct'] for r in wed_up) / len(wed_up) if wed_up else 0
avg_tue_move_after_wed_down = sum(r['tue_vs_wed_pct'] for r in wed_down) / len(wed_down) if wed_down else 0

print(f"After Wednesday UP:   Tuesday moves {avg_tue_move_after_wed_up:+.2f}% on average (from Wed close)")
print(f"After Wednesday DOWN: Tuesday moves {avg_tue_move_after_wed_down:+.2f}% on average (from Wed close)")

# Statistical significance
print(f"\n--- Statistical Significance ---")
from math import comb
p_value = sum(comb(total, k) * (0.5 ** total) for k in range(continuations, total + 1))
print(f"P-value: {p_value:.4f}")
if p_value < 0.05:
    print("→ STATISTICALLY SIGNIFICANT (p < 0.05)")
elif p_value < 0.10:
    print("→ Marginally significant (p < 0.10)")
else:
    print("→ Not statistically significant (p >= 0.10)")

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)
if accuracy >= 60:
    print(f"✓ Your hunch is CORRECT! {accuracy:.1f}% of the time, Wednesday's direction")
    print(f"  continues till Tuesday expiry. This is a meaningful edge.")
elif accuracy >= 55:
    print(f"~ Your hunch has SOME merit. {accuracy:.1f}% accuracy shows a mild tendency")
    print(f"  for continuation, but it's not a strong signal.")
else:
    print(f"✗ The data doesn't support this hypothesis. {accuracy:.1f}% is close to random.")
