#!/usr/bin/env python3
"""
predict_backtest.py — STEP 5: does the trained scorer's top picks actually make money?

For every trading day in a range it scores all stocks with break_scorer.joblib, takes the
TOP-N by score (what you'd actually buy), and grades each by its 10-day forward return
(entry = next-day open, exit = day-10 close — same definition as everywhere else). Then it
reports hit-rate / avg / median / best-worst, plus the picks' average decision-day return
(to confirm whether it's a "buy the dip" picker) and the market baseline over the same days.

Efficient: reads each stock once, scores all its in-range days in a single batch.

NOTE: if the range overlaps the model's training dates (2025-2026), results are IN-SAMPLE
and optimistic. For an honest read, train on an earlier slice and backtest a later one.

Usage:
    python predict_backtest.py --range 20260401 20260519 --top 10 --win 20
Output: share_data/predict_backtest_<start>_<end>.txt
"""
import os
import sys
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd
import joblib

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(TOOL_DIR, "stock_history_ak")
META_PATH = os.path.join(TOOL_DIR, "share_data", "stock_meta.csv")
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")
MODEL_PATH = os.path.join(SHARE_DIR, "break_scorer.joblib")

BEFORE = 20
HOLD = 5


def parse_day(s):
    s = s.replace("-", "")
    return pd.Timestamp(f"{s[:4]}-{s[4:6]}-{s[6:8]}")


