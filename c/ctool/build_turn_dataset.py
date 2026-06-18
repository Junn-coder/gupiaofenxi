#!/usr/bin/env python3
"""
build_turn_dataset.py — prepare the training dataset for the "pure-up turn" hunt.

Each example is one stock-day D = the PICK point = end of a `before`-day window
(period - HOLD; period default 25, HOLD default 5, so before = 20). Everything is
computed with data up to and including day D — no look-ahead.

  Features (all the picker may see at decision time):
    r0..r{B-1}   daily return % over the before-window  (r{B-1} = day D, the newest)
    vr0..vr{B-1} that day's volume / the before-window average volume (stock-agnostic)
    mcap_b       float market cap (B yuan), carried so pre_break can report cap band
    Engineered (winner_study-proven, no look-ahead):
      mom20, mom5          — momentum over 20d and 5d
      pct_from_high250     — distance from 52-week high
      vol_ratio20          — volume / prior 20d average (aggregate)
      ma_aligned           — MA 5>10>20 aligned (0/1)
      above_ma20           — close above 20d MA (0/1)
      range_contract       — recent 5d range / 20d range
      turnover_yi          — daily turnover (100M yuan)
    Waking-up (ignition detection, no look-ahead):
      consec_up            — consecutive green days ending at D
      vol_expand           — vol[D] > vol[D-1] > vol[D-2] (volume expansion)
      close_high_pct       — (close-low)/(high-low)*100 (closing strength)
      gap_up               — open[D] gap vs close[D-1] (%)
      green_count5         — number of up days in last 5

  Label = "loose pure-up" over the next HOLD trading days:
    entry = open[D+1], exit = close[D+HOLD]
    net   = (exit - entry) / entry * 100 >= WIN_PCT
    AND the path never closes more than DD_TOL% below entry (a real ride, not a spike)

  fwd_net is kept for inspection ("what 'up' looks like").

Output: share_data/turn_dataset.parquet (or .csv.gz fallback). All data local.

Usage:
    python build_turn_dataset.py                 # before=20d, hold=5d, +10% win
    python build_turn_dataset.py --hold 10       # classic 10d hold
    python build_turn_dataset.py --win 7 --dd 3
"""
import os
import sys
import csv
import argparse

import numpy as np
import pandas as pd

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(TOOL_DIR, "stock_history_ak")
META_PATH = os.path.join(TOOL_DIR, "share_data", "stock_meta.csv")
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")

HOLD = 5  # the up-leg (short: clearer signal, faster feedback)


def load_mcap() -> dict:
    out = {}
    if not os.path.exists(META_PATH):
        return out
    with open(META_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row.get("code", "").strip()] = float(row.get("float_mcap_now", "0") or "0")
            except ValueError:
                pass
    return out


def build_one(df: pd.DataFrame, mcap, before: int, hold: int, win_pct: float, dd_tol: float):
    df = df.sort_values("Date").reset_index(drop=True)
    o, c, h, l, v = df["Open"], df["Close"], df["High"], df["Low"], df["Volume"]

    ret = (c / c.shift(1) - 1) * 100
    volavg = v.rolling(before).mean()

    # forward label (no look-ahead: uses only days strictly after D)
    entry = o.shift(-1)
    exit_ = c.shift(-hold)
    fut_min = pd.concat([c.shift(-i) for i in range(1, hold + 1)], axis=1).min(axis=1)
    net = (exit_ - entry) / entry * 100
    dd_ok = fut_min >= entry * (1 - dd_tol / 100.0)
    label = ((net >= win_pct) & dd_ok).astype("int8")

    data = {
        "Date": df["Date"],
        "fwd_net": net,
        "label": label,
        "mcap_b": (mcap / 1e9 if mcap else np.nan),
    }
    feat_cols = []

    # ── raw daily features (r0..r{before-1}, vr0..vr{before-1}) ──
    for k in range(before):                 # r0 = oldest, r{before-1} = day D
        data[f"r{k}"] = ret.shift(before - 1 - k)
        data[f"vr{k}"] = v.shift(before - 1 - k) / volavg
        feat_cols += [f"r{k}", f"vr{k}"]

    # ── engineered features (winner_study-proven, no look-ahead) ──
    # Momentum
    mom20 = (c / c.shift(20) - 1) * 100
    mom5 = (c / c.shift(5) - 1) * 100
    data["mom20"] = mom20
    data["mom5"] = mom5

    # Proximity to 250-day high
    high250 = h.rolling(250).max()
    data["pct_from_high250"] = (c - high250) / high250 * 100

    # Aggregate volume ratio (today vs prior 20d avg)
    vol20_prior = v.shift(1).rolling(20).mean()
    data["vol_ratio20"] = v / vol20_prior

    # MA alignment (5>10>20 + above 20MA)
    ma5 = c.rolling(5).mean()
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    data["ma_aligned"] = ((ma5 > ma10) & (ma10 > ma20)).astype("int8")
    data["above_ma20"] = (c > ma20).astype("int8")

    # Range contraction (recent 5d range / 20d range)
    rng = h - l
    rng5 = rng.rolling(5).mean()
    rng20 = rng.rolling(20).mean()
    data["range_contract"] = rng5 / rng20

    # Liquidity (daily turnover in 100M yuan)
    data["turnover_yi"] = v * c / 1e8

    eng_feats = ["mom20", "mom5", "pct_from_high250", "vol_ratio20",
                 "ma_aligned", "above_ma20", "range_contract", "turnover_yi"]
    feat_cols += eng_feats

    # ── waking-up features (is the stock stirring right now?) ──
    # Consecutive green days ending at D
    up = (ret > 0).astype(int)
    consec_up = up.copy()
    for k in range(1, len(up)):
        if up.iloc[k]:
            consec_up.iloc[k] = consec_up.iloc[k - 1] + 1
        else:
            consec_up.iloc[k] = 0
    data["consec_up"] = consec_up

    # Volume expansion: vol[D] > vol[D-1] > vol[D-2]
    data["vol_expand"] = ((v > v.shift(1)) & (v.shift(1) > v.shift(2))).astype("int8")

    # Where in day's range did it close? (close - low) / (high - low)
    data["close_high_pct"] = (c - l) / (h - l) * 100  # 0-100, higher = bullish

    # Gap up from yesterday's close (open vs prior close)
    data["gap_up"] = (o - c.shift(1)) / c.shift(1) * 100

    # Green days in the last 5 (waking-up density)
    data["green_count5"] = up.rolling(5).sum()

    wake_feats = ["consec_up", "vol_expand", "close_high_pct", "gap_up", "green_count5"]
    feat_cols += wake_feats

    out = pd.DataFrame(data).replace([np.inf, -np.inf], np.nan)
    # need full feature window + a real forward label; mcap_b may stay NaN (it's a feature)
    out = out[entry.notna().values & exit_.notna().values]
    out = out.dropna(subset=feat_cols)
    return out, feat_cols


