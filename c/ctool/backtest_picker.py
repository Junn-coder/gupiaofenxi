#!/usr/bin/env python3
"""
Backtest: score the test set samples and check accuracy.
Shows: if you ran the picker on test data, how many actually broke?
"""

import json
import math

def std_dev(values):
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)

def rsi_from_features(rsi_val):
    """Score based on RSI value."""
    if rsi_val is None:
        return 0
    if 60 <= rsi_val <= 80:
        return 100
    elif 50 <= rsi_val < 60 or 80 < rsi_val <= 90:
        return 70
    elif 40 <= rsi_val < 50 or 90 < rsi_val:
        return 30
    else:
        return 10

def vol_score(vol):
    """Score volatility."""
    if vol > 3:
        return 90
    elif vol > 2:
        return 70
    elif vol > 1:
        return 50
    else:
        return 20

def ma_dist_score(dist):
    """Score distance to 20-day MA."""
    if 2 <= dist <= 8:
        return 100
    elif 0 <= dist < 2 or 8 < dist <= 12:
        return 70
    elif -2 <= dist < 0 or dist > 12:
        return 30
    else:
        return 10

def momentum_score(mom):
    """Score momentum."""
    if mom is None:
        return 50
    if mom > 5:
        return 90
    elif mom > 0:
        return 70
    elif mom > -5:
        return 40
    else:
        return 10

def price_range_score(close_pct, high_pct):
    """Score price range."""
    avg_range = (abs(close_pct) + abs(high_pct)) / 2
    if avg_range > 8:
        return 90
    elif avg_range > 5:
        return 70
    elif avg_range > 3:
        return 50
    else:
        return 20

def score_sample(sample):
    """Score a single test sample (feature dict)."""
    scores = []

    # RSI
    if 'rsi' in sample:
        scores.append(rsi_from_features(sample['rsi']))

    # Volatility
    if 'volatility' in sample:
        scores.append(vol_score(sample['volatility']))

    # Distance to MA20
    if 'dist_to_ma20' in sample:
        scores.append(ma_dist_score(sample['dist_to_ma20']))

    # Momentum
    if 'momentum' in sample:
        scores.append(momentum_score(sample['momentum']))

    # Price range
    if 'close_pct_change' in sample and 'high_pct_change' in sample:
        scores.append(price_range_score(sample['close_pct_change'], sample['high_pct_change']))

    overall = sum(scores) / len(scores) if scores else 0
    return overall

def main():
    print("\n" + "="*80)
    print("BACKTEST: Score test set samples, check if actual breaks rank high")
    print("="*80 + "\n")

    # Load test samples
    with open('break_analysis/test_samples.json') as f:
        test_samples = json.load(f)

    print(f"Loaded {len(test_samples)} test samples\n")

    # Score each sample
    scored = []
    for i, sample in enumerate(test_samples):
        score = score_sample(sample)
        label = sample.get('label', 0)
        scored.append({
            'idx': i,
            'score': score,
            'label': label,
            'break_date': sample.get('break_date', '?'),
        })

    # Sort by score (descending)
    scored.sort(key=lambda x: x['score'], reverse=True)

    # Analyze top-K picks
    top_k_values = [3, 10, 25, 50, 100]
    print("Accuracy if we picked top-K scores:\n")
    print(f"{'Top-K':<8} {'Actual Breaks':<16} {'Hit Rate':<12} {'Result':<50}")
    print("-" * 80)

    for k in top_k_values:
        top_k = scored[:k]
        breaks_in_top = sum(1 for s in top_k if s['label'] == 1)
        hit_rate = breaks_in_top / k * 100 if k > 0 else 0

        # Interpretation
        if hit_rate >= 80:
            result = "✓ Excellent — tool picks breaks reliably"
        elif hit_rate >= 70:
            result = "✓ Good — most picks break"
        elif hit_rate >= 60:
            result = "△ Fair — mixed results"
        else:
            result = "✗ Weak — random or worse"

        print(f"{k:<8} {breaks_in_top}/{k:<14} {hit_rate:>6.1f}%       {result:<50}")

    print("\n" + "-"*80)

    # Analyze by score percentile
    print("\nBREAK RATE BY SCORE PERCENTILE:\n")
    print(f"{'Score Range':<20} {'Samples':<12} {'Breaks':<12} {'Break %':<12}")
    print("-" * 60)

    percentiles = [
        (90, 100, "90-100"),
        (80, 90, "80-90"),
        (70, 80, "70-80"),
        (60, 70, "60-70"),
        (50, 60, "50-60"),
        (0, 50, "0-50"),
    ]

    for min_score, max_score, label in percentiles:
        in_range = [s for s in scored if min_score <= s['score'] < max_score]
        breaks = sum(1 for s in in_range if s['label'] == 1)
        break_pct = breaks / len(in_range) * 100 if in_range else 0
        print(f"{label:<20} {len(in_range):<12} {breaks:<12} {break_pct:>6.1f}%")

    print("\n" + "-"*80)
    print("\nTOP 5 HIGH-SCORE SAMPLES (should be actual breaks):\n")

    for i, item in enumerate(scored[:5], 1):
        status = "✓ BREAK" if item['label'] == 1 else "✗ no break"
        print(f"{i}. Score {item['score']:.1f}/100 → {status} ({item['break_date']})")

    print("\n" + "-"*80)
    print("\nBOTTOM 5 LOW-SCORE SAMPLES (should NOT be breaks):\n")

    for i, item in enumerate(scored[-5:], 1):
        status = "✓ correctly no-break" if item['label'] == 0 else "✗ missed a break"
        print(f"{i}. Score {item['score']:.1f}/100 → {status} ({item['break_date']})")

    print("\n" + "="*80 + "\n")

    # Summary
    total_breaks = sum(1 for s in scored if s['label'] == 1)
    top_3_breaks = sum(1 for s in scored[:3] if s['label'] == 1)
    top_10_breaks = sum(1 for s in scored[:10] if s['label'] == 1)

    print(f"SUMMARY:")
    print(f"  Total test samples: {len(scored)}")
    print(f"  Actual breaks in test set: {total_breaks} ({total_breaks/len(scored)*100:.1f}%)")
    print(f"  If you picked top 3: {top_3_breaks}/3 would break ({top_3_breaks/3*100:.0f}%)")
    print(f"  If you picked top 10: {top_10_breaks}/10 would break ({top_10_breaks/10*100:.0f}%)")
    print()


if __name__ == '__main__':
    main()
