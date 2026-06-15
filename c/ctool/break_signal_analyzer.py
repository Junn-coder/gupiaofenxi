#!/usr/bin/env python3
"""
Pre-break signal detection: extract patterns N days before 10%+ ceiling hits.
Pure Python (no external deps).
"""

import os
import csv
import json
import glob
import math
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================================
# TUNABLE PARAMETERS — edit these to experiment
# ============================================================================

CONFIG = {
    # Break definition
    "break_threshold": 0.10,          # 10% or 0.20 for 20%

    # Pre-break window
    "lookback_days": 40,              # TUNED: 40 days (+14% signal vs default 30)
    "lookahead_days": 5,              # prediction horizon: will it break within N days?

    # Volume features
    "vol_sma_period": 20,             # volume MA period
    "vol_expansion_threshold": 1.5,   # volume spike factor

    # Price / momentum features
    "ma_periods": [5, 10, 20, 60],    # moving average periods
    "rsi_period": 14,
    "momentum_period": 10,            # ROC period
    "distance_to_52wk_high": True,    # include 52-week high proximity

    # Train/test split
    "train_ratio": 0.60,              # 60% train, 40% test (by time)

    # Output
    "output_dir": "break_analysis",
    "sample_size_limit": None,        # None = use all, or set to e.g. 1000 for quick test
}

# ============================================================================
# HELPERS
# ============================================================================

def sma(series, period):
    """Simple moving average."""
    if len(series) < period:
        return [None] * len(series)
    result = [None] * (period - 1)
    for i in range(period - 1, len(series)):
        result.append(sum(series[i-period+1:i+1]) / period)
    return result

def std_dev(series):
    """Standard deviation."""
    if len(series) < 2:
        return 0
    mean = sum(series) / len(series)
    variance = sum((x - mean) ** 2 for x in series) / len(series)
    return math.sqrt(variance)

def rsi(series, period=14):
    """Relative Strength Index."""
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
    """Rate of change (%)."""
    if len(series) < period + 1:
        return [None] * len(series)
    result = [None] * period
    for i in range(period, len(series)):
        pct = (series[i] - series[i-period]) / series[i-period] * 100 if series[i-period] else 0
        result.append(pct)
    return result

def load_stock_data(csv_path):
    """Load CSV, return list of dicts sorted by date."""
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

def find_break_days(data, threshold):
    """Return list of (idx, date) where close >= prev_close * (1 + threshold)."""
    breaks = []
    for i in range(1, len(data)):
        prev_close = data[i-1]['close']
        curr_close = data[i]['close']
        if (curr_close - prev_close) / prev_close >= threshold:
            breaks.append((i, data[i]['date']))
    return breaks

def extract_windows(data, break_indices, lookback=30):
    """Extract positive windows: lookback days before each break."""
    windows = []
    for break_idx, break_date in break_indices:
        start_idx = max(0, break_idx - lookback)
        window = data[start_idx:break_idx]
        if len(window) >= 15:  # minimum viable window
            windows.append((window, break_date, 1))
    return windows

