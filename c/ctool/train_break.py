#!/usr/bin/env python3
"""
train_break.py — train a 0-100 scorer that gives HIGH scores to break_data samples
(pure-up turns, label 1) and LOW scores to flat_data samples (sideways, label 0).

Target separation:  break_data -> score > 60 ,  flat_data -> score < 30.

Features = the BEFORE-window (20 days), no look-ahead:
    r0..r19   daily return %     (r19 = decision day D, r0 = D-19)
    vr0..vr19 volume / 20d-window average volume
    mcap_b    float market cap (B yuan)
    + 8 engineered: mom20, mom5, pct_from_high250, vol_ratio20,
      ma_aligned, above_ma20, range_contract, turnover_yi
    + 5 waking-up: consec_up, vol_expand, close_high_pct, gap_up, green_count5
computed from full stock history up to D via build_turn_dataset.build_one.
The forward leg (HOLD days after D) is never seen.

Holds out 20% (stratified). Trains HistGB + logistic, reports separation + AUC
at HIGH/LOW thresholds, and the logistic readout of strongest precursors.
Saves the better model.

Output: share_data/break_scorer.joblib   All data local.
"""
import os
import re
import sys
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd

from build_turn_dataset import build_one, load_mcap, HISTORY_DIR

from sklearn.model_selection import train_test_split
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
import joblib

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
BREAK_DIR = os.path.join(TOOL_DIR, "break_data")
FLAT_DIR = os.path.join(TOOL_DIR, "flat_data")
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")
MODEL_PATH = os.path.join(SHARE_DIR, "break_scorer.joblib")

BEFORE = 20
HOLD = 5
WIN_PCT = 10.0
DD_TOL = 5.0
HIGH, LOW = 60.0, 30.0
SEED = 42
FNAME_RE = re.compile(r"^(\d{6})_(\d{8})\.csv$")


def collect(minnet=None, years=None):
    """Build X, y from both folders. Features recomputed from full history (no look-ahead).
    If minnet is set, positives are filtered to up-leg net >= minnet% (read from the sample
    file: entry=open[row21], exit=close[row30]). If years is set, only decision dates in
    those years are kept (for train-on-2025 / test-on-2026 holdouts). Non-destructive."""
    mcap = load_mcap()
    want = defaultdict(dict)   # code -> {Timestamp: label}
    for d, lab in [(BREAK_DIR, 1), (FLAT_DIR, 0)]:
        for fn in os.listdir(d):
            m = FNAME_RE.match(fn)
            if not m:
                continue
            ts = pd.Timestamp(m.group(2))
            if years is not None and ts.year not in years:
                continue
            if lab == 1 and minnet is not None:
                try:
                    s = pd.read_csv(os.path.join(d, fn))
                    entry_idx = BEFORE  # first day after lookback
                    exit_idx = BEFORE + HOLD - 1  # HOLD trading days later (0-based)
                    entry, exit_ = s["Open"].iloc[entry_idx], s["Close"].iloc[exit_idx]
                    if (exit_ - entry) / entry * 100 < minnet:
                        continue
                except Exception:
                    continue
            want[m.group(1)][ts] = lab

    rows, feat_cols = [], None
    missing = 0
    for code, datemap in want.items():
        path = os.path.join(HISTORY_DIR, f"{code}.csv")
        if not os.path.exists(path):
            missing += len(datemap)
            continue
        df = pd.read_csv(path, parse_dates=["Date"])
        if df.empty or "Close" not in df.columns:
            missing += len(datemap)
            continue
        out, feat_cols = build_one(df, mcap.get(code, np.nan), BEFORE, HOLD, WIN_PCT, DD_TOL)
        out = out.set_index("Date")
        for dt, lab in datemap.items():
            if dt in out.index:
                r = out.loc[dt]
                rec = {c: float(r[c]) for c in feat_cols}
                rec["mcap_b"] = float(r["mcap_b"]) if pd.notna(r["mcap_b"]) else np.nan
                rec["label"] = lab
                rows.append(rec)
            else:
                missing += 1

    data = pd.DataFrame(rows)
    cols = feat_cols + ["mcap_b"]
    if missing:
        print(f"(note: {missing} samples skipped — date not in computable feature range)", file=sys.stderr)
    return data, cols


