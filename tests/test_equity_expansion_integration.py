"""Exercise production run orchestration without network or database imports."""
import ast
import contextlib
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('expansion', ROOT/'scripts/equity_expansion_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class IntegrationTests(unittest.TestCase):
    def test_new_fund_failures_preserve_existing_etfs_and_signals(self):
        tree = ast.parse((ROOT/'scripts/fetch_holdings.py').read_text())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        calls = []
        def fetch(ticker, *args):
            calls.append(('fetch', ticker))
            return object()
        def new_fetch(ticker):
            calls.append(('new_fetch', ticker))
            if ticker != 'BCHP':
                raise ValueError('simulated new source failure')
            return object()
        def save(ticker, frame):
            calls.append(('save', ticker))
            if ticker == 'BCHP':
                raise RuntimeError('simulated new database failure')
            return 'unchanged'
        module = types.ModuleType('equity_expansion_adapter')
        module.APPROVED_ETFS = adapter.APPROVED_ETFS
        module.fetch_equity_expansion = new_fetch
        env = dict(TODAY='2026-11-17', ARK_ETFS={'ARKK':'url'}, ARKQ_URLS=['url'],
            TEMA_ETFS={'NASA':'url'}, ISHARES_ETFS={'TEK':{'product_id':123}},
            ADDITIONAL_ETFS={t:'issuer' for t in ('CGUS','CGGO','CGGR','CGDV','JGRO','JAVA')},
            fetch_ark=fetch, fetch_ark_with_fallback=fetch, fetch_tema=fetch,
            fetch_ishares=fetch, fetch_additional=fetch, save_etf=save,
            time=types.SimpleNamespace(sleep=lambda n:None),
            generate_multi_etf_signals=lambda:calls.append(('signals',None)))
        exec(compile(ast.Module(body=[run], type_ignores=[]), 'run', 'exec'), env)
        with patch.dict(sys.modules, {'equity_expansion_adapter':module}):
            with contextlib.redirect_stdout(io.StringIO()):
                env['run']()
        original = ('ARKK','ARKQ','NASA','TEK','CGUS','CGGO','CGGR','CGDV','JGRO','JAVA')
        self.assertEqual([c for c in calls if c[0]=='fetch'], [('fetch',t) for t in original])
        self.assertEqual([c for c in calls if c[0]=='save' and c[1] in original], [('save',t) for t in original])
        self.assertEqual([t for kind,t in calls if kind=='new_fetch'], list(adapter.APPROVED_ETFS))
        self.assertEqual(calls[-1], ('signals',None))
        self.assertLess(calls.index(('save','JAVA')), calls.index(('new_fetch','AVUV')))

if __name__ == '__main__':
    unittest.main()