def main():
    ap = argparse.ArgumentParser(description="Prepare the pure-up turn training dataset")
    ap.add_argument("--period", type=int, default=25, help="window length; before = period - HOLD (default 25)")
    ap.add_argument("--hold", type=int, default=HOLD, help=f"forward hold days (default {HOLD})")
    ap.add_argument("--win", type=float, default=10.0, help="pure-up bar %% over hold days (default 10)")
    ap.add_argument("--dd", type=float, default=5.0, help="max %% a close may sit below entry (default 5)")
    args = ap.parse_args()

    hold = args.hold
    before = args.period - hold
    if before < 5:
        sys.exit(f"period {args.period} too short (before window = {before})")

    mcap = load_mcap()
    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".csv"))
    print(f"Building turn dataset: period={args.period} (before={before}d, hold={hold}d), "
          f"win=+{args.win:.0f}%, dd<={args.dd:.0f}%, over {len(files)} stocks...", file=sys.stderr)

    frames, feat_cols = [], None
    for i, fn in enumerate(files, 1):
        if i % 200 == 0:
            print(f"  ... {i}/{len(files)} stocks", file=sys.stderr)
        code = fn[:-4]
        try:
            df = pd.read_csv(os.path.join(HISTORY_DIR, fn), parse_dates=["Date"])
        except Exception:
            continue
        if df.empty or "Close" not in df.columns or len(df) < before + hold + 2:
            continue
        out, fc = build_one(df, mcap.get(code, np.nan), before, hold, args.win, args.dd)
        feat_cols = fc
        if not out.empty:
            out.insert(0, "code", code)
            frames.append(out)

    if not frames:
        sys.exit("no data collected")
    data = pd.concat(frames, ignore_index=True)

    pos = int(data["label"].sum())
    n = len(data)
    rate = pos / n * 100

    # save (parquet preferred, csv.gz fallback)
    os.makedirs(SHARE_DIR, exist_ok=True)
    out_path = os.path.join(SHARE_DIR, "turn_dataset.parquet")
    try:
        data.to_parquet(out_path, index=False)
    except Exception as e:
        out_path = os.path.join(SHARE_DIR, "turn_dataset.csv.gz")
        data.to_csv(out_path, index=False, compression="gzip")
        print(f"(parquet unavailable: {e}; wrote csv.gz)", file=sys.stderr)

    # report
    print("\n" + "=" * 60)
    print(f"TURN DATASET  period={args.period} (before={before}d, hold={hold}d)  label=+{args.win:.0f}%/{hold}d pure-up (dd<={args.dd:.0f}%)")
    print("=" * 60)
    print(f"stock-days (rows) ... {n:,}")
    print(f"positives (turners) . {pos:,}")
    print(f"negatives ........... {n - pos:,}")
    print(f"base rate ........... {rate:.2f}%")
    print(f"feature cols ........ {len(feat_cols)}  (r0..r{before-1}, vr0..vr{before-1}) + mcap_b")
    print(f"saved -> {out_path}")

    # cap-band breakdown for THIS label
    sub = data.dropna(subset=["mcap_b"]).copy()
    if not sub.empty:
        sub["band"] = pd.qcut(sub["mcap_b"], 6, duplicates="drop")
        g = sub.groupby("band", observed=True)["label"]
        brate, bn = g.mean() * 100, g.size()
        base = sub["label"].mean() * 100
        print("\nWhere are the fish? positive-rate by float-mcap band (this label):")
        print(f"  {'mcap band (B yuan)':<26}{'n':>10}{'turn%':>9}{'lift':>8}")
        for itv in brate.index:
            lift = brate[itv] / base if base > 0 else 0
            txt = f"[{itv.left:.1f}, {itv.right:.1f}]"
            print(f"  {txt:<26}{bn[itv]:>10,}{brate[itv]:>8.2f}%{lift:>7.1f}x")
        print(f"  (base rate among cap-known rows: {base:.2f}%)")


if __name__ == "__main__":
    main()