def report(name, y, score):
    pos = score[y == 1]
    neg = score[y == 0]
    pos_hi = (pos > HIGH).mean() * 100
    neg_lo = (neg < LOW).mean() * 100
    auc = roc_auc_score(y, score)
    obj = (pos_hi + neg_lo) / 2
    lines = [
        f"## {name}",
        f"  AUC ........................ {auc:.3f}",
        f"  break_data scoring > {HIGH:.0f} .... {pos_hi:5.1f}%   (target: high)",
        f"  flat_data  scoring < {LOW:.0f} .... {neg_lo:5.1f}%   (target: high)",
        f"  combined separation ........ {obj:5.1f}%",
        f"  score buckets   break / flat:",
        f"     >60   {(pos>60).sum():5d} / {(neg>60).sum():5d}",
        f"     30-60 {((pos>=30)&(pos<=60)).sum():5d} / {((neg>=30)&(neg<=60)).sum():5d}",
        f"     <30   {(pos<30).sum():5d} / {(neg<30).sum():5d}",
    ]
    return obj, auc, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Train the break scorer (20 feature days)")
    ap.add_argument("--minnet", type=float, default=None,
                    help="filter positives to up-leg net >= this %% (e.g. 20 to sharpen the bar)")
    ap.add_argument("--years", type=int, nargs="+", default=None,
                    help="keep only these decision-date years (e.g. --years 2025 for a holdout)")
    ap.add_argument("--out", default=MODEL_PATH, help="model output path (default break_scorer.joblib)")
    args = ap.parse_args()
    bar = f" net>=+{args.minnet:.0f}%" if args.minnet else ""
    yr = f" years={args.years}" if args.years else ""
    print(f"Collecting samples + features (first 20 days){bar}{yr}...", file=sys.stderr)
    data, cols = collect(args.minnet, set(args.years) if args.years else None)
    y = data["label"].values
    X = data[cols].copy()
    # impute mcap_b NaN with median (the only column that can be NaN)
    med = X["mcap_b"].median()
    X["mcap_b"] = X["mcap_b"].fillna(med)
    Xv = X.values

    print(f"samples: {len(y)}  (break={int(y.sum())}, flat={int((y==0).sum())}), features: {len(cols)}",
          file=sys.stderr)

    Xtr, Xte, ytr, yte = train_test_split(Xv, y, test_size=0.20, stratify=y, random_state=SEED)

    results = []

    # 1) gradient-boosted trees
    gb = HistGradientBoostingClassifier(random_state=SEED, max_iter=300, learning_rate=0.08,
                                        class_weight="balanced")
    gb.fit(Xtr, ytr)
    s_gb = gb.predict_proba(Xte)[:, 1] * 100
    obj_gb, auc_gb, txt_gb = report("Gradient-boosted trees (HistGB)", yte, s_gb)
    results.append((obj_gb, "gb", gb, txt_gb))

    # 2) logistic regression (standardized) — interpretable
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0,
                                                            class_weight="balanced"))
    lr.fit(Xtr, ytr)
    s_lr = lr.predict_proba(Xte)[:, 1] * 100
    obj_lr, auc_lr, txt_lr = report("Logistic regression (standardized)", yte, s_lr)
    results.append((obj_lr, "lr", lr, txt_lr))

    # logistic readout: strongest standardized coefficients
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
        waking = {
            "consec_up": "consecutive green days ending at D",
            "vol_expand": "vol[D] > vol[D-1] > vol[D-2]",
            "close_high_pct": "(close-low)/(high-low)*100",
            "gap_up": "open[D] gap vs close[D-1] (%)",
            "green_count5": "up days in last 5",
        }
        if name in engineered:
            return engineered[name]
        if name in waking:
            return waking[name]
        if name == "mcap_b":
            return "market cap (B yuan)"
        if name.startswith("vr"):
            k = int(name[2:]); return f"volume ratio, day D-{19-k}"
        k = int(name[1:]); return f"daily return, day D-{19-k}"

    lines = []
    lines.append("=" * 60)
    lines.append("BREAK SCORER — separate break_data (turns) from flat_data (noise)")
    lines.append(f"trained on {len(ytr)} samples, tested on {len(yte)} (held out, stratified)")
    lines.append(f"target: break_data > {HIGH:.0f},  flat_data < {LOW:.0f}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(txt_gb)
    lines.append("")
    lines.append(txt_lr)
    lines.append("")
    lines.append("## Logistic readout — strongest precursors (standardized)")
    lines.append("   (+ pushes score toward 'turn', - toward 'flat')")
    for i in order:
        lines.append(f"   {coef[i]:+.3f}  {cols[i]:<7}  {explain(cols[i])}")
    report_txt = "\n".join(lines)

    # save the better model by combined separation
    results.sort(key=lambda r: r[0], reverse=True)
    best_obj, best_name, best_model, _ = results[0]
    os.makedirs(SHARE_DIR, exist_ok=True)
    joblib.dump({"model": best_model, "kind": best_name, "feat_cols": cols,
                 "mcap_median": float(med), "high": HIGH, "low": LOW}, args.out)

    print("\n" + report_txt)
    print(f"\nBest model: {best_name} (separation {best_obj:.1f}%) -> saved {args.out}")
    with open(os.path.join(SHARE_DIR, "break_scorer_report.txt"), "w", encoding="utf-8") as f:
        f.write(report_txt + f"\n\nBest: {best_name} ({best_obj:.1f}%)\n")


if __name__ == "__main__":
    main()
