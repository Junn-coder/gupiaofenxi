"""
test_profit_fields.py — Diagnostic & regression tests for baostock price and profit data

Background (found 2026-05-10):
  The original get_q1_growth() used query_profit_data() with wrong field indices.
  Actual field order from the API (verified with sh.688610):

    [0] code        e.g. 'sh.688610'
    [1] pubDate     e.g. '2025-04-18'   <-- NOT year; the original code used this as year
    [2] statDate    e.g. '2025-03-31'   <-- derive year from here
    [3] roeAvg      e.g. '0.005919'
    [4] npMargin    e.g. '0.115212'     <-- original code read this as netProfit (WRONG)
    [5] gpMargin    e.g. '0.398289'
    [6] netProfit   e.g. '8623448.88'   <-- original code read this as revenue (WRONG)
    [7] epsTTM      e.g. '0.223221'
    [8] MBRevenue   e.g. ''             <-- often empty; original code never read this
    [9] totalShare
   [10] liqaShare

  Correct approach: use dict(zip(rs.fields, row)) for named field access,
  and extract year from statDate[:4] rather than storing row[1].

Run:
    python test_profit_fields.py             # all tests (requires network)
    python test_profit_fields.py -v          # verbose
"""

import sys
import unittest
from datetime import date, timedelta
import baostock as bs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login():
    lg = bs.login()
    assert lg.error_code == '0', f"baostock login failed: {lg.error_msg}"


def _logout():
    bs.logout()


def query_profit_named(bs_code, year, quarter=1):
    """Return a list of dicts with named fields for query_profit_data."""
    rs = bs.query_profit_data(code=bs_code, year=year, quarter=quarter)
    if rs.error_code != '0':
        return None, rs.error_msg
    rows = []
    while rs.next():
        row = dict(zip(rs.fields, rs.get_row_data()))
        rows.append(row)
    return rows, None


def get_q1_growth_fixed(stock_code):
    """
    Corrected version of get_q1_growth using named fields and dynamic years.
    Returns (revenue_growth, profit_growth, debug_info).
    revenue_growth may be None if MBRevenue is empty.
    """
    debug = []
    current_year = date.today().year
    prev_year = current_year - 1
    bs_code = f"sh.{stock_code}" if stock_code.startswith('6') else f"sz.{stock_code}"

    _login()
    try:
        profit_data = []
        for year in [prev_year, current_year]:
            rows, err = query_profit_named(bs_code, year)
            if err:
                debug.append(f"query {year}Q1 failed: {err}")
                continue
            for row in rows:
                stat_year = row.get('statDate', '')[:4]
                net_profit_str = row.get('netProfit', '')
                mb_revenue_str = row.get('MBRevenue', '')
                profit_data.append({
                    'year': stat_year,
                    'net_profit': float(net_profit_str) if net_profit_str else None,
                    'revenue': float(mb_revenue_str) if mb_revenue_str else None,
                })
                debug.append(
                    f"{year}Q1: netProfit={net_profit_str!r}, MBRevenue={mb_revenue_str!r}"
                )
    finally:
        _logout()

    by_year = {r['year']: r for r in profit_data}
    prev = by_year.get(str(prev_year))
    curr = by_year.get(str(current_year))

    if not prev or not curr:
        debug.append(f"missing data: prev={prev}, curr={curr}")
        return None, None, '\n'.join(debug)

    if not prev['net_profit']:
        debug.append("prev net_profit is zero or missing")
        return None, None, '\n'.join(debug)

    profit_growth = (curr['net_profit'] - prev['net_profit']) / abs(prev['net_profit']) * 100
    debug.append(f"profit growth: {prev['net_profit']:.2f} -> {curr['net_profit']:.2f} = {profit_growth:.2f}%")

    revenue_growth = None
    if prev['revenue'] and curr['revenue'] and prev['revenue'] != 0:
        revenue_growth = (curr['revenue'] - prev['revenue']) / abs(prev['revenue']) * 100
        debug.append(f"revenue growth: {revenue_growth:.2f}%")
    else:
        debug.append("MBRevenue empty — revenue growth not available")

    return revenue_growth, profit_growth, '\n'.join(debug)


