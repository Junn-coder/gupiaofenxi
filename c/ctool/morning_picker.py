#!/usr/bin/env python3
"""
Morning stock picker: score all stocks, return top 3 candidates.
Run daily to get today's best pre-break candidates.
"""

import os
import csv
import json
import glob
import math

# Tuned parameters from analysis
CONFIG = {
    "lookback_days": 40,
    "rsi_period": 14,
    "momentum_period": 10,
    "ma_periods": [5, 10, 20, 60],
    "vol_sma_period": 20,
}

def sma(series, period):
    if len(series) < period:
        return [None] * len(series)
    result = [None] * (period - 1)
    for i in range(period - 1, len(series)):
        result.append(sum(series[i-period+1:i+1]) / period)
    return result

def std_dev(series):
    if len(series) < 2:
        return 0
    mean = sum(series) / len(series)
    variance = sum((x - mean) ** 2 for x in series) / len(series)
    return math.sqrt(variance)

def rsi(series, period=14):
    if len(series) < period + 1:
        return None
    deltas = [series[i] - series[i-1] for i in range(1, len(series))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi_val = 100 - (100 / (1 + rs)) if rs >= 0 else 0
    return rsi_val

def momentum(series, period=10):
    if len(series) < period + 1:
        return None
    pct = (series[-1] - series[-period-1]) / series[-period-1] * 100 if series[-period-1] else 0
    return pct

def load_stock_data(csv_path):
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            try:
                rows.append({
                    'date': row['Date'],
                    'close': float(row['Close']),
                    'high': float(row['High']),
                    'volume': float(row['Volume']),
                })
            except:
                pass
    return sorted(rows, key=lambda r: r['date'])

def score_stock(data):
    """
    Compute pre-break score for a stock.
    Range: 0-100, where 100 = perfect pre-break setup.
    """
    if len(data) < CONFIG['lookback_days']:
        return None, None

    closes = [r['close'] for r in data[-CONFIG['lookback_days']:]]
    highs = [r['high'] for r in data[-CONFIG['lookback_days']:]]
    volumes = [r['volume'] for r in data[-CONFIG['lookback_days']:]]

    scores = []

    # Signal 1: RSI (target: 60-80, avoid <40 or >90)
    rsi_val = rsi(closes, CONFIG['rsi_period'])
    if rsi_val:
        if 60 <= rsi_val <= 80:
            scores.append(('RSI', 100))
        elif 50 <= rsi_val < 60 or 80 < rsi_val <= 90:
            scores.append(('RSI', 70))
        elif 40 <= rsi_val < 50 or 90 < rsi_val:
            scores.append(('RSI', 30))
        else:
            scores.append(('RSI', 10))

    # Signal 2: Volatility (higher = better, target >3%)
    daily_rets = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
    vol = std_dev(daily_rets) if daily_rets else 0
    if vol > 3:
        scores.append(('Volatility', 90))
    elif vol > 2:
        scores.append(('Volatility', 70))
    elif vol > 1:
        scores.append(('Volatility', 50))
    else:
        scores.append(('Volatility', 20))

    # Signal 3: Price vs 20-day MA (target: 2-8% above)
    ma20 = sma(closes, 20)
    if ma20[-1]:
        dist_pct = (closes[-1] - ma20[-1]) / ma20[-1] * 100
        if 2 <= dist_pct <= 8:
            scores.append(('MA20_Dist', 100))
        elif 0 <= dist_pct < 2 or 8 < dist_pct <= 12:
            scores.append(('MA20_Dist', 70))
        elif -2 <= dist_pct < 0 or dist_pct > 12:
            scores.append(('MA20_Dist', 30))
        else:
            scores.append(('MA20_Dist', 10))

    # Signal 4: Price momentum (positive = good)
    mom = momentum(closes, CONFIG['momentum_period'])
    if mom:
        if mom > 5:
            scores.append(('Momentum', 90))
        elif mom > 0:
            scores.append(('Momentum', 70))
        elif mom > -5:
            scores.append(('Momentum', 40))
        else:
            scores.append(('Momentum', 10))

    # Signal 5: Price range in period (high volatility = good)
    price_range = (max(closes) - min(closes)) / min(closes) * 100 if min(closes) else 0
    if price_range > 8:
        scores.append(('PriceRange', 90))
    elif price_range > 5:
        scores.append(('PriceRange', 70))
    elif price_range > 3:
        scores.append(('PriceRange', 50))
    else:
        scores.append(('PriceRange', 20))

    # Compute overall score
    score_dict = {name: val for name, val in scores}
    overall = sum(val for _, val in scores) / len(scores) if scores else 0

    return overall, score_dict


def main():
    print("\n" + "="*80)
    print("MORNING STOCK PICKER — Top 3 pre-break candidates")
    print("="*80 + "\n")

    # Load all stocks from stock_history_ak (updated daily by downa.py)
    stock_files = sorted(glob.glob('stock_history_ak/*.csv'))

    print(f"Scanning {len(stock_files)} stocks...")

    scores = []
    for fpath in stock_files:
        stock_code = os.path.basename(fpath).replace('.csv', '')
        unique_data = load_stock_data(fpath)

        if len(unique_data) < CONFIG['lookback_days']:
            continue

        score, details = score_stock(unique_data)
        if score and score > 0:
            latest = unique_data[-1]
            scores.append({
                'code': stock_code,
                'score': score,
                'details': details,
                'price': latest['close'],
                'date': latest['date'],
            })

    # Sort by score
    scores.sort(key=lambda x: x['score'], reverse=True)

    # Display top 3
    print(f"\n{'RANK':<6} {'STOCK':<10} {'SCORE':<8} {'PRICE':<10} {'SIGNALS':<60}")
    print("-" * 95)

    for i, item in enumerate(scores[:3], 1):
        signals_str = ", ".join(
            f"{name}:{val:.0f}"
            for name, val in sorted(item['details'].items(), key=lambda x: x[1], reverse=True)[:3]
        )
        print(f"{i:<6} {item['code']:<10} {item['score']:>6.1f} {item['price']:>9.2f}  {signals_str:<60}")

    print("\n" + "-" * 95)
    print("\nDETAILED VIEW:")
    print()

    for i, item in enumerate(scores[:3], 1):
        print(f"{i}. STOCK {item['code']} (Score: {item['score']:.1f}/100)")
        print(f"   Price: ¥{item['price']:.2f} | Date: {item['date']}")
        print(f"   Signals:")
        for name, val in sorted(item['details'].items(), key=lambda x: x[1], reverse=True):
            bar = "█" * int(val / 10) + "░" * (10 - int(val / 10))
            print(f"     {name:.<20} {val:>5.0f}/100  {bar}")
        print()

    # Save to file
    with open('morning_picks.txt', 'w') as f:
        f.write(f"{'RANK':<6} {'STOCK':<10} {'SCORE':<8} {'PRICE':<10}\n")
        f.write("-" * 40 + "\n")
        for i, item in enumerate(scores[:3], 1):
            f.write(f"{i:<6} {item['code']:<10} {item['score']:>6.1f} {item['price']:>9.2f}\n")

    print(f"✓ Results saved to morning_picks.txt\n")


if __name__ == '__main__':
    main()
