#!/usr/bin/env python3
"""
US Trend-Template scorecard — scores each price_<T>.txt against frame.md 第三层.

frame.md Trend Template (9 conditions, need >=8/9; #1/#5/#8/#9 are mandatory):
  1. price > 150MA > 200MA
  2. 200MA rising >= ~1 month (today's 200MA > 200MA ~21 trading days ago)
  3. 150MA > 200MA
  4. 50MA > 150MA > 200MA
  5. price > 50MA
  6. price >= +30% above 52-week low
  7. price within 25% of 52-week high (price >= 0.75 * 52w high)
  8. RS >= 80   -> NOT computable here (needs full-market ranking) -> reported as N/A
  9. weekly: close > 30-week MA, 30wMA rising over 13 weeks, <=2/13 weeks below (tolerance)
 10. monthly: close > 12-month MA, 12mMA rising over 6 months, <=2/12 months below
Plus Weinstein Stage (2 = price above a rising 30-week MA = the only buy stage).

Data: u/ushare_data/price_<T>.txt  (cols Date,Open,Close,High,Low,Volume,Turnover,Amplitude).
~2y of daily bars is enough for all of the above (monthly #10 is the tightest).

Usage:
    python utrend.py                 # score every price_*.txt
    python utrend.py NVDA GEV VRT    # only these
"""

import os
import re
import sys
import argparse
from io import StringIO

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.normpath(os.path.join(HERE, "..", "ushare_data"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def load(path):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    hdr = next(i for i, ln in enumerate(lines) if ln.startswith("Date,"))
    df = pd.read_csv(StringIO("".join(lines[hdr:])))
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def pct(a, b):
    return (a / b - 1) * 100 if b else float("nan")


def score(df):
    c = df["Close"]
    price = c.iloc[-1]
    ma50, ma150, ma200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
    m50, m150, m200 = ma50.iloc[-1], ma150.iloc[-1], ma200.iloc[-1]
    m200_1mo = ma200.iloc[-22] if len(ma200) > 22 else float("nan")

    win = df.tail(252)
    hi52, lo52 = win["High"].max(), win["Low"].min()

    # weekly (#9) and monthly (#10) on a datetime index
    s = c.copy()
    s.index = df["Date"]
    wk = s.resample("W-FRI").last().dropna()
    wma30 = wk.rolling(30).mean()
    mo = s.resample("ME").last().dropna()
    mma12 = mo.rolling(12).mean()

    def slope_up(series, lag):
        if len(series.dropna()) <= lag:
            return None
        return series.iloc[-1] > series.iloc[-1 - lag]

    # #8 weekly
    w_ok = None
    if wma30.notna().sum() >= 1 and len(wk) >= 13:
        above_now = wk.iloc[-1] > wma30.iloc[-1]
        rising = slope_up(wma30, 13)
        last13 = (wk.iloc[-13:] < wma30.iloc[-13:]).sum()
        w_ok = bool(above_now) and bool(rising) and (last13 <= 2)
        w_detail = f"周收{wk.iloc[-1]:.0f} vs 30wMA{wma30.iloc[-1]:.0f}, 破位{int(last13)}/13"
    else:
        w_detail = "数据不足"

    # #9 monthly
    m_ok = None
    if mma12.notna().sum() >= 1 and len(mo) >= 6:
        above_now = mo.iloc[-1] > mma12.iloc[-1]
        rising = slope_up(mma12, 6)
        last12 = (mo.iloc[-12:] < mma12.iloc[-12:]).sum()
        m_ok = bool(above_now) and bool(rising) and (last12 <= 2)
        m_detail = f"月收{mo.iloc[-1]:.0f} vs 12mMA{mma12.iloc[-1]:.0f}, 破位{int(last12)}/12"
    else:
        m_detail = "数据不足"

    conds = {
        1: price > m150 > m200,
        2: (m200 > m200_1mo) if pd.notna(m200_1mo) else None,
        3: m150 > m200,
        4: m50 > m150 > m200,
        5: price > m50,
        6: price >= 1.30 * lo52,
        7: price >= 0.75 * hi52,
        8: w_ok,
        9: m_ok,
    }

    # Weinstein stage (simplified, from 30-week MA = weekly)
    w_rising = slope_up(wma30, 13)
    above_w = wk.iloc[-1] > wma30.iloc[-1] if wma30.notna().iloc[-1] else None
    if above_w and w_rising:
        stage = "2 上升"
    elif (above_w is False) and (w_rising is False):
        stage = "4 下降"
    else:
        stage = "1/3 过渡"

    computable = [k for k in conds if conds[k] is not None]
    passed = sum(1 for k in computable if conds[k])
    mand = {1: conds[1], 5: conds[5], 8: conds[8], 9: conds[9]}
    mand_ok = all(v for v in mand.values() if v is not None)

    return {
        "price": price, "ma50": m50, "ma150": m150, "ma200": m200,
        "hi52": hi52, "lo52": lo52,
        "from_low": pct(price, lo52), "from_high": pct(price, hi52),
        "conds": conds, "passed": passed, "n": len(computable),
        "mand_ok": mand_ok, "stage": stage,
        "w_detail": w_detail, "m_detail": m_detail,
        "last_date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
    }


def cells(conds):
    out = []
    for k in range(1, 10):
        v = conds[k]
        mark = "?" if v is None else ("✓" if bool(v) else "✗")  # bool() handles numpy bool
        out.append(f"#{k}{mark}")
    return " ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--outdir", default=OUTDIR)
    args = ap.parse_args()

    if args.tickers:
        files = [os.path.join(args.outdir, f"price_{t.upper()}.txt") for t in args.tickers]
    else:
        files = [os.path.join(args.outdir, f) for f in sorted(os.listdir(args.outdir))
                 if re.match(r"^price_.+\.txt$", f)]

    for path in files:
        t = re.match(r"^price_(.+)\.txt$", os.path.basename(path)).group(1).upper()
        if not os.path.exists(path):
            print(f"\n=== {t} ===  (no file)")
            continue
        df = load(path)
        if len(df) < 200:
            print(f"\n=== {t} ===  data {len(df)} rows < 200, skip")
            continue
        r = score(df)
        verdict = "买点候选(过)" if (r["passed"] >= 8 and r["mand_ok"]) else "未过"
        print(f"\n=== {t} ===  收 ${r['price']:.2f} ({r['last_date']})   "
              f"{r['passed']}/{r['n']} 条过, 强制项{'OK' if r['mand_ok'] else '未满足'}, Stage {r['stage']}  -> {verdict}")
        print(f"  {cells(r['conds'])}")
        print(f"  50MA {r['ma50']:.1f}  150MA {r['ma150']:.1f}  200MA {r['ma200']:.1f}")
        print(f"  距52周低 {r['from_low']:+.0f}%  距52周高 {r['from_high']:+.0f}%  (高{r['hi52']:.0f}/低{r['lo52']:.0f})")
        print(f"  周线 {r['w_detail']}")
        print(f"  月线 {r['m_detail']}")


if __name__ == "__main__":
    main()