def query_price_history(stock_code, start_date=None, end_date=None, frequency='d'):
    """
    Query daily (or weekly/monthly) price history for a China A-share stock.

    Parameters
    ----------
    stock_code  : str   bare code, e.g. '688610', '600519', '002266'
    start_date  : str   'YYYY-MM-DD'; defaults to 6 months before end_date
    end_date    : str   'YYYY-MM-DD'; defaults to today
    frequency   : str   'd' daily | 'w' weekly | 'm' monthly

    Returns
    -------
    list[dict]  one dict per trading day, keys:
                  date, open, high, low, close, volume, amount, pctChg, turn
                empty list if no data or on error.

    Fields from baostock (adjustflag='2' = backward-adjusted so prices are comparable):
      date        trading date
      open/high/low/close  prices in CNY
      volume      shares traded
      amount      CNY traded
      pctChg      daily % change
      turn        turnover rate (%)
    """
    bs_code = f"sh.{stock_code}" if stock_code.startswith('6') else f"sz.{stock_code}"

    if end_date is None:
        end_date = date.today().strftime('%Y-%m-%d')
    if start_date is None:
        start_date = (date.today() - timedelta(days=183)).strftime('%Y-%m-%d')

    _login()
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            'date,open,high,low,close,volume,amount,pctChg,turn',
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag='2',  # backward-adjusted
        )
        if rs.error_code != '0':
            return []
        rows = []
        while rs.next():
            row = dict(zip(rs.fields, rs.get_row_data()))
            rows.append({
                'date':   row['date'],
                'open':   float(row['open'])   if row['open']   else None,
                'high':   float(row['high'])   if row['high']   else None,
                'low':    float(row['low'])    if row['low']    else None,
                'close':  float(row['close'])  if row['close']  else None,
                'volume': int(row['volume'])   if row['volume'] else None,
                'amount': float(row['amount']) if row['amount'] else None,
                'pctChg': float(row['pctChg']) if row['pctChg'] else None,
                'turn':   float(row['turn'])   if row['turn']   else None,
            })
        return rows
    finally:
        _logout()


