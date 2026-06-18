#!/usr/bin/env python3
"""
predict_flat_erupt.py — live scanner for flat-then-erupt candidates.

Strategy:
  1. FLATNESS GATE: only score stocks that are currently quiet and coiling
     (mom20 in [-5,15]%, range_contract < 0.85, >=16/20 quiet days)
  2. ML SCORE: apply flat_erupt_scorer.joblib to rank gated stocks
  3. OUTPUT: top N candidates with metrics — high precision, low volume

This deliberately misses many eventual eruptions in exchange for near-zero
downside on wrong picks: stocks that don't erupt from flatness tend to stay flat,
not crater.

Usage:
    python predict_flat_erupt.py                        # latest trading day
    python predict_flat_erupt.py --date 2026-06-18
    python predict_flat_erupt.py --min-score 70 --top 5  # precision mode
    python predict_flat_erupt.py -q                      # save file only

Output: share_data/flat_erupt_<date>.txt
"""
import os
import sys
import csv
import argparse

import numpy as np
import pandas as pd
import joblib

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(TOOL_DIR, "stock_history_ak")
META_PATH = os.path.join(TOOL_DIR, "share_data", "stock_meta.csv")
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")
MODEL_PATH = os.path.join(SHARE_DIR, "flat_erupt_scorer.joblib")
CAL_FILE = os.path.join(HISTORY_DIR, "000001.csv")

BEFORE = 20

# Flatness gate (must match build_flat_dataset.py)
LOW_MOM_MAX = 15.0
RANGE_TIGHT = 0.85
FLAT_DAYS_MIN = 16


