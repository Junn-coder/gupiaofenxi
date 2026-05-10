"""
analyze.py — local analysis runner, no email, no GitHub Actions needed.

Run:
    python analyze.py                      # screen whitelist, no AI analysis
    python analyze.py --api-key YOUR_KEY  # include DeepSeek AI commentary

This file contains the fixed core logic. gpfenxi.py stays unchanged for
GitHub Actions (email delivery). Both files share the same WHITELIST and
screening thresholds so results are consistent.

Fixes vs gpfenxi.py:
  - get_q1_growth() uses named field access (dict(zip(fields, row))) instead
    of fragile index positions — the original indices were wrong (row[1] was
    pubDate not year; row[4] was npMargin not netProfit; row[6] was netProfit
    not revenue).
  - Year is derived from statDate[:4] instead of row[1].
  - bs.logout() is guaranteed via try/finally even when an exception is raised.
  - Years are dynamic (current_year / prev_year) instead of hard-coded 2025/2026.
  - screen_growth_stocks() does not require revenue_growth — MBRevenue is empty
    for most stocks on this API; profit_growth alone drives the filter.
"""

import os
import sys
import argparse
from datetime import date, timedelta

import requests
import baostock as bs


WHITELIST = [
    {"code": "603629", "name": "利通电子",  "sector": "AI算力租赁"},
    {"code": "688610", "name": "埃科光电",  "sector": "机器视觉"},
    {"code": "002266", "name": "浙富控股",  "sector": "资源化/清洁能源"},
    {"code": "301162", "name": "国能日新",  "sector": "新能源数字化"},
    {"code": "003010", "name": "若羽臣",    "sector": "电商运营转型"},
]

PROFIT_GROWTH_THRESHOLD = 30   # %
REVENUE_GROWTH_THRESHOLD = 20  # % (optional — skipped when MBRevenue is empty)


# ---------------------------------------------------------------------------
# baostock helpers
# ---------------------------------------------------------------------------

def _bs_code(stock_code):
    return f"sh.{stock_code}" if stock_code.startswith('6') else f"sz.{stock_code}"


def get_q1_growth(stock_code):
    """
    Fetch Q1 YoY profit and revenue growth for a China A-share stock.

    Returns (revenue_growth, profit_growth, debug_info).
    revenue_growth may be None when MBRevenue is not reported (common on baostock).
    profit_growth is None when data is unavailable or an error occurs.
    """
    debug = []
    current_year = date.today().year
    prev_year = current_year - 1
    code = _bs_code(stock_code)

    lg = bs.login()
    if lg.error_code != '0':
        return None, None, f"login failed: {lg.error_msg}"

    try:
        by_year = {}
        for year in [prev_year, current_year]:
            rs = bs.query_profit_data(code=code, year=year, quarter=1)
            if rs.error_code != '0':
                debug.append(f"{year}Q1 query failed: {rs.error_msg}")
                continue
            while rs.next():
                row = dict(zip(rs.fields, rs.get_row_data()))
                stat_year = row.get('statDate', '')[:4]
                if not stat_year:
                    continue
                net_profit_str = row.get('netProfit', '')
                mb_revenue_str = row.get('MBRevenue', '')
                by_year[stat_year] = {
                    'net_profit': float(net_profit_str) if net_profit_str else None,
                    'revenue':    float(mb_revenue_str) if mb_revenue_str else None,
                }
                debug.append(
                    f"{stat_year}Q1: netProfit={net_profit_str!r}, MBRevenue={mb_revenue_str!r}"
                )
    finally:
        bs.logout()

    prev = by_year.get(str(prev_year))
    curr = by_year.get(str(current_year))

    if not prev or not curr:
        debug.append(f"missing data — got years: {list(by_year)}")
        return None, None, '\n'.join(debug)

    if not prev['net_profit']:
        debug.append("prev net_profit is zero or missing — cannot compute growth")
        return None, None, '\n'.join(debug)

    profit_growth = (curr['net_profit'] - prev['net_profit']) / abs(prev['net_profit']) * 100
    debug.append(
        f"profit: {prev['net_profit']:.2f} -> {curr['net_profit']:.2f} = {profit_growth:+.2f}%"
    )

    revenue_growth = None
    if prev['revenue'] and curr['revenue']:
        revenue_growth = (curr['revenue'] - prev['revenue']) / abs(prev['revenue']) * 100
        debug.append(f"revenue growth: {revenue_growth:+.2f}%")
    else:
        debug.append("MBRevenue empty — revenue growth not available")

    return revenue_growth, profit_growth, '\n'.join(debug)


def get_price_history(stock_code, start_date=None, end_date=None, frequency='d'):
    """
    Fetch daily/weekly/monthly price history for a stock.

    start_date / end_date: 'YYYY-MM-DD', defaults to last 6 months.
    frequency: 'd' daily | 'w' weekly | 'm' monthly.
    Returns list of dicts: date, open, high, low, close, volume, amount, pctChg, turn.
    """
    if end_date is None:
        end_date = date.today().strftime('%Y-%m-%d')
    if start_date is None:
        start_date = (date.today() - timedelta(days=183)).strftime('%Y-%m-%d')

    code = _bs_code(stock_code)
    lg = bs.login()
    if lg.error_code != '0':
        return []

    try:
        rs = bs.query_history_k_data_plus(
            code,
            'date,open,high,low,close,volume,amount,pctChg,turn',
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag='2',
        )
        if rs.error_code != '0':
            return []
        rows = []
        while rs.next():
            r = dict(zip(rs.fields, rs.get_row_data()))
            rows.append({
                'date':   r['date'],
                'open':   float(r['open'])   if r['open']   else None,
                'high':   float(r['high'])   if r['high']   else None,
                'low':    float(r['low'])    if r['low']    else None,
                'close':  float(r['close'])  if r['close']  else None,
                'volume': int(r['volume'])   if r['volume'] else None,
                'amount': float(r['amount']) if r['amount'] else None,
                'pctChg': float(r['pctChg']) if r['pctChg'] else None,
                'turn':   float(r['turn'])   if r['turn']   else None,
            })
        return rows
    finally:
        bs.logout()


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

