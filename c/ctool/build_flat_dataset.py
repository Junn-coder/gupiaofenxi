#!/usr/bin/env python3
"""
build_flat_dataset.py — prepare training data for the flat-then-erupt hunt.

Filters stock-days to those that are QUIET and COILING (flatness gate), then labels:
  1 = erupted (forward 10d >= +10%) from flatness
  0 = stayed flat (forward 10d < +5%)
  (forward 5-10% excluded — ambiguous, don't teach either signal)

Features are computed by build_one() from build_turn_dataset.py — 49 features total
(raw r0..r19, vr0..vr19, + 8 engineered: mom20, mom5, pct_from_high250, vol_ratio20,
ma_aligned, above_ma20, range_contract, turnover_yi, mcap_b).

Output: share_data/flat_dataset.parquet

Usage:
    python build_flat_dataset.py
    python build_flat_dataset.py --win 15 --dd 8  # tighter bar
"""
import os
import sys
import argparse
import csv

import numpy as np
import pandas as pd

from build_turn_dataset import build_one, load_mcap, HISTORY_DIR

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SHARE_DIR = os.path.join(TOOL_DIR, "share_data")

# Flatness gate parameters
LOW_MOM_MAX = 15.0       # mom20 must be in [-5%, +15%] — not trending strongly
RANGE_TIGHT = 0.85       # 5d range / 20d range < 0.85 — tightening
FLAT_DAYS_MIN = 16       # >= 16 of 20 days with abs(daily ret) < 3% — quiet
FWD_FLAT_MAX = 5.0       # forward < 5% = stayed flat (negative class)
FWD_ERUPT_MIN = 10.0     # forward >= 10% = erupted (positive class)

BEFORE = 20
HOLD = 10


def build_flat_dataset(win_pct: float = 10.0, dd_tol: float = 5.0):
    mcap = load_mcap()
    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".csv"))

    print(f"Building flat-erupt dataset: quiet coiling -> erupt +{win_pct:.0f}%/{HOLD}d, "
          f"max dd {dd_tol:.0f}%, over {len(files)} stocks...", file=sys.stderr)

    frames = []
    skipped_short = 0
    skipped_not_flat = 0
    skipped_ambiguous = 0
    positive = 0
    negative = 0

    for i, fn in enumerate(files, 1):
        if i % 200 == 0:
            print(f"  ... {i}/{len(files)} stocks", file=sys.stderr)
        code = fn[:-4]
        try:
            df = pd.read_csv(os.path.join(HISTORY_DIR, fn), parse_dates=["Date"])
        except Exception:
            continue

        if df.empty or "Close" not in df.columns or len(df) < 270:
            skipped_short += 1
            continue

        # compute full feature matrix via build_one (all 49 features)
        out, feat_cols = build_one(df, mcap.get(code, np.nan), BEFORE, HOLD, win_pct, dd_tol)
        if out.empty:
            continue

        # Now apply flatness gate: only keep rows where day D was coiling
        df_sorted = df.sort_values("Date").reset_index(drop=True)
        c, h, l = df_sorted["Close"], df_sorted["High"], df_sorted["Low"]
        ret_raw = (c / c.shift(1) - 1) * 100
        mom20_raw = (c / c.shift(20) - 1) * 100
        rng = h - l
        rng5 = rng.rolling(5).mean()
        rng20 = rng.rolling(20).mean()
        range_contract_raw = rng5 / rng20
        small_ret = (ret_raw.abs() < 3).rolling(20).sum()

        # Map flatness metrics to out's Date index
        date_to_idx = {d: j for j, d in enumerate(df_sorted["Date"])}

        keep_mask = []
        flat_labels = []
        for _, row in out.iterrows():
            d = row["Date"]
            j = date_to_idx.get(d)
            if j is None or j < 269:
                keep_mask.append(False)
                flat_labels.append(np.nan)
                continue

            is_flat = (
                -5.0 <= mom20_raw.iloc[j] <= LOW_MOM_MAX
                and pd.notna(range_contract_raw.iloc[j])
                and range_contract_raw.iloc[j] < RANGE_TIGHT
                and pd.notna(small_ret.iloc[j])
                and small_ret.iloc[j] >= FLAT_DAYS_MIN
            )
            keep_mask.append(is_flat)

            if is_flat:
                fwd = row["fwd_net"]
                if fwd >= FWD_ERUPT_MIN:
                    flat_labels.append(1)
                elif fwd < FWD_FLAT_MAX:
                    flat_labels.append(0)
                else:
                    flat_labels.append(np.nan)  # ambiguous 5-10%, skip
            else:
                flat_labels.append(np.nan)

        out = out[keep_mask].copy()
        flat_labels_arr = np.array(flat_labels)[np.array(keep_mask)]

        # Remove ambiguous rows
        valid = pd.notna(flat_labels_arr)
        out = out[valid].copy()
        flat_labels_arr = flat_labels_arr[valid]

        skipped_not_flat += sum(~np.array(keep_mask))
        skipped_ambiguous += sum(np.isnan(flat_labels_arr))

        if out.empty:
            continue

        out["label"] = flat_labels_arr.astype("int8")
        out.insert(0, "code", code)
        frames.append(out)
        positive += int(out["label"].sum())
        negative += int(len(out) - out["label"].sum())

    if not frames:
        sys.exit("no data collected")

    data = pd.concat(frames, ignore_index=True)
    n = len(data)
    rate = positive / n * 100 if n > 0 else 0

    os.makedirs(SHARE_DIR, exist_ok=True)
    out_path = os.path.join(SHARE_DIR, "flat_dataset.parquet")
    try:
        data.to_parquet(out_path, index=False)
    except Exception as e:
        out_path = os.path.join(SHARE_DIR, "flat_dataset.csv.gz")
        data.to_csv(out_path, index=False, compression="gzip")
        print(f"(parquet unavailable: {e}; wrote csv.gz)", file=sys.stderr)

    print("\n" + "=" * 60)
    print(f"FLAT-ERUPT DATASET  win=+{win_pct:.0f}%/{HOLD}d  dd<={dd_tol:.0f}%")
    print("=" * 60)
    print(f"stocks processed ......... {len(files)}")
    print(f"  skipped (history<270) .. {skipped_short}")
    print(f"  rows not flat .......... {skipped_not_flat:,}")
    print(f"  ambiguous (5-10% fwd) .. {skipped_ambiguous}")
    print(f"------------------------------")
    print(f"dataset rows ............ {n:,}")
    print(f"  erupt (label=1) ....... {positive:,}  ({rate:.2f}%)")
    print(f"  flat (label=0) ........ {negative:,}  ({100-rate:.2f}%)")
    print(f"feature cols ............ {len(feat_cols)}")
    print(f"saved -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Build flat-then-erupt training dataset")
    ap.add_argument("--win", type=float, default=10.0, help="erupt bar %% over 10 days (default 10)")
    ap.add_argument("--dd", type=float, default=5.0, help="max %% a close may sit below entry (default 5)")
    args = ap.parse_args()
    build_flat_dataset(args.win, args.dd)


if __name__ == "__main__":
    main()
