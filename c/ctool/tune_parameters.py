#!/usr/bin/env python3
"""
Parameter tuning: test multiple configs to find best signal strength.
"""

import os
import csv
import json
import glob
import math
from collections import defaultdict
from itertools import product

# ============================================================================
# COPY OF CORE ANALYZER FUNCTIONS (from break_signal_analyzer.py)
# ============================================================================

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
        return [None] * len(series)
    deltas = [series[i] - series[i-1] for i in range(1, len(series))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result = [None] * (period + 1)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi_val = 100 - (100 / (1 + rs)) if rs >= 0 else 0
        result.append(rsi_val)
    return result

def momentum(series, period=10):
    if len(series) < period + 1:
        return [None] * len(series)
    result = [None] * period
    for i in range(period, len(series)):
        pct = (series[i] - series[i-period]) / series[i-period] * 100 if series[i-period] else 0
        result.append(pct)
    return result

def load_stock_data(csv_path):
    import csv as csvmod
    with open(csv_path) as f:
        reader = csvmod.DictReader(f)
        rows = []
        for row in reader:
            try:
                rows.append({'date': row['Date'], 'close': float(row['Close']), 'high': float(row['High']), 'volume': float(row['Volume'])})
            except:
                pass
    return sorted(rows, key=lambda r: r['date'])

def find_break_days(data, threshold):
    breaks = []
    for i in range(1, len(data)):
        prev_close = data[i-1]['close']
        curr_close = data[i]['close']
        if (curr_close - prev_close) / prev_close >= threshold:
            breaks.append((i, data[i]['date']))
    return breaks

def compute_features(window, ma_periods, rsi_period, momentum_period, vol_sma_period):
    closes = [r['close'] for r in window]
    highs = [r['high'] for r in window]
    volumes = [r['volume'] for r in window]
    if len(closes) < 20:
        return None
    features = {}
    features['close_pct_change'] = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else 0
    features['high_pct_change'] = (max(highs) - min(highs)) / min(highs) * 100 if min(highs) else 0
    for ma_p in ma_periods:
        ma_vals = sma(closes, ma_p)
        if ma_vals[-1]:
            dist = (closes[-1] - ma_vals[-1]) / ma_vals[-1] * 100
            features[f'dist_to_ma{ma_p}'] = dist
            features[f'above_ma{ma_p}'] = 1 if closes[-1] > ma_vals[-1] else 0
    vol_ma = sma(volumes, vol_sma_period)
    if vol_ma[-1]:
        features['vol_vs_ma'] = volumes[-1] / vol_ma[-1]
    features['vol_trend'] = (volumes[-1] - volumes[0]) / volumes[0] * 100 if volumes[0] else 0
    rsi_vals = rsi(closes, rsi_period)
    if rsi_vals[-1]:
        features['rsi'] = rsi_vals[-1]
    mom_vals = momentum(closes, momentum_period)
    if mom_vals[-1]:
        features['momentum'] = mom_vals[-1]
    features['dist_to_52w_high'] = (closes[-1] - max(closes)) / max(closes) * 100 if max(closes) else 0
    daily_rets = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes)) if closes[i-1]]
    features['volatility'] = std_dev(daily_rets) if daily_rets else 0
    if len(closes) >= 5:
        tail = closes[-5:]
        features['last_5_min'] = min(tail)
        features['distance_from_5d_low'] = (closes[-1] - min(tail)) / min(tail) * 100 if min(tail) else 0
    return features