def print_price_summary(rows, stock_code):
    """Print a compact price table for quick visual inspection."""
    if not rows:
        print(f"  {stock_code}: no data")
        return
    closes = [r['close'] for r in rows if r['close'] is not None]
    print(f"\n  {stock_code}  {rows[0]['date']} -> {rows[-1]['date']}  ({len(rows)} days)")
    print(f"  close range: {min(closes):.2f} – {max(closes):.2f} CNY")
    print(f"  {'date':<12} {'open':>8} {'high':>8} {'low':>8} {'close':>8} {'pctChg':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for r in rows[-10:]:  # show last 10 rows
        print(f"  {r['date']:<12} {r['open']:>8.2f} {r['high']:>8.2f} "
              f"{r['low']:>8.2f} {r['close']:>8.2f} {r['pctChg']:>7.2f}%")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFieldStructure(unittest.TestCase):
    """Verify the actual field names returned by query_profit_data."""

    EXPECTED_FIELDS = [
        'code', 'pubDate', 'statDate', 'roeAvg',
        'npMargin', 'gpMargin', 'netProfit', 'epsTTM',
        'MBRevenue', 'totalShare', 'liqaShare',
    ]

    @classmethod
    def setUpClass(cls):
        _login()

    @classmethod
    def tearDownClass(cls):
        _logout()

    def test_field_names_match_expected(self):
        """query_profit_data fields must match the documented order."""
        rs = bs.query_profit_data(code='sh.688610', year=2025, quarter=1)
        self.assertEqual(rs.error_code, '0', rs.error_msg)
        self.assertEqual(rs.fields, self.EXPECTED_FIELDS,
                         "Field order changed — update index references in get_q1_growth")

    def test_stat_date_contains_year(self):
        """statDate (index 2) should start with a 4-digit year."""
        rs = bs.query_profit_data(code='sh.688610', year=2025, quarter=1)
        self.assertEqual(rs.error_code, '0')
        rs.next()
        row = rs.get_row_data()
        stat_date = row[2]
        self.assertTrue(stat_date.startswith('2025'), f"statDate={stat_date!r}")

    def test_pub_date_is_not_year(self):
        """pubDate (index 1) is a full date string, NOT a plain year — the original bug."""
        rs = bs.query_profit_data(code='sh.688610', year=2025, quarter=1)
        self.assertEqual(rs.error_code, '0')
        rs.next()
        row = rs.get_row_data()
        pub_date = row[1]
        self.assertNotEqual(pub_date, '2025',
                            "pubDate should be a full date like '2025-04-18', not '2025'")
        self.assertRegex(pub_date, r'^\d{4}-\d{2}-\d{2}$')

    def test_net_profit_is_index_6_not_4(self):
        """netProfit is at index 6, not 4 (index 4 is npMargin)."""
        rs = bs.query_profit_data(code='sh.688610', year=2025, quarter=1)
        self.assertEqual(rs.error_code, '0')
        rs.next()
        row = rs.get_row_data()
        # npMargin at [4] is a ratio < 1; netProfit at [6] is an absolute value >> 1
        np_margin = float(row[4])
        net_profit = float(row[6])
        self.assertLess(abs(np_margin), 10,
                        f"[4] should be npMargin (small ratio), got {np_margin}")
        self.assertGreater(abs(net_profit), 1000,
                           f"[6] should be netProfit (large absolute), got {net_profit}")


class TestGet688610(unittest.TestCase):
    """Integration tests for stock 688610 (埃科光电) using the corrected function."""

    def test_profit_growth_is_calculable(self):
        """688610 should return a valid profit_growth (netProfit data exists)."""
        rev, prof, info = get_q1_growth_fixed('688610')
        print(f"\n688610: revenue_growth={rev}, profit_growth={prof}")
        print(info)
        self.assertIsNotNone(prof, f"profit_growth should not be None.\n{info}")

    def test_revenue_growth_is_none_for_688610(self):
        """688610 MBRevenue is empty — revenue_growth expected to be None."""
        rev, prof, info = get_q1_growth_fixed('688610')
        self.assertIsNone(rev,
            f"MBRevenue is empty for 688610, expected None but got {rev}.\n{info}")

    def test_profit_growth_is_positive(self):
        """688610 2026Q1 net profit is higher than 2025Q1 — growth should be positive."""
        _, prof, info = get_q1_growth_fixed('688610')
        self.assertIsNotNone(prof)
        self.assertGreater(prof, 0, f"Expected positive growth.\n{info}")


class TestGetOtherStocks(unittest.TestCase):
    """Sanity checks on other whitelist stocks."""

    def _check(self, code):
        rev, prof, info = get_q1_growth_fixed(code)
        print(f"\n{code}: revenue_growth={rev}, profit_growth={prof}")
        print(info)
        return rev, prof, info

    def test_600519(self):
        _, prof, info = self._check('600519')
        self.assertIsNotNone(prof, info)

    def test_002266(self):
        _, prof, info = self._check('002266')
        self.assertIsNotNone(prof, info)


class TestPriceHistory(unittest.TestCase):
    """Integration tests for query_price_history()."""

    def test_default_six_months_returns_data(self):
        """Default call (no dates) should return ~120 trading days."""
        rows = query_price_history('688610')
        print_price_summary(rows, '688610')
        self.assertGreater(len(rows), 50, "Expected at least 50 trading days in 6 months")

    def test_custom_date_range(self):
        """Custom date range should return only rows within that range."""
        rows = query_price_history('688610', start_date='2025-01-01', end_date='2025-03-31')
        print_price_summary(rows, '688610 (2025 Q1)')
        self.assertTrue(all(r['date'] >= '2025-01-01' for r in rows))
        self.assertTrue(all(r['date'] <= '2025-03-31' for r in rows))

    def test_close_price_is_positive(self):
        """All close prices should be positive numbers."""
        rows = query_price_history('688610', start_date='2025-11-01', end_date='2025-12-31')
        for r in rows:
            if r['close'] is not None:
                self.assertGreater(r['close'], 0, f"Non-positive close on {r['date']}")

    def test_high_gte_low_each_day(self):
        """Daily high must be >= low."""
        rows = query_price_history('688610', start_date='2025-11-01', end_date='2025-12-31')
        for r in rows:
            if r['high'] is not None and r['low'] is not None:
                self.assertGreaterEqual(r['high'], r['low'],
                    f"high < low on {r['date']}: high={r['high']}, low={r['low']}")

    def test_rows_sorted_by_date_ascending(self):
        """Rows should come back in chronological order."""
        rows = query_price_history('688610', start_date='2025-01-01', end_date='2025-06-30')
        dates = [r['date'] for r in rows]
        self.assertEqual(dates, sorted(dates))

    def test_weekly_frequency(self):
        """Weekly frequency should return fewer rows than daily for the same period."""
        daily = query_price_history('688610', start_date='2025-01-01', end_date='2025-06-30',
                                    frequency='d')
        weekly = query_price_history('688610', start_date='2025-01-01', end_date='2025-06-30',
                                     frequency='w')
        print(f"\n  daily rows={len(daily)}, weekly rows={len(weekly)}")
        self.assertGreater(len(daily), len(weekly))

    def test_sh_and_sz_prefix(self):
        """SH stock (688610) and SZ stock (002266) should both return data."""
        sh_rows = query_price_history('688610', start_date='2026-01-01')
        sz_rows = query_price_history('002266', start_date='2026-01-01')
        self.assertGreater(len(sh_rows), 0, "SH stock returned no data")
        self.assertGreater(len(sz_rows), 0, "SZ stock returned no data")

    def test_invalid_code_returns_empty(self):
        """Invalid stock code should return an empty list, not raise."""
        rows = query_price_history('999999', start_date='2026-01-01')
        self.assertEqual(rows, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