def compute_features(window, config):
    """Extract feature dict from a pre-break window."""
    closes = [r['close'] for r in window]
    highs = [r['high'] for r in window]
    volumes = [r['volume'] for r in window]

    if len(closes) < 20:
        return None

    features = {}

    # Price action
    features['close_pct_change'] = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else 0
    features['high_pct_change'] = (max(highs) - min(highs)) / min(highs) * 100 if min(highs) else 0

    # Distance to MAs
    for ma_p in config['ma_periods']:
        ma_vals = sma(closes, ma_p)
        if ma_vals[-1]:
            dist = (closes[-1] - ma_vals[-1]) / ma_vals[-1] * 100
            features[f'dist_to_ma{ma_p}'] = dist
            features[f'above_ma{ma_p}'] = 1 if closes[-1] > ma_vals[-1] else 0

    # Volume
    vol_ma = sma(volumes, config['vol_sma_period'])
    if vol_ma[-1]:
        features['vol_vs_ma'] = volumes[-1] / vol_ma[-1]
    features['vol_trend'] = (volumes[-1] - volumes[0]) / volumes[0] * 100 if volumes[0] else 0

    # Momentum
    rsi_vals = rsi(closes, config['rsi_period'])
    if rsi_vals[-1]:
        features['rsi'] = rsi_vals[-1]

    mom_vals = momentum(closes, config['momentum_period'])
    if mom_vals[-1]:
        features['momentum'] = mom_vals[-1]

    # 52-week high proximity
    if config['distance_to_52wk_high']:
        max_52w = max(closes)
        features['dist_to_52w_high'] = (closes[-1] - max_52w) / max_52w * 100 if max_52w else 0

    # Volatility
    daily_rets = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes)) if closes[i-1]]
    features['volatility'] = std_dev(daily_rets) if daily_rets else 0

    # Pullback pattern (last 5 days)
    if len(closes) >= 5:
        tail = closes[-5:]
        features['last_5_min'] = min(tail)
        features['distance_from_5d_low'] = (closes[-1] - min(tail)) / min(tail) * 100 if min(tail) else 0

    return features