def run_config(config):
    """Run analysis with given config. Return top signal strength."""
    print(f"  Testing: break={config['break_threshold']:.2f}, lookback={config['lookback_days']}, "
          f"vol_sma={config['vol_sma_period']}, rsi={config['rsi_period']}, ratio={config['train_ratio']:.2f}...", end=" ", flush=True)

    all_windows = []
    stock_files_map = defaultdict(list)
    for fpath in sorted(glob.glob('break_stocks_ceiling/*.csv')):
        fname = os.path.basename(fpath)
        stock_code = fname.split('_')[0]
        stock_files_map[stock_code].append(fpath)

    stocks_to_process = list(stock_files_map.keys())[:100]  # Limit to 100 stocks for speed

    for stock_code in stocks_to_process:
        all_data = []
        for fpath in sorted(stock_files_map[stock_code]):
            data = load_stock_data(fpath)
            all_data.extend(data)

        seen_dates = set()
        unique_data = []
        for row in sorted(all_data, key=lambda r: r['date']):
            if row['date'] not in seen_dates:
                unique_data.append(row)
                seen_dates.add(row['date'])

        data = unique_data
        if len(data) < 50:
            continue

        breaks = find_break_days(data, config['break_threshold'])

        if breaks:
            for break_idx, break_date in breaks:
                start_idx = max(0, break_idx - config['lookback_days'])
                window = data[start_idx:break_idx]
                if len(window) >= 20:
                    all_windows.append((window, break_date, 1))

        if breaks:
            break_indices = set()
            for break_idx, _ in breaks:
                for offset in range(-15, 16):
                    if 0 <= break_idx + offset < len(data):
                        break_indices.add(break_idx + offset)

            for start_idx in range(0, len(data) - config['lookback_days'], 25):
                window_range = set(range(start_idx, min(start_idx + config['lookback_days'], len(data))))
                if not window_range.intersection(break_indices):
                    window = data[start_idx:start_idx + config['lookback_days']]
                    if len(window) >= 20:
                        all_windows.append((window, data[start_idx + len(window) - 1]['date'], 0))

    if not all_windows:
        print("✗ (no windows)")
        return 0

    # Compute features
    feature_rows = []
    for window, break_date, label in all_windows:
        feats = compute_features(window, config['ma_periods'], config['rsi_period'], config['momentum_period'], config['vol_sma_period'])
        if feats:
            feats['label'] = label
            feature_rows.append(feats)

    if not feature_rows:
        print("✗ (no features)")
        return 0

    # Fill NaNs
    all_keys = set()
    for row in feature_rows:
        all_keys.update(k for k in row.keys() if k != 'label')

    means = {}
    for key in all_keys:
        vals = [row[key] for row in feature_rows if key in row and row[key] is not None]
        means[key] = sum(vals) / len(vals) if vals else 0

    for row in feature_rows:
        for key in all_keys:
            if key not in row or row[key] is None:
                row[key] = means[key]

    # Compute correlation (top signal strength)
    top_signal = 0
    for key in all_keys:
        vals = [row[key] for row in feature_rows]
        labels = [row['label'] for row in feature_rows]
        mean_val = sum(vals) / len(vals) if vals else 0
        mean_label = sum(labels) / len(labels) if labels else 0
        numerator = sum((vals[i] - mean_val) * (labels[i] - mean_label) for i in range(len(vals)))
        denom_var_v = sum((vals[i] - mean_val) ** 2 for i in range(len(vals)))
        denom_var_l = sum((labels[i] - mean_label) ** 2 for i in range(len(labels)))
        if denom_var_v > 0 and denom_var_l > 0:
            corr = abs(numerator / math.sqrt(denom_var_v * denom_var_l))
            top_signal = max(top_signal, corr)

    print(f"✓ signal={top_signal:.4f}")
    return top_signal


def main():
    print("\n" + "="*80)
    print("PARAMETER TUNING: Find optimal config for pre-break signals")
    print("="*80 + "\n")

    # Base config
    base = {
        "break_threshold": 0.10,
        "lookback_days": 30,
        "lookahead_days": 5,
        "vol_sma_period": 20,
        "rsi_period": 14,
        "momentum_period": 10,
        "ma_periods": [5, 10, 20, 60],
        "distance_to_52wk_high": True,
        "train_ratio": 0.60,
    }

    # Test combinations
    results = []

    configs_to_test = [
        # Test break threshold
        {"break_threshold": 0.10},
        {"break_threshold": 0.15},
        {"break_threshold": 0.20},

        # Test lookback window
        {"lookback_days": 15},
        {"lookback_days": 20},
        {"lookback_days": 30},
        {"lookback_days": 40},

        # Test volume SMA
        {"vol_sma_period": 10},
        {"vol_sma_period": 20},
        {"vol_sma_period": 30},

        # Test RSI period
        {"rsi_period": 10},
        {"rsi_period": 14},
        {"rsi_period": 20},

        # Test train ratio
        {"train_ratio": 0.50},
        {"train_ratio": 0.60},
        {"train_ratio": 0.70},

        # Best combinations
        {"break_threshold": 0.15, "lookback_days": 20, "vol_sma_period": 15, "rsi_period": 14},
        {"break_threshold": 0.10, "lookback_days": 30, "vol_sma_period": 20, "rsi_period": 10},
        {"break_threshold": 0.20, "lookback_days": 40, "vol_sma_period": 25, "rsi_period": 14},
    ]

    for i, param_override in enumerate(configs_to_test, 1):
        config = base.copy()
        config.update(param_override)
        signal_strength = run_config(config)
        results.append((signal_strength, config.copy()))

    # Sort by signal strength (descending)
    results.sort(key=lambda x: x[0], reverse=True)

    print("\n" + "="*80)
    print("TOP 10 CONFIGURATIONS")
    print("="*80 + "\n")

    for rank, (strength, config) in enumerate(results[:10], 1):
        print(f"{rank}. Signal strength: {strength:.4f}")
        print(f"   break_threshold: {config['break_threshold']}")
        print(f"   lookback_days: {config['lookback_days']}")
        print(f"   vol_sma_period: {config['vol_sma_period']}")
        print(f"   rsi_period: {config['rsi_period']}")
        print()

    # Save best config
    best_config = results[0][1]
    with open('break_analysis/best_config.json', 'w') as f:
        json.dump(best_config, f, indent=2)

    print(f"✓ Best config saved to break_analysis/best_config.json\n")
    print("Next: run with best config:")
    print(f"  cd ~/git/gprun/c/ctool")
    print(f"  python3 break_signal_analyzer.py  # edit CONFIG in script first")


if __name__ == '__main__':
    main()