def load_mcap():
    out = {}
    if not os.path.exists(META_PATH):
        return out
    import csv
    with open(META_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row.get("code", "").strip()] = float(row.get("float_mcap_now", "0") or "0")
            except ValueError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser(description="Backtest the trained scorer's top picks")
    ap.add_argument("--range", nargs=2, metavar=("START", "END"), required=True)
    ap.add_argument("--top", type=int, default=10, help="picks per day (default 10)")
    ap.add_argument("--win", type=float, default=20.0, help="hit threshold %% (default 20)")
    ap.add_argument("--model", default=MODEL_PATH, help="model path (default break_scorer.joblib)")
    args = ap.parse_args()

    d0, d1 = parse_day(args.range[0]), parse_day(args.range[1])
    bundle = joblib.load(args.model)
    model, feat_cols = bundle["model"], bundle["feat_cols"]
    mcap_med = bundle.get("mcap_median", np.nan)
    mcap = load_mcap()
    mcap_i = feat_cols.index("mcap_b")

    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".csv"))
    # per (date) -> list of (score, code, fwd, day_ret)
    per_day = defaultdict(list)
    all_fwd = []  # market baseline: every scored stock-day's forward return

    for n, fn in enumerate(files, 1):
        if n % 200 == 0:
            print(f"  ... {n}/{len(files)} stocks", file=sys.stderr)
        code = fn[:-4]
        try:
            df = pd.read_csv(os.path.join(HISTORY_DIR, fn), parse_dates=["Date"])
        except Exception:
            continue
        if df.empty or "Close" not in df.columns or len(df) < BEFORE + HOLD + 2:
            continue
        df = df.sort_values("Date").reset_index(drop=True)
        dates = df["Date"].values
        o = df["Open"].to_numpy(float)
        c = df["Close"].to_numpy(float)
        h = df["High"].to_numpy(float)
        l = df["Low"].to_numpy(float)
        v = df["Volume"].to_numpy(float)
        ret = np.empty(len(c)); ret[0] = np.nan
        ret[1:] = (c[1:] / c[:-1] - 1) * 100
        volavg = pd.Series(v).rolling(BEFORE).mean().to_numpy()

        in_range = (df["Date"] >= d0) & (df["Date"] <= d1)
        cand = [i for i in np.flatnonzero(in_range.values)
                if i >= BEFORE and i + HOLD < len(df)]
        if not cand:
            continue
        vi = np.array(cand)

        # build feature matrix in feat_cols order
        cols = {}
        for k in range(BEFORE):
            off = BEFORE - 1 - k
            cols[f"r{k}"] = ret[vi - off]
            with np.errstate(divide="ignore", invalid="ignore"):
                cols[f"vr{k}"] = v[vi - off] / volavg[vi]

        # engineered features (same formulas as build_one, no look-ahead)
        cols["mom20"] = (c[vi] / c[vi - 20] - 1) * 100
        cols["mom5"] = (c[vi] / c[vi - 5] - 1) * 100
        high250 = pd.Series(h).rolling(250).max().to_numpy()
        cols["pct_from_high250"] = (c[vi] - high250[vi]) / high250[vi] * 100
        vol20p = pd.Series(v).shift(1).rolling(20).mean().to_numpy()
        cols["vol_ratio20"] = v[vi] / vol20p[vi]
        ma5 = pd.Series(c).rolling(5).mean().to_numpy()
        ma10 = pd.Series(c).rolling(10).mean().to_numpy()
        ma20 = pd.Series(c).rolling(20).mean().to_numpy()
        cols["ma_aligned"] = ((ma5[vi] > ma10[vi]) & (ma10[vi] > ma20[vi])).astype("int8")
        cols["above_ma20"] = (c[vi] > ma20[vi]).astype("int8")
        rng = pd.Series(h - l)
        rng5 = rng.rolling(5).mean().to_numpy()
        rng20 = rng.rolling(20).mean().to_numpy()
        cols["range_contract"] = rng5[vi] / rng20[vi]
        cols["turnover_yi"] = v[vi] * c[vi] / 1e8

        # waking-up features (ignition detection)
        # consec_up: count consecutive green days ending at each vi
        up_arr = (ret > 0).astype(int)
        consec = np.zeros(len(vi), dtype=float)
        for j, idx in enumerate(vi):
            cnt = 0
            for k in range(idx, max(idx - 20, 0), -1):
                if up_arr[k]:
                    cnt += 1
                else:
                    break
            consec[j] = cnt
        cols["consec_up"] = consec
        cols["vol_expand"] = ((v[vi] > v[vi - 1]) & (v[vi - 1] > v[vi - 2])).astype("int8")
        denom = h[vi] - l[vi]
        cols["close_high_pct"] = np.where(denom > 0, (c[vi] - l[vi]) / denom * 100, 50.0)  # 50=mid if no range
        cols["gap_up"] = (o[vi] - c[vi - 1]) / c[vi - 1] * 100
        cols["green_count5"] = ((ret[vi - 4] > 0).astype(int) + (ret[vi - 3] > 0).astype(int) +
                                (ret[vi - 2] > 0).astype(int) + (ret[vi - 1] > 0).astype(int) +
                                (ret[vi] > 0).astype(int))

        mb = (mcap.get(code, np.nan) / 1e9) if np.isfinite(mcap.get(code, np.nan)) else mcap_med
        X = np.empty((len(vi), len(feat_cols)))
        for ci, name in enumerate(feat_cols):
            X[:, ci] = mb if name == "mcap_b" else cols[name]
        good = np.isfinite(X[:, [j for j in range(len(feat_cols)) if j != mcap_i]]).all(axis=1)
        if not good.any():
            continue
        vi, X = vi[good], X[good]
        X[~np.isfinite(X[:, mcap_i]), mcap_i] = mcap_med

        scores = model.predict_proba(X)[:, 1] * 100
        fwd = (c[vi + HOLD] - o[vi + 1]) / o[vi + 1] * 100
        dret = ret[vi]
        for s, f, dr, i in zip(scores, fwd, dret, vi):
            per_day[dates[i]].append((float(s), code, float(f), float(dr)))
            all_fwd.append(float(f))

    if not per_day:
        sys.exit("no gradeable stock-days in range")

    picks = []
    for day, lst in per_day.items():
        lst.sort(key=lambda r: r[0], reverse=True)
        picks.extend(lst[: args.top])

    fwd = np.array([p[2] for p in picks])
    dret = np.array([p[3] for p in picks])
    base = np.array(all_fwd)
    hit = (fwd >= args.win).mean() * 100

    lines = []
    lines.append(f"predict_backtest  {d0.date()} -> {d1.date()}   top {args.top}/day")
    lines.append(f"model: {bundle.get('kind','?')}   hit = forward >= +{args.win:.0f}% ({HOLD}-day)")
    lines.append("=" * 64)
    lines.append(f"pick-days .............. {len(per_day)}")
    lines.append(f"picks graded ........... {len(picks)}")
    lines.append(f"hit rate (>= +{args.win:.0f}%) ..... {hit:.1f}%")
    lines.append(f"avg forward return ..... {fwd.mean():+.2f}%   median {np.median(fwd):+.2f}%")
    lines.append(f"  vs MARKET baseline ... {base.mean():+.2f}%   median {np.median(base):+.2f}%   (all scored stock-days)")
    lines.append(f"picks' avg decision-day return .. {dret.mean():+.2f}%   <- negative = it's buying dips")
    lines.append("")
    srt = sorted(picks, key=lambda p: p[2], reverse=True)
    lines.append("Best 5:")
    for s, code, f, dr in srt[:5]:
        lines.append(f"   {f:+7.1f}%  {code}  (score {s:.0f}, day {dr:+.1f}%)")
    lines.append("Worst 5:")
    for s, code, f, dr in srt[-5:]:
        lines.append(f"   {f:+7.1f}%  {code}  (score {s:.0f}, day {dr:+.1f}%)")
    report = "\n".join(lines)

    os.makedirs(SHARE_DIR, exist_ok=True)
    out = os.path.join(SHARE_DIR, f"predict_backtest_{d0.date()}_{d1.date()}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print("\n" + report)
    print(f"\nsaved -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