def screen_growth_stocks():
    """
    Screen WHITELIST stocks by Q1 YoY growth.
    Returns list of candidates that pass the thresholds.
    """
    candidates = []
    for item in WHITELIST:
        code, name, sector = item['code'], item['name'], item['sector']
        print(f"  Checking {name} ({code}) ...")
        rev_growth, prof_growth, debug = get_q1_growth(code)

        if prof_growth is None:
            print(f"    [SKIP] no profit data — {debug.splitlines()[-1]}")
            continue

        rev_str = f"{rev_growth:+.1f}%" if rev_growth is not None else "n/a"
        print(f"    profit growth: {prof_growth:+.1f}%  revenue growth: {rev_str}")

        prof_ok = prof_growth > PROFIT_GROWTH_THRESHOLD
        rev_ok  = rev_growth is None or rev_growth > REVENUE_GROWTH_THRESHOLD

        if prof_ok and rev_ok:
            print(f"    [PASS]")
            candidates.append({
                "code":           code,
                "name":           name,
                "sector":         sector,
                "profit_growth":  round(prof_growth, 2),
                "revenue_growth": round(rev_growth, 2) if rev_growth is not None else None,
                "debug":          debug,
            })
        else:
            reasons = []
            if not prof_ok:
                reasons.append(f"profit {prof_growth:.1f}% < {PROFIT_GROWTH_THRESHOLD}%")
            if not rev_ok:
                reasons.append(f"revenue {rev_growth:.1f}% < {REVENUE_GROWTH_THRESHOLD}%")
            print(f"    [FAIL] {', '.join(reasons)}")

    return candidates


# ---------------------------------------------------------------------------
# AI commentary (optional)
# ---------------------------------------------------------------------------

def analyze_with_deepseek(stock_info, api_key):
    prompt = (
        f"请分析以下A股股票的投资价值，重点关注3-6个月是否有30%-50%上涨潜力：\n"
        f"- 股票名称：{stock_info['name']}（{stock_info['code']}）\n"
        f"- 所属赛道：{stock_info['sector']}\n"
        f"- 一季度净利润同比：{stock_info['profit_growth']}%\n"
        f"- 一季度营收同比：{stock_info['revenue_growth']}%\n\n"
        f"输出格式：\n"
        f"1. 核心成长逻辑（2-3点）\n"
        f"2. 主要风险（2点）\n"
        f"3. 综合评级：A（强烈看好）/B（一般）/C（回避）\n"
        f"4. 3-6个月预期涨幅区间：xx%\n"
    )
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.7},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[AI analysis failed: {e}]"


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def print_price_table(rows, label):
    if not rows:
        print(f"  {label}: no data")
        return
    closes = [r['close'] for r in rows if r['close'] is not None]
    print(f"\n  {label}  {rows[0]['date']} -> {rows[-1]['date']}  ({len(rows)} trading days)")
    print(f"  close range: {min(closes):.2f} – {max(closes):.2f} CNY")
    print(f"  {'date':<12} {'open':>8} {'high':>8} {'low':>8} {'close':>8} {'pctChg':>8} {'volume':>10}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    for r in rows[-10:]:
        vol = f"{r['volume']:,}" if r['volume'] else '-'
        print(f"  {r['date']:<12} {r['open']:>8.2f} {r['high']:>8.2f} "
              f"{r['low']:>8.2f} {r['close']:>8.2f} {r['pctChg']:>7.2f}% {vol:>10}")


def print_report(candidates, api_key=None):
    today = date.today().strftime('%Y-%m-%d')
    print(f"\n{'='*60}")
    print(f"  Stock Screening Report — {today}")
    print(f"  Thresholds: profit growth > {PROFIT_GROWTH_THRESHOLD}%,"
          f" revenue growth > {REVENUE_GROWTH_THRESHOLD}% (or n/a)")
    print(f"{'='*60}")

    if not candidates:
        print("\n  No stocks passed the thresholds today.")
    else:
        print(f"\n  {len(candidates)} stock(s) passed:\n")
        for c in candidates:
            rev_str = f"{c['revenue_growth']:+.2f}%" if c['revenue_growth'] is not None else "n/a"
            print(f"  {c['name']} ({c['code']})  [{c['sector']}]")
            print(f"    profit growth: {c['profit_growth']:+.2f}%   revenue growth: {rev_str}")

            rows = get_price_history(c['code'])
            print_price_table(rows, f"{c['code']} last 6 months")

            if api_key:
                print(f"\n  --- DeepSeek analysis ---")
                print(analyze_with_deepseek(c, api_key))

            print()

    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Screen whitelist stocks locally.')
    parser.add_argument('--api-key', default=os.getenv('_API_KEY'),
                        help='DeepSeek API key for AI commentary (optional)')
    args = parser.parse_args()

    print(f"\nScreening {len(WHITELIST)} stocks ...")
    candidates = screen_growth_stocks()
    print_report(candidates, api_key=args.api_key)


if __name__ == '__main__':
    main()
