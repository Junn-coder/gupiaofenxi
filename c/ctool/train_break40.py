#!/usr/bin/env python3
"""
train_break40.py — "more history, same target" test vs the 30-day model (AUC 0.80).

Identical task to train_break.py (10-day +15% up-leg vs forward-10d flat negatives), the
ONLY change is the feature window: 30 days instead of 20. So any AUC difference is the
effect of 10 extra days of history.

Positives: break_data_40 (30 feature days + 10-day +15% loose up-leg), label 1.
Negatives (generated): forward 10-day net within +/-5% (stayed flat), 2025+2026, no
constraint on the feature window, sampled with a fixed seed, label 0.

Features = first 30 days only: r0..r29, vr0..vr29, mcap_b (from full history at D, no look-ahead).
Output: share_data/break_scorer40.joblib + break_scorer40_report.txt
"""
import os
import re
import sys
import random
from collections import defaultdict

import numpy as np
import pandas as pd

from build_turn_dataset import build_one, load_mcap, HISTORY_DIR
from train_break import report, HIGH, LOW

from sklearn.model_selection import train_test_split
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
import joblib

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
BREAK_DIR = os.path.join(TOOL_DIR, "break_data_40")
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")
MODEL_PATH = os.path.join(SHARE_DIR, "break_scorer40.joblib")

BASE = 30          # feature window
UP = 10            # up-leg (same target as the 30-day model)
NEG_FLAT = 5.0     # negative forward 10d |net| <= (stayed flat) — matches 30-day flat_data
N_NEG = 5000
SEED = 42
YEARS = {2025, 2026}
FNAME_RE = re.compile(r"^(\d{6})_(\d{8})\.csv$")


def positive_dates():
    out = defaultdict(set)
    for fn in os.listdir(BREAK_DIR):
        m = FNAME_RE.match(fn)
        if m:
            out[m.group(1)].add(pd.Timestamp(m.group(2)))
    return out


def scan_negatives(code, df):
    """forward 10d stayed flat (|net|<=NEG_FLAT), no feature-window constraint."""
    df = df.sort_values("Date").reset_index(drop=True)
    c, o = df["Close"], df["Open"]
    entry = o.shift(-1)
    exit_ = c.shift(-UP)
    fwd_net = (exit_ - entry) / entry * 100
    yr = df["Date"].dt.year
    ok = (fwd_net.abs() <= NEG_FLAT) & yr.isin(YEARS) & entry.notna() & exit_.notna()
    idx = [i for i in np.flatnonzero(ok.values) if i >= BASE - 1 and i + UP < len(df)]
    s = set(idx)
    kept = [i for i in idx if (i - 1) not in s]
    return [df.iloc[i]["Date"] for i in kept]


def collect():
    mcap = load_mcap()
    pos = positive_dates()
    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".csv"))

    neg_cand = []
    for fn in files:
        code = fn[:-4]
        try:
            df = pd.read_csv(os.path.join(HISTORY_DIR, fn), parse_dates=["Date"])
        except Exception:
            continue
        if df.empty or "Close" not in df.columns or len(df) < BASE + UP + 1:
            continue
        for dt in scan_negatives(code, df):
            neg_cand.append((code, dt))
    random.seed(SEED)
    random.shuffle(neg_cand)
    neg_cand = neg_cand[:N_NEG]
    print(f"negative candidates pooled, using {len(neg_cand)}", file=sys.stderr)

    want = defaultdict(dict)
    for code, dates in pos.items():
        for dt in dates:
            want[code][dt] = 1
    for code, dt in neg_cand:
        want[code].setdefault(dt, 0)

    rows, feat_cols = [], None
    missing = 0
    for code, datemap in want.items():
        path = os.path.join(HISTORY_DIR, f"{code}.csv")
        if not os.path.exists(path):
            missing += len(datemap); continue
        df = pd.read_csv(path, parse_dates=["Date"])
        if df.empty or "Close" not in df.columns:
            missing += len(datemap); continue
        out, feat_cols = build_one(df, mcap.get(code, np.nan), BASE, UP, 15.0, 5.0)
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
    if missing:
        print(f"(note: {missing} samples skipped — date not in computable feature range)", file=sys.stderr)
    return pd.DataFrame(rows), feat_cols + ["mcap_b"]


def main():
    print("Collecting 40-day samples + features (first 30 days)...", file=sys.stderr)
    data, cols = collect()
    y = data["label"].values
    X = data[cols].copy()
    med = X["mcap_b"].median()
    X["mcap_b"] = X["mcap_b"].fillna(med)
    Xv = X.values
    print(f"samples: {len(y)}  (break={int(y.sum())}, flat={int((y==0).sum())}), features: {len(cols)}",
          file=sys.stderr)

    Xtr, Xte, ytr, yte = train_test_split(Xv, y, test_size=0.20, stratify=y, random_state=SEED)

    gb = HistGradientBoostingClassifier(random_state=SEED, max_iter=300, learning_rate=0.08,
                                        class_weight="balanced")
    gb.fit(Xtr, ytr)
    s_gb = gb.predict_proba(Xte)[:, 1] * 100
    obj_gb, auc_gb, txt_gb = report("Gradient-boosted trees (HistGB)", yte, s_gb)

    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0,
                                                            class_weight="balanced"))
    lr.fit(Xtr, ytr)
    s_lr = lr.predict_proba(Xte)[:, 1] * 100
    obj_lr, auc_lr, txt_lr = report("Logistic regression (standardized)", yte, s_lr)

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
            k = int(name[2:]); return f"volume ratio, day D-{BASE-1-k}"
        k = int(name[1:]); return f"daily return, day D-{BASE-1-k}"

    lines = ["=" * 60,
             "BREAK-40 SCORER — 10-day +15% up-leg, 30 feature days (vs 30-day model's 20)",
             f"trained {len(ytr)}, tested {len(yte)} (held out); features {len(cols)} (first {BASE}d)",
             f"target: break>{HIGH:.0f}, flat<{LOW:.0f}", "=" * 60, "",
             txt_gb, "", txt_lr, "",
             "## Logistic readout — strongest precursors (standardized)",
             "   (+ pushes toward 'up-leg', - toward 'flat')"]
    for i in order:
        lines.append(f"   {coef[i]:+.3f}  {cols[i]:<7}  {explain(cols[i])}")
    report_txt = "\n".join(lines)

    best = ("gb", gb, obj_gb) if obj_gb >= obj_lr else ("lr", lr, obj_lr)
    os.makedirs(SHARE_DIR, exist_ok=True)
    joblib.dump({"model": best[1], "kind": best[0], "feat_cols": cols,
                 "mcap_median": float(med), "high": HIGH, "low": LOW,
                 "base": BASE, "up": UP}, MODEL_PATH)
    print("\n" + report_txt)
    print(f"\nBest model: {best[0]} (separation {best[2]:.1f}%) -> saved {MODEL_PATH}")
    with open(os.path.join(SHARE_DIR, "break_scorer40_report.txt"), "w", encoding="utf-8") as f:
        f.write(report_txt + f"\n\nBest: {best[0]} ({best[2]:.1f}%)\n")


if __name__ == "__main__":
    main()
