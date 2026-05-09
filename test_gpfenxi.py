"""
Test file for get_q1_growth() in gpfenxi.py
Uses mocking to avoid real baostock API calls in unit tests,
plus integration tests that call the real API.

Updated 2026-05-09: Now tests query_growth_data approach (not query_profit_data).
Growth data fields: [code, pubDate, statDate, yoRevenue, yoNetProfit, ...]
  [0]=code, [1]=pubDate, [2]=statDate, [3]=yoRevenue, [4]=yoNetProfit
"""
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gpfenxi


class MockBaostockResult:
    """Simulates baostock query result set."""
    def __init__(self, rows, error_code='0', error_msg=''):
        self.error_code = error_code
        self.error_msg = error_msg
        self._rows = rows
        self._index = -1

    def next(self):
        self._index += 1
        return self._index < len(self._rows)

    def get_row_data(self):
        if 0 <= self._index < len(self._rows):
            return self._rows[self._index]
        return []


class MockBaostockLogin:
    def __init__(self, error_code='0', error_msg=''):
        self.error_code = error_code
        self.error_msg = error_msg


class TestGetQ1Growth(unittest.TestCase):
    """Unit tests for get_q1_growth() with mocked baostock."""

    def setUp(self):
        gpfenxi.debug_logs.clear()

    def _mock_growth_row(self, code, yo_revenue, yo_net_profit):
        """Helper: create a growth_data row.
        [0]=code, [1]=pubDate, [2]=statDate, [3]=yoRevenue, [4]=yoNetProfit
        """
        return [code, '2026-04-25', '2026-03-31', str(yo_revenue), str(yo_net_profit),
                '', '', '']

    # ---- Normal Cases ----

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_normal_growth_positive(self, mock_login, mock_growth, mock_logout):
        """Test: Normal positive growth (rev=50%, prof=60%)."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([
            self._mock_growth_row('sh.603629', 0.50, 0.60)
        ])
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertAlmostEqual(rev, 50.0, places=2)
        self.assertAlmostEqual(prof, 60.0, places=2)
        self.assertIn('YoY', info)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_negative_growth(self, mock_login, mock_growth, mock_logout):
        """Test: Revenue up 20%, profit down 70%."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([
            self._mock_growth_row('sz.002266', 0.20, -0.70)
        ])
        rev, prof, info = gpfenxi.get_q1_growth('002266')
        self.assertAlmostEqual(rev, 20.0, places=2)
        self.assertAlmostEqual(prof, -70.0, places=2)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_turnaround_from_loss(self, mock_login, mock_growth, mock_logout):
        """Test: Loss-to-profit (rev=50%, prof=150%)."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([
            self._mock_growth_row('sz.301162', 0.50, 1.50)
        ])
        rev, prof, info = gpfenxi.get_q1_growth('301162')
        self.assertAlmostEqual(rev, 50.0, places=2)
        self.assertAlmostEqual(prof, 150.0, places=2)

    # ---- Edge Cases ----

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_zero_net_profit_in_base_year(self, mock_login, mock_growth, mock_logout):
        """Test: profit=0 -> should still calculate (growth_data returns raw ratio)."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([
            self._mock_growth_row('sh.688610', 0.50, 0.0)
        ])
        rev, prof, info = gpfenxi.get_q1_growth('688610')
        # profit=0 is valid ratio (e.g. 0% growth, or base was 0)
        # The new code doesn't special-case 0 profit, it just passes through
        self.assertIsNotNone(rev)
        self.assertIsNotNone(prof)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_zero_revenue_in_base_year(self, mock_login, mock_growth, mock_logout):
        """Test: revenue=0 -> still passes through (growth_data returns raw ratio)."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([
            self._mock_growth_row('sh.603629', 0.0, 0.60)
        ])
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertEqual(rev, 0.0)
        self.assertAlmostEqual(prof, 60.0, places=2)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_no_growth_data(self, mock_login, mock_growth, mock_logout):
        """Test: No growth data returned -> return None."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([])  # empty result
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertIsNone(rev)
        self.assertIsNone(prof)
        self.assertIn('No growth data', info)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_growth_query_error(self, mock_login, mock_growth, mock_logout):
        """Test: query_growth_data returns error -> return None."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([], error_code='-1', error_msg='API error')
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertIsNone(rev)
        self.assertIsNone(prof)
        self.assertIn('No growth data', info)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_login_failure(self, mock_login, mock_growth, mock_logout):
        """Test: baostock login fails -> return None."""
        mock_login.return_value = MockBaostockLogin(error_code='-1', error_msg='网络错误')
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertIsNone(rev)
        self.assertIsNone(prof)
        self.assertIn('login failed', info)

    # ---- Code Prefix Tests ----

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_sh_stock_code_prefix(self, mock_login, mock_growth, mock_logout):
        """Test: Stock code starting with '6' uses 'sh.' prefix."""
        mock_login.return_value = MockBaostockLogin()

        def check_code(code, year, quarter):
            self.assertEqual(code, 'sh.603629')
            self.assertEqual(year, 2026)
            self.assertEqual(quarter, 1)
            return MockBaostockResult([self._mock_growth_row('sh.603629', 0.50, 0.60)])

        mock_growth.side_effect = check_code
        gpfenxi.get_q1_growth('603629')

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_sz_stock_code_prefix(self, mock_login, mock_growth, mock_logout):
        """Test: Stock code NOT starting with '6' uses 'sz.' prefix."""
        mock_login.return_value = MockBaostockLogin()

        def check_code(code, year, quarter):
            self.assertEqual(code, 'sz.002266')
            self.assertEqual(year, 2026)
            self.assertEqual(quarter, 1)
            return MockBaostockResult([self._mock_growth_row('sz.002266', 0.20, 0.30)])

        mock_growth.side_effect = check_code
        gpfenxi.get_q1_growth('002266')

    # ---- Field Handling ----

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_insufficient_fields(self, mock_login, mock_growth, mock_logout):
        """Test: Row with <5 fields -> return None."""
        mock_login.return_value = MockBaostockLogin()
        # Only 4 fields instead of 5+
        mock_growth.return_value = MockBaostockResult([
            ['sh.603629', '2026-04-25', '2026-03-31', '0.50']
        ])
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertIsNone(rev)
        self.assertIsNone(prof)
        self.assertIn('fields', info)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_empty_yo_revenue(self, mock_login, mock_growth, mock_logout):
        """Test: Empty yoRevenue string -> treat as 0.0."""
        mock_login.return_value = MockBaostockLogin()
        row = ['sh.603629', '2026-04-25', '2026-03-31', '', '0.60']
        mock_growth.return_value = MockBaostockResult([row])
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertEqual(rev, 0.0)
        self.assertAlmostEqual(prof, 60.0, places=2)

    @patch('gpfenxi.bs.logout')
    @patch('gpfenxi.bs.query_growth_data')
    @patch('gpfenxi.bs.login')
    def test_large_growth_rates(self, mock_login, mock_growth, mock_logout):
        """Test: Very large growth rates (e.g., 500% profit growth)."""
        mock_login.return_value = MockBaostockLogin()
        mock_growth.return_value = MockBaostockResult([
            self._mock_growth_row('sh.603629', 2.50, 5.0)  # 250% and 500%
        ])
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        self.assertAlmostEqual(rev, 250.0, places=2)
        self.assertAlmostEqual(prof, 500.0, places=2)


class TestGetQ1GrowthIntegration(unittest.TestCase):
    """Integration tests that call the real baostock API.
    These tests require network access.
    """

    def setUp(self):
        gpfenxi.debug_logs.clear()

    def _print_growth_row(self, code):
        """Debug helper: show growth_data field structure."""
        import baostock as bs
        lg = bs.login()
        if lg.error_code == '0':
            bs_code = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
            rs = bs.query_growth_data(code=bs_code, year=2026, quarter=1)
            if rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                labels = ['code', 'pubDate', 'statDate', 'yoRevenue', 'yoNetProfit',
                          'grossProfitRate', 'netProfitRate', 'roeYear']
                print(f"\n  {code} 2026Q1 growth_data (len={len(row)}):")
                for i, val in enumerate(row):
                    lbl = labels[i] if i < len(labels) else f'?'
                    print(f"    [{i}] {lbl:>14s} = {repr(val)}")
            else:
                print(f"\n  {code}: {rs.error_code} {rs.error_msg}")
            bs.logout()

    def test_integration_600519(self):
        """Integration: 600519 贵州茅台. Should return both rev and prof."""
        self._print_growth_row('600519')
        print()
        rev, prof, info = gpfenxi.get_q1_growth('600519')
        print(f"Result: revenue_growth={rev}%, profit_growth={prof}%")
        print(f"Debug: {info[:200]}")
        self.assertIsNotNone(rev, f"Revenue should be calculable. Debug: {info}")
        self.assertIsNotNone(prof, f"Profit should be calculable. Debug: {info}")

    def test_integration_300750(self):
        """Integration: 300750 宁德时代."""
        self._print_growth_row('300750')
        print()
        rev, prof, info = gpfenxi.get_q1_growth('300750')
        print(f"Result: revenue_growth={rev}%, profit_growth={prof}%")
        print(f"Debug: {info[:200]}")
        self.assertIsNotNone(rev, f"Revenue should be calculable. Debug: {info}")
        self.assertIsNotNone(prof, f"Profit should be calculable. Debug: {info}")

    def test_integration_603629(self):
        """Integration: 603629 利通电子 (white-listed stock)."""
        rev, prof, info = gpfenxi.get_q1_growth('603629')
        print(f"\n603629: rev={rev}%, prof={prof}%")
        print(f"  {info}")
        self.assertIsNotNone(rev)
        self.assertIsNotNone(prof)

    def test_integration_002266(self):
        """Integration: 002266 浙富控股 (white-listed stock)."""
        rev, prof, info = gpfenxi.get_q1_growth('002266')
        print(f"\n002266: rev={rev}%, prof={prof}%")
        print(f"  {info}")
        self.assertIsNotNone(rev)
        self.assertIsNotNone(prof)

    def test_integration_invalid_code(self):
        """Integration: Invalid stock code -> should return None gracefully."""
        rev, prof, info = gpfenxi.get_q1_growth('999999')
        self.assertIsNone(rev)
        self.assertIsNone(prof)
        print(f"\n--- Integration: 999999 ---")
        print(info)


if __name__ == '__main__':
    unittest.main()