def load_meta():
    """code -> (name, industry, float_mcap_yuan)."""
    out = {}
    if not os.path.exists(META_PATH):
        return out
    with open(META_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row.get("code", "").strip()
            try:
                mc = float(row.get("float_mcap_now", "0") or "0")
            except ValueError:
                mc = np.nan
            out[code] = (row.get("name", "").strip(), row.get("industry", "").strip(), mc)
    return out


def flatness_gate(df_sorted, i):
    """Check if day i passes the flatness (quiet coiling) gate."""
    c = df_sorted["Close"]
    h = df_sorted["High"]
    l = df_sorted["Low"]
    v = df_sorted["Volume"]

    if i < 269:  # need 250d high + margins
        return False

    # Momentum in range [-5%, +15%]
    mom20 = float((c.iloc[i] / c.iloc[i - 20] - 1) * 100)
    if mom20 < -5.0 or mom20 > LOW_MOM_MAX:
        return False

    # Range tightening
    rng = h - l
    rng5 = rng.iloc[i - 4:i + 1].mean()
    rng20 = rng.iloc[i - 19:i + 1].mean()
    if rng20 <= 0:
        return False
    range_contract = float(rng5 / rng20)
    if range_contract >= RANGE_TIGHT:
        return False

    # Quiet: most days have small returns
    ret = (c / c.shift(1) - 1) * 100
    quiet_count = (ret.iloc[i - 19:i + 1].abs() < 3).sum()
    if quiet_count < FLAT_DAYS_MIN:
        return False

    return True


def features_at(df_sorted, mcap, i, feat_cols):
    """Compute feature vector at day i, same formulas as build_one + engineered.
    Returns (feature_array, close, day_ret) or None."""
    c = df_sorted["Close"]
    h = df_sorted["High"]
    l = df_sorted["Low"]
    v = df_sorted["Volume"]

    ret = (c / c.shift(1) - 1) * 100
    vavg = v.iloc[i - (BEFORE - 1):i + 1].mean()
    if not np.isfinite(vavg) or vavg == 0:
        return None

    feat = {}
    for k in range(BEFORE):
        j = i - (BEFORE - 1 - k)
        feat[f"r{k}"] = float(ret.iloc[j])
        feat[f"vr{k}"] = float(v.iloc[j] / vavg)
    feat["mcap_b"] = (mcap / 1e9) if (mcap and np.isfinite(mcap)) else np.nan

    # Engineered features
    feat["mom20"] = float((c.iloc[i] / c.iloc[i - 20] - 1) * 100)
    feat["mom5"] = float((c.iloc[i] / c.iloc[i - 5] - 1) * 100)
    high250 = h.iloc[i - 249:i + 1].max()
    feat["pct_from_high250"] = float((c.iloc[i] - high250) / high250 * 100)
    vol20_prior = v.iloc[i - 20:i].mean()
    feat["vol_ratio20"] = float(v.iloc[i] / vol20_prior) if vol20_prior > 0 else np.nan
    ma5 = c.iloc[i - 4:i + 1].mean()
    ma10 = c.iloc[i - 9:i + 1].mean()
    ma20 = c.iloc[i - 19:i + 1].mean()
    feat["ma_aligned"] = int(ma5 > ma10 > ma20)
    feat["above_ma20"] = int(c.iloc[i] > ma20)
    rng = h - l
    rng5 = rng.iloc[i - 4:i + 1].mean()
    rng20 = rng.iloc[i - 19:i + 1].mean()
    feat["range_contract"] = float(rng5 / rng20) if rng20 > 0 else np.nan
    feat["turnover_yi"] = float(v.iloc[i] * c.iloc[i] / 1e8)

    row = []
    for name in feat_cols:
        val = feat.get(name, np.nan)
        if name != "mcap_b" and not np.isfinite(val):
            return None
        row.append(val)
    return np.array(row, dtype=float), float(c.iloc[i]), float(ret.iloc[i])


def main():
    ap = argparse.ArgumentParser(description="Scan for flat-then-erupt candidates")
    ap.add_argument("--date", help="trading day YYYY-MM-DD (default: latest)")
    ap.add_argument("--min-score", type=float, default=60.0, help="score threshold (default 60)")
    ap.add_argument("--top", type=int, default=10, help="max candidates (default 10)")
    ap.add_argument("-q", "--quiet", action="store_true", help="save file only, no stdout")
    args = ap.parse_args()

    if not os.path.exists(MODEL_PATH):
        sys.exit(f"no model at {MODEL_PATH} — run train_flat_erupt.py first")

    bundle = joblib.load(MODEL_PATH)
    model, feat_cols = bundle["model"], bundle["feat_cols"]
    mcap_med = bundle.get("mcap_median", np.nan)

    cal = pd.read_csv(CAL_FILE, parse_dates=["Date"])
    target = pd.Timestamp(args.date) if args.date else cal["Date"].max()

    meta = load_meta()
    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".csv"))

    print(f"Flat-erupt scan for {target.date()}  "
          f"(model: {bundle.get('kind','?')}, score>={args.min_score:.0f})",
          file=sys.stderr)

    gated = 0
    scored = 0
    recs = []

    for fn in files:
        code = fn[:-4]
        name, industry, mc = meta.get(code, ("", "", np.nan))
        try:
            df = pd.read_csv(os.path.join(HISTORY_DIR, fn), parse_dates=["Date"])
        except Exception:
            continue
        if df.empty or "Close" not in df.columns or len(df) < 270:
            continue

        df = df.sort_values("Date").reset_index(drop=True)
        idx = df.index[df["Date"] == target]
        if len(idx) == 0:
            continue
        i = int(idx[0])

        # STEP 1: flatness gate
        if not flatness_gate(df, i):
            continue
        gated += 1

        # STEP 2: compute features + score
        res = features_at(df, mc, i, feat_cols)
        if res is None:
            continue
        x, close, day_ret = res

        if not np.isfinite(x).all():
            continue
        if "mcap_b" in feat_cols:
            idx_mcap = feat_cols.index("mcap_b")
            if not np.isfinite(x[idx_mcap]):
                x[idx_mcap] = mcap_med

        score = float(model.predict_proba(x.reshape(1, -1))[0, 1] * 100)
        scored += 1

        if score >= args.min_score:
            recs.append((score, code, name, industry, close, day_ret,
                         (mc / 1e9) if np.isfinite(mc) else np.nan))

    recs.sort(key=lambda r: r[0], reverse=True)
    hits = recs[:args.top]

    lines = []
    lines.append(f"flat_erupt — {target.date()}  (model: {bundle.get('kind','?')}, "
                 f"score>={args.min_score:.0f})")
    lines.append(f"stocks gated (flat): {gated}  scored: {scored}  "
                 f"above threshold: {len(recs)}  showing top {len(hits)}")
    lines.append("=" * 78)
    if hits:
        lines.append(f"{'#':>3} {'score':>6} {'code':<7} {'name':<10} "
                     f"{'close':>8} {'day%':>7} {'mcapB':>7}  industry")
        lines.append("-" * 78)
        for rank, (sc, code, name, industry, close, day_ret, mcb) in enumerate(hits, 1):
            mcs = f"{mcb:6.1f}" if np.isfinite(mcb) else "   n/a"
            lines.append(f"{rank:>3} {sc:6.1f} {code:<7} {name[:10]:<10} "
                         f"{close:8.2f} {day_ret:7.1f} {mcs}  {industry[:18]}")
    else:
        lines.append("(no candidates cleared the threshold)")

    report = "\n".join(lines)

    os.makedirs(SHARE_DIR, exist_ok=True)
    out_path = os.path.join(SHARE_DIR, f"flat_erupt_{target.date()}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    if not args.quiet:
        print(report)
    print(f"\nsaved -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
