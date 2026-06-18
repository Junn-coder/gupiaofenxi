#!/usr/bin/env python3
"""
train_flat_erupt.py — train a classifier that finds the flat stocks that will ERUPT.

Loads flat_dataset.parquet (built by build_flat_dataset.py), which contains ONLY quiet
coiling stock-days. The model learns to separate those that go on to +10%+ forward return
from those that stay flat.

Goal: HIGH PRECISION — when the model says "buy", it's a real eruption. We accept lower
recall (miss some good ones) because wrong picks on flat stocks lose very little.

Trains HistGB + logistic, reports precision/recall by threshold, saves the best model.
"""
import os
import sys
import argparse

import numpy as np
import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score, precision_recall_curve, average_precision_score
import joblib

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")
DATASET_PATH = os.path.join(SHARE_DIR, "flat_dataset.parquet")
MODEL_PATH = os.path.join(SHARE_DIR, "flat_erupt_scorer.joblib")

SEED = 42


def load_dataset():
    if not os.path.exists(DATASET_PATH):
        # try csv.gz fallback
        csv_path = os.path.join(SHARE_DIR, "flat_dataset.csv.gz")
        if os.path.exists(csv_path):
            return pd.read_csv(csv_path)
        sys.exit(f"no dataset at {DATASET_PATH} — run build_flat_dataset.py first")

    return pd.read_parquet(DATASET_PATH)


def report_at_thresholds(y_true, scores, thresholds=(50, 60, 70, 80)):
    """Precision/recall at each score threshold."""
    lines = []
    for t in thresholds:
        pred = scores >= t
        tp = (pred & (y_true == 1)).sum()
        fp = (pred & (y_true == 0)).sum()
        fn = ((~pred) & (y_true == 1)).sum()
        tn = ((~pred) & (y_true == 0)).sum()
        prec = tp / (tp + fp) * 100 if (tp + fp) > 0 else 0
        rec = tp / (tp + fn) * 100 if (tp + fn) > 0 else 0
        lines.append(
            f"  score>={t:.0f}  precision={prec:5.1f}%  recall={rec:5.1f}%  "
            f"tp={tp:4d}  fp={fp:4d}  fn={fn:4d}  tn={tn:4d}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Train the flat-erupt classifier")
    ap.add_argument("--out", default=MODEL_PATH, help="model output path")
    args = ap.parse_args()

    print("Loading flat-erupt dataset...", file=sys.stderr)
    data = load_dataset()

    # Feature columns — everything except code, Date, fwd_net, label
    skip_cols = {"code", "Date", "fwd_net", "label"}
    feat_cols = [c for c in data.columns if c not in skip_cols]
    y = data["label"].values
    X = data[feat_cols].copy()

    # Impute mcap_b NaN with median
    if "mcap_b" in X.columns:
        med = X["mcap_b"].median()
        X["mcap_b"] = X["mcap_b"].fillna(med)
    else:
        med = 0

    pos = int(y.sum())
    neg = len(y) - pos
    print(f"Dataset: {len(y):,} rows, {pos} erupt ({pos/len(y)*100:.1f}%), "
          f"{neg} flat, {len(feat_cols)} features", file=sys.stderr)

    Xtr, Xte, ytr, yte = train_test_split(
        X.values, y, test_size=0.20, stratify=y, random_state=SEED
    )
    print(f"Train: {len(ytr)}, Test: {len(yte)} (stratified)", file=sys.stderr)

    results = []

    # 1) Gradient-boosted trees
    gb = HistGradientBoostingClassifier(
        random_state=SEED, max_iter=300, learning_rate=0.08,
        class_weight="balanced"
    )
    gb.fit(Xtr, ytr)
    s_gb = gb.predict_proba(Xte)[:, 1] * 100
    auc_gb = roc_auc_score(yte, s_gb)
    ap_gb = average_precision_score(yte, s_gb)
    print(f"\n## HistGB  AUC={auc_gb:.3f}  AvgPrecision={ap_gb:.3f}", file=sys.stderr)
    print(report_at_thresholds(yte, s_gb), file=sys.stderr)
    results.append((ap_gb, "gb", gb, auc_gb))

    # 2) Logistic regression
    lr = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
    )
    lr.fit(Xtr, ytr)
    s_lr = lr.predict_proba(Xte)[:, 1] * 100
    auc_lr = roc_auc_score(yte, s_lr)
    ap_lr = average_precision_score(yte, s_lr)
    print(f"\n## Logistic  AUC={auc_lr:.3f}  AvgPrecision={ap_lr:.3f}", file=sys.stderr)
    print(report_at_thresholds(yte, s_lr), file=sys.stderr)
    results.append((ap_lr, "lr", lr, auc_lr))

    # Logistic readout
    coef = lr.named_steps["logisticregression"].coef_[0]
    order = np.argsort(np.abs(coef))[::-1][:10]

    def explain(name):
        engineered = {
            "mom20": "20-day momentum (%)",
            "mom5": "5-day momentum (%)",
            "pct_from_high250": "distance from 250d high (%)",
            "vol_ratio20": "volume / prior 20d avg",
            "ma_aligned": "MA 5>10>20 aligned (0/1)",
            "above_ma20": "close above 20d MA (0/1)",
            "range_contract": "5d range / 20d range",
            "turnover_yi": "daily turnover (100M yuan)",
        }
        if name in engineered:
            return engineered[name]
        if name == "mcap_b":
            return "market cap (B yuan)"
        if name.startswith("vr"):
            k = int(name[2:])
            return f"volume ratio, day D-{19 - k}"
        k = int(name[1:])
        return f"daily return, day D-{19 - k}"

    lines = []
    lines.append("=" * 60)
    lines.append("FLAT-ERUPT SCORER — find coiling stocks that will erupt +10% in 10d")
    lines.append(f"trained on {len(ytr):,}, tested on {len(yte):,} (20% stratified holdout)")
    lines.append(f"features: {len(feat_cols)}  base rate: {pos/len(y)*100:.1f}%")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"## HistGB  AUC={auc_gb:.3f}  AvgPrecision={ap_gb:.3f}")
    lines.append(report_at_thresholds(yte, s_gb))
    lines.append("")
    lines.append(f"## Logistic  AUC={auc_lr:.3f}  AvgPrecision={ap_lr:.3f}")
    lines.append(report_at_thresholds(yte, s_lr))
    lines.append("")
    lines.append("## Logistic readout — strongest precursors (standardized)")
    lines.append("   (+ pushes toward 'erupt', - toward 'stay flat')")
    for i in order:
        lines.append(f"   {coef[i]:+.3f}  {feat_cols[i]:<7}  {explain(feat_cols[i])}")
    report_txt = "\n".join(lines)

    # Save best model by average precision
    results.sort(key=lambda r: r[0], reverse=True)
    best_ap, best_name, best_model, best_auc = results[0]
    os.makedirs(SHARE_DIR, exist_ok=True)
    joblib.dump(
        {
            "model": best_model,
            "kind": best_name,
            "feat_cols": feat_cols,
            "mcap_median": float(med),
            "auc": best_auc,
            "avg_precision": best_ap,
        },
        args.out,
    )

    print("\n" + report_txt)
    print(f"\nBest: {best_name} (AvgPrecision={best_ap:.3f}, AUC={best_auc:.3f}) -> {args.out}")

    with open(os.path.join(SHARE_DIR, "flat_erupt_report.txt"), "w", encoding="utf-8") as f:
        f.write(report_txt + f"\n\nBest: {best_name} (AP={best_ap:.3f}, AUC={best_auc:.3f})\n")


if __name__ == "__main__":
    main()
