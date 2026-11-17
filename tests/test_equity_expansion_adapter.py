import ast
import importlib.util
import unittest
from datetime import date
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts' / 'equity_expansion_adapter.py'
spec = importlib.util.spec_from_file_location('expansion', path)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
TODAY = date(2026, 11, 17)


def portfolio():
    return [p.row('S' + str(i), 'Stock ' + str(i), 20, 100, 'EQUITY') for i in range(5)]


class ExpansionTests(unittest.TestCase):
    def test_exact_candidate_scope_excludes_existing_funds(self):
        self.assertEqual(len(p.APPROVED_ETFS), 11)
        self.assertEqual(len(set(p.APPROVED_ETFS)), 11)
        self.assertFalse(set(p.APPROVED_ETFS) & {'CGUS','CGGO','CGDV','CGGR','JGRO','JAVA','ARKK'})

    def test_no_database_dependency_or_production_import(self):
        s = path.read_text()
        tree = ast.parse(s)
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any(x in name for name in imports for x in ('supabase', 'fetch_holdings')))
        self.assertNotIn('os.environ', s)
        self.assertNotIn('SUPABASE_KEY', s)

    def test_source_dates_are_real(self):
        self.assertEqual(p.actual_date('11/16/26', TODAY), '2026-11-16')
        with self.assertRaises(ValueError):
            p.actual_date('11/18/2026', TODAY)
        with self.assertRaises(ValueError):
            p.actual_date('10/01/2026', TODAY)
        with self.assertRaises(ValueError):
            p.actual_date('', TODAY)

    def test_weight_and_shares_stay_original(self):
        r, a = p.validate('CGCV', portfolio(), '2026-11-16')
        self.assertEqual(r[0]['weight'], 20)
        self.assertEqual(r[0]['shares'], 100)
        self.assertEqual(a['full_weight_total'], 100)

    def test_cash_and_eln_are_audited_not_stocks(self):
        rows = portfolio()
        rows[0]['weight'] = 15
        rows.extend([p.row('', 'SPX_25', 4, 100, 'Equity Linked Notes'),
                     p.row('GVMXX', 'Cash vehicle', 1, 50, 'SWEEP INVESTMENT VEHICLE')])
        eq, audit = p.validate('JEPI', rows, '2026-11-16')
        self.assertEqual(len(eq), 5)
        self.assertEqual(audit['excluded_rows'], 2)
        self.assertEqual(audit['equity_weight_total'], 95)
        self.assertEqual(eq[0]['weight'], 20)  # No renormalization to 100.

    def test_incomplete_source_rejected(self):
        with self.assertRaises(ValueError):
            p.validate('CGCV', portfolio()[:4], '2026-11-16')

    def test_duplicate_equity_ticker_rejected(self):
        rows = portfolio()
        rows[1]['ticker'] = rows[0]['ticker']
        with self.assertRaises(ValueError):
            p.validate('CGCV', rows, '2026-11-16')

    def test_numeric_foreign_ticker_preserved(self):
        rows = portfolio()
        rows[0]['ticker'] = '6000'
        eq, _ = p.validate('CGCV', rows, '2026-11-16')
        self.assertIn('6000', [r['ticker'] for r in eq])

    def test_missing_equity_identity_or_shares_rejected(self):
        for key, value in [('ticker', ''), ('shares', None), ('shares', -1)]:
            rows = portfolio()
            rows[0][key] = value
            with self.assertRaises(ValueError):
                p.validate('CGCV', rows, '2026-11-16')

    def test_unknown_asset_type_rejected(self):
        rows = portfolio()
        rows[0]['asset_type'] = 'UNKNOWN SECURITY'
        with self.assertRaises(ValueError):
            p.validate('CGCV', rows, '2026-11-16')

    def test_tchp_proxy_never_accepted_as_actual(self):
        with self.assertRaisesRegex(ValueError, 'Unapproved candidate'):
            p.parse('TCHP', b'proxy portfolio', TODAY)

    def test_cross_host_redirect_blocked(self):
        class Response:
            is_redirect = True
            headers = {'Location': 'https://evil.example/holdings.xlsx'}
        class Session:
            def get(self, *args, **kwargs):
                return Response()
        with self.assertRaisesRegex(ValueError, 'verified issuer host'):
            p.download(Session(), 'https://oakmark.com/holdings.csv')

    def test_only_approved_funds_can_fetch(self):
        for ticker in ('AVUS', 'LSGR', 'BUSA', 'TCHP', 'DFAC', 'CGUS', 'CGGR'):
            with self.assertRaisesRegex(ValueError, 'Unapproved candidate'):
                p.source(ticker)

    def test_http_source_blocked(self):
        with self.assertRaises(ValueError):
            p.download(None, 'http://oakmark.com/holdings.csv')

    def test_nan_cannot_pass_weight_validation(self):
        with self.assertRaises(ValueError):
            p.row('ABC', 'Company', 'NaN', 100, 'EQUITY')

if __name__ == '__main__':
    unittest.main()
