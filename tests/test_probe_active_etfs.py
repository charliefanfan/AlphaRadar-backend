import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

path = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_active_etfs.py'
if not path.exists():
    path = Path(__file__).with_name('probe_active_etfs.py')
spec = importlib.util.spec_from_file_location('probe_active_etfs', path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
TODAY = date(2026, 11, 16)


def fixture(shares=True, fractional=False, asof='As of 11/13/2026'):
    headers = ['Ticker', 'Security Name', 'Percent of Net Assets', 'Shares']
    rows = [[asof, '', '', ''], headers]
    rows += [[str(6000 + i), f'Company {i}', 0.125 if fractional else 12.5,
              100 + i if shares else '-'] for i in range(8)]
    return pd.DataFrame(rows)


class ProbeTests(unittest.TestCase):
    def test_numeric_foreign_tickers_and_actual_source_date(self):
        rows = probe.normalize(fixture(), 'CGGO', TODAY)
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]['date'], '2026-11-13')
        self.assertEqual(rows[0]['ticker'], '6000')
        self.assertEqual(sum(r['weight'] for r in rows), 100)

    def test_fractional_capital_weights(self):
        rows = probe.normalize(fixture(fractional=True), 'CGUS', TODAY)
        self.assertEqual(sum(r['weight'] for r in rows), 100)

    def test_missing_shares_stay_null(self):
        rows = probe.normalize(fixture(shares=False), 'CGUS', TODAY)
        self.assertTrue(all(r['shares'] is None for r in rows))

    def test_missing_source_date_rejected(self):
        with self.assertRaises(ValueError):
            probe.normalize(fixture(asof=''), 'CGUS', TODAY)

    def test_future_source_date_rejected(self):
        with self.assertRaises(ValueError):
            probe.normalize(fixture(asof='As of 11/17/2026'), 'CGUS', TODAY)

    def test_incomplete_weights_rejected(self):
        frame = fixture()
        frame.iloc[2:, 2] = 2
        with self.assertRaises(ValueError):
            probe.normalize(frame, 'CGUS', TODAY)

    def test_duplicate_ticker_rejected(self):
        frame = fixture()
        frame.iloc[3, 0] = frame.iloc[2, 0]
        with self.assertRaises(ValueError):
            probe.normalize(frame, 'CGUS', TODAY)

    def test_capital_accounting_cash_rows_are_not_stocks(self):
        frame = fixture(fractional=True)
        frame.loc[len(frame)] = ['', 'NET OTHER ASSETS', 0.0008, '-']
        frame.loc[len(frame)] = ['', 'US DOLLAR', 0.0001, '-']
        rows = probe.normalize(frame, 'CGGO', TODAY)
        self.assertEqual(len(rows), 8)
        self.assertFalse(any(r['company'] in {'NET OTHER ASSETS', 'US DOLLAR'} for r in rows))

    def test_unknown_material_tickerless_security_still_blocked(self):
        frame = fixture(fractional=True)
        frame.loc[len(frame)] = ['', 'UNKNOWN SECURITY', 0.1, 100]
        with self.assertRaises(ValueError):
            probe.normalize(frame, 'CGGO', TODAY)

    def test_no_official_domain_lookalikes(self):
        self.assertTrue(probe.allowed('https://am.jpmorgan.com/file.csv', 'jpmorgan.com'))
        self.assertFalse(probe.allowed('https://jpmorgan.com.example.net/file.csv', 'jpmorgan.com'))
        self.assertFalse(probe.allowed('http://am.jpmorgan.com/file.csv', 'jpmorgan.com'))

    def test_no_database_dependency_or_environment(self):
        tree = __import__('ast').parse(path.read_text())
        imports = [n.module or '' for n in __import__('ast').walk(tree) if isinstance(n, __import__('ast').ImportFrom)]
        self.assertFalse(any('supabase' in name for name in imports))
        self.assertNotIn('os.environ', path.read_text())


if __name__ == '__main__':
    unittest.main()
