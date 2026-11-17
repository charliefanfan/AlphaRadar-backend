import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[1] / 'scripts'
if not root.exists():
    root = Path(__file__).parent
sys.path.insert(0, str(root))
import import_candidate_etfs as adapter


def record(etf):
    return {'etf': etf, 'ticker': 'AAPL', 'company': 'APPLE', 'weight': 5.0,
            'shares': 100.0, 'date': '2026-11-13'}


class ImportTests(unittest.TestCase):
    def test_can_only_save_new_candidate_symbols(self):
        calls = []
        backend = SimpleNamespace(ARK_ETFS={'ARKK': 'url'}, TEMA_ETFS={}, ISHARES_ETFS={},
                                  ADDITIONAL_ETFS={'CGGR': 'capital'},
                                  save_etf=lambda ticker, frame: calls.append((ticker, frame.iloc[0]['date'])) or 'saved')
        result = adapter.write_new_funds({'CGUS': [record('CGUS')], 'CGGO': [record('CGGO')]}, backend)
        self.assertEqual(result, {'CGUS': 'saved', 'CGGO': 'saved'})
        self.assertEqual(calls, [('CGUS', '2026-11-13'), ('CGGO', '2026-11-13')])

    def test_existing_etf_cannot_be_written(self):
        with patch.object(adapter.importlib, 'import_module') as db_import:
            with self.assertRaises(ValueError):
                adapter.write_new_funds({'ARKK': [record('ARKK')]})
            db_import.assert_not_called()

    def test_existing_registration_cannot_be_overwritten(self):
        backend = SimpleNamespace(ADDITIONAL_ETFS={'CGUS': 'capital'}, save_etf=lambda *_: self.fail('write attempted'))
        with self.assertRaises(ValueError):
            adapter.write_new_funds({'CGUS': [record('CGUS')]}, backend)

    def test_identity_mismatch_before_any_database_import(self):
        with patch.object(adapter.importlib, 'import_module') as db_import:
            with self.assertRaises(ValueError):
                adapter.write_new_funds({'CGUS': [record('CGGO')]})
            db_import.assert_not_called()

    def test_failed_source_does_not_import_database_client(self):
        with patch.object(adapter, 'fetch', side_effect=ValueError('source unavailable')):
            with patch.object(adapter.importlib, 'import_module') as db_import:
                with self.assertRaises(ValueError):
                    adapter.collect(['CGUS', 'CGGO'], None, date(2026, 11, 16))
                db_import.assert_not_called()


if __name__ == '__main__':
    unittest.main()
