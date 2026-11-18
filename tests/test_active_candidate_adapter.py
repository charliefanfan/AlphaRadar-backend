import csv
import sys
import unittest
from datetime import date
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from active_candidate_adapter import parse


class CandidateParserTests(unittest.TestCase):
    today=date(2026,11,18)

    def tema(self,mutate=lambda r: None):
        rows=[dict(holdings_date='2026-11-17',ticker='STK'+str(i),cusip='',proper_name='Stock '+str(i),
            shares='100',market_value='1000',percent_of_nav='.18',is_cash='0',country='United States',sector='Technology') for i in range(5)]
        rows.append(dict(holdings_date='2026-11-17',ticker='',cusip='',proper_name='CASH & CASH EQUIVALENTS',
            shares='',market_value='100',percent_of_nav='.1',is_cash='1',country='',sector=''))
        mutate(rows)
        out=StringIO(); w=csv.DictWriter(out,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
        return out.getvalue().encode()

    def test_fractional_weights_and_cash(self):
        records,audit=parse('VOLT',self.tema(),self.today)
        self.assertEqual(len(records),5)
        self.assertAlmostEqual(audit['full_weight'],100)
        self.assertAlmostEqual(audit['equity_weight'],90)
        self.assertEqual(records[0]['weight'],18)
        self.assertEqual(records[0]['date'],'2026-11-17')

    def test_stale_date_fails_instead_of_using_today(self):
        data=self.tema(lambda rs:[r.update(holdings_date='2025-08-07') for r in rs])
        with self.assertRaisesRegex(ValueError,'Stale'):
            parse('VOLT',data,self.today)

    def test_partial_portfolio_rejected(self):
        data=self.tema(lambda rs:rs.pop(0))
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            parse('VOLT',data,self.today)

    def test_duplicate_symbol_rejected(self):
        data=self.tema(lambda rs:rs[1].update(ticker=rs[0]['ticker']))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            parse('VOLT',data,self.today)

    def test_spv_excluded_and_original_weights_preserved(self):
        def change(rs):
            rs.insert(0,dict(rs[-1],ticker='PRIVATE SPV',proper_name='PRIVATE SPV EXPOSURE',
                             is_cash='0',shares='10',percent_of_nav='.05'))
            rs[-1]['percent_of_nav']='.05'
        records,audit=parse('VOLT',self.tema(change),self.today)
        self.assertEqual(len(records),5)
        self.assertEqual({r['kind'] for r in audit['excluded']},{'cash','private_or_swap'})
        self.assertEqual(records[0]['weight'],18)

    def test_unknown_instrument_rejected(self):
        data=self.tema(lambda rs:rs[0].update(sector='',country=''))
        with self.assertRaisesRegex(ValueError,'Unclassified'):
            parse('VOLT',data,self.today)

    def test_proxy_candidate_has_no_parser(self):
        for ticker in ['FBCG','FBCV','FMAG','TCHP','TEQI','LUX','RSHO']:
            with self.subTest(ticker=ticker),self.assertRaisesRegex(ValueError,'No validated'):
                parse(ticker,b'',self.today)

    def test_balanced_fund_keeps_stock_weights_and_excludes_bonds(self):
        rows=[['Holdings for ETF','CGBL - Capital Group Core Balanced ETF','','','','As Of 11/17/2026'],
              ['','','','','',''],
              ['Security Name','Ticker','Asset Type','Shares or Principal Amount','Market Value','Percent of Net Assets']]
        rows += [['Stock '+str(i),'STK'+str(i),'Equity',100,1000,.12] for i in range(5)]
        rows += [['Bond ETF','BOND','Fixed Income',100,1000,.4]]
        out=BytesIO()
        with pd.ExcelWriter(out,engine='openpyxl') as writer:
            pd.DataFrame(rows).to_excel(writer,sheet_name='Daily Fund Holdings',header=False,index=False)
        records,audit=parse('CGBL',out.getvalue(),self.today)
        self.assertEqual(len(records),5)
        self.assertEqual(audit['equity_weight'],60)
        self.assertEqual(records[0]['weight'],12)


if __name__=='__main__':
    unittest.main()
