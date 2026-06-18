#!/usr/bin/env python3
"""
train_break60.py — 60-day sibling of train_break.py, so the AUC is directly comparable.

Task: score the 60-day "flat base -> steady +15% climb" episodes (break_data_60, label 1)
against flat bases that STAYED flat (negatives generated here, label 0). Both classes share
the 30-day flat base, so the model must learn what WITHIN a flat base predicts the breakout
(it can't cheat on "is the base flat").

Features = the 30-day flat base ONLY (no look-ahead):
    r0..r29   daily return %     (r29 = decision day D)
    vr0..vr29 volume / 30-day-window average volume
    mcap_b    float market cap (B yuan)
recomputed from full history at D, where (code, D) for positives come from the
break_data_60 filenames and negatives are scanned from history.

Negatives: flat base |net30|<=4%, decision day in 2025+2026, and forward 30-day net within
+/-8% (stayed flat). Non-overlapping, sampled to N with a fixed seed.

Output: share_data/break_scorer60.joblib + break_scorer60_report.txt   All data local.
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
BREAK_DIR = os.path.join(TOOL_DIR, "break_data_60")
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")
MODEL_PATH = os.path.join(SHARE_DIR, "break_scorer60.joblib")

BASE = 30          # flat base = before-window
UP = 30            # up-leg
FLAT_BAND = 4.0    # base |net| <=
NEG_FLAT = 8.0     # negative forward |net| <= (stayed flat)
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
    """flat base that STAYED flat over the next 30 days -> negative decision dates."""
    df = df.sort_values("Date").reset_index(drop=True)
    c, o = df["Close"], df["Open"]
    base0 = c.shift(BASE - 1)
    base_net = (c - base0) / base0 * 100
    entry = o.shift(-1)
    exit_ = c.shift(-UP)
    fwd_net = (exit_ - entry) / entry * 100
    yr = df["Date"].dt.year
    ok = (base_net.abs() <= FLAT_BAND) & (fwd_net.abs() <= NEG_FLAT) & yr.isin(YEARS) \
        & entry.notna() & exit_.notna()
    idx = [i for i in np.flatnonzero(ok.values) if i >= BASE - 1 and i + UP < len(df)]
    s = set(idx)
    kept = [i for i in idx if (i - 1) not in s]      # collapse consecutive
    return [df.iloc[i]["Date"] for i in kept]


def collect():
    mcap = load_mcap()
    pos = positive_dates()
    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".csv"))

    # gather negative candidates across all stocks, then sample
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

    want = defaultdict(dict)   # code -> {date: label}
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
    print("Collecting 60-day samples + features (first 30 days)...", file=sys.stderr)
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
             "BREAK-60 SCORER — flat base -> +15% steady climb vs flat-stayed",
             f"trained {len(ytr)}, tested {len(yte)} (held out, stratified); features {len(cols)} (first {BASE}d)",
             f"target: break>{HIGH:.0f}, flat<{LOW:.0f}", "=" * 60, "",
             txt_gb, "", txt_lr, "",
             "## Logistic readout — strongest precursors (standardized)",
             "   (+ pushes toward 'climb', - toward 'stay flat')"]
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
    with open(os.path.join(SHARE_DIR, "break_scorer60_report.txt"), "w", encoding="utf-8") as f:
        f.write(report_txt + f"\n\nBest: {best[0]} ({best[2]:.1f}%)\n")


if __name__ == "__main__":
    main()