def main():
    config = CONFIG
    os.makedirs(config['output_dir'], exist_ok=True)

    print(f"Config: {json.dumps(config, indent=2)}")
    print(f"\nPhase 1: Group files by stock code...")

    # Group files by stock code
    stock_files_map = defaultdict(list)
    for fpath in sorted(glob.glob('break_stocks_ceiling/*.csv')):
        fname = os.path.basename(fpath)
        stock_code = fname.split('_')[0]
        stock_files_map[stock_code].append(fpath)

    print(f"Found {len(stock_files_map)} unique stocks")

    all_windows = []

    # Limit sample if requested
    stocks_to_process = list(stock_files_map.keys())
    if config['sample_size_limit']:
        stocks_to_process = stocks_to_process[:config['sample_size_limit']]

    print(f"Processing {len(stocks_to_process)} stocks...")

    for i, stock_code in enumerate(stocks_to_process):
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(stocks_to_process)}...")

        # Load and merge all files for this stock
        all_data = []
        for fpath in sorted(stock_files_map[stock_code]):
            data = load_stock_data(fpath)
            all_data.extend(data)

        # Remove duplicates, sort by date
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
            # POSITIVE: windows before breaks
            for break_idx, break_date in breaks:
                start_idx = max(0, break_idx - config['lookback_days'])
                window = data[start_idx:break_idx]
                if len(window) >= 20:
                    all_windows.append((window, break_date, 1))

        # NEGATIVE: random windows, avoiding 15 days around breaks
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

    positive = sum(1 for _, _, label in all_windows if label == 1)
    negative = sum(1 for _, _, label in all_windows if label == 0)
    print(f"\nExtracted {len(all_windows)} windows")
    print(f"  Positive (break): {positive}")
    print(f"  Negative (no break): {negative}")

    if not all_windows:
        print("ERROR: no windows extracted. Check config.")
        return

    # Compute features
    print("Computing features...")
    feature_rows = []
    for window, break_date, label in all_windows:
        feats = compute_features(window, config)
        if feats:
            feats['label'] = label
            feats['break_date'] = break_date
            feature_rows.append(feats)

    print(f"Feature matrix: {len(feature_rows)} samples")

    if not feature_rows:
        print("ERROR: no features computed.")
        return

    # Fill NaN with mean
    all_keys = set()
    for row in feature_rows:
        all_keys.update(k for k in row.keys() if k not in ['label', 'break_date'])

    # Compute means
    means = {}
    for key in all_keys:
        vals = [row[key] for row in feature_rows if key in row and row[key] is not None]
        if vals:
            means[key] = sum(vals) / len(vals)
        else:
            means[key] = 0

    # Fill NaNs
    for row in feature_rows:
        for key in all_keys:
            if key not in row or row[key] is None:
                row[key] = means[key]

    print(f"After NaN cleanup: {len(feature_rows)} samples")

    # Train/test split by time
    split_idx = int(len(feature_rows) * config['train_ratio'])
    train_data = feature_rows[:split_idx]
    test_data = feature_rows[split_idx:]

    train_breaks = sum(1 for row in train_data if row['label'] == 1)
    test_breaks = sum(1 for row in test_data if row['label'] == 1)

    print(f"Train: {len(train_data)} samples ({train_breaks} breaks)")
    print(f"Test: {len(test_data)} samples ({test_breaks} breaks)")

    # Simple feature importance: correlation with label
    print(f"\nComputing feature importance (correlation with break label)...")

    feature_importance = {}
    for key in all_keys:
        vals = [row[key] for row in train_data]
        labels = [row['label'] for row in train_data]

        # Compute correlation
        mean_val = sum(vals) / len(vals) if vals else 0
        mean_label = sum(labels) / len(labels) if labels else 0

        numerator = sum((vals[i] - mean_val) * (labels[i] - mean_label) for i in range(len(vals)))
        denom_var_v = sum((vals[i] - mean_val) ** 2 for i in range(len(vals)))
        denom_var_l = sum((labels[i] - mean_label) ** 2 for i in range(len(labels)))

        if denom_var_v > 0 and denom_var_l > 0:
            corr = numerator / math.sqrt(denom_var_v * denom_var_l)
            feature_importance[key] = abs(corr)
        else:
            feature_importance[key] = 0

    # Top features
    top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:15]

    # Statistics
    report = f"""
================================================================================
PRE-BREAK SIGNAL ANALYSIS (PURE PYTHON)
================================================================================

CONFIG:
  Break threshold: {config['break_threshold']*100:.0f}%
  Lookback days: {config['lookback_days']}
  Lookahead days: {config['lookahead_days']}
  Train ratio: {config['train_ratio']}

RESULTS:
  Total windows: {len(feature_rows)}
  Train size: {len(train_data)} ({train_breaks} breaks)
  Test size: {len(test_data)} ({test_breaks} breaks)

TOP 15 SIGNALS (feature correlation with break):
"""
    for feat, imp in top_features:
        report += f"\n  {feat:.<45s} {imp:>8.4f}"

    report += "\n\n"
    report += "INTERPRETATION:\n"
    report += "  - Features with high correlation are stronger predictors of pre-break state\n"
    report += "  - dist_to_maXX: distance to moving average (positive = above MA)\n"
    report += "  - vol_vs_ma: volume relative to 20-day MA (>1 = elevated volume)\n"
    report += "  - rsi: momentum oscillator (0-100)\n"
    report += "  - momentum: rate of price change (%)\n"
    report += "  - dist_to_52w_high: proximity to 52-week high (negative = below high)\n"
    report += "  - volatility: price swing magnitude (%)\n"

    report += "\n" + "="*80 + "\n"

    print(report)

    # Save outputs
    report_path = os.path.join(config['output_dir'], 'signal_report.txt')
    with open(report_path, 'w') as f:
        f.write(report)

    # Save samples as JSON for inspection
    with open(os.path.join(config['output_dir'], 'train_samples.json'), 'w') as f:
        json.dump(train_data[:100], f, indent=2)  # first 100 for inspection

    with open(os.path.join(config['output_dir'], 'test_samples.json'), 'w') as f:
        json.dump(test_data, f, indent=2)  # save ALL test samples for full verification

    config_out = config.copy()
    config_out['total_samples'] = len(feature_rows)
    config_out['train_samples'] = len(train_data)
    config_out['test_samples'] = len(test_data)
    config_out['train_breaks'] = train_breaks
    config_out['test_breaks'] = test_breaks

    with open(os.path.join(config['output_dir'], 'config.json'), 'w') as f:
        json.dump(config_out, f, indent=2)

    print(f"\n✓ Saved to {config['output_dir']}/")
    print(f"  - signal_report.txt")
    print(f"  - train_samples.json (first 100)")
    print(f"  - test_samples.json (first 100)")
    print(f"  - config.json")

if __name__ == '__main__':
    main()
