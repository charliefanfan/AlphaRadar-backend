"""Isolated read-only probe for 20 ETF candidates. Never imports production ETL or a DB client."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import urlparse, urljoin
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

AVANTIS = {
    'AVUV': 'avantis-us-small-cap-value-etf',
    'AVUS': 'avantis-us-equity-etf',
    'AVLV': 'avantis-us-large-cap-value-etf',
}
DIMENSIONAL = {
    'DFAC': 'us-core-equity-2-etf', 'DFAU': 'us-core-equity-market-etf',
    'DCOR': 'us-core-equity-1-etf', 'DUHP': 'us-high-profitability-etf',
    'DFLV': 'us-large-cap-value-etf',
}
JPM = {'JEPI': '46641Q332', 'JEPQ': '46654Q203', 'JUSA': '46654Q617'}
CANDIDATES = tuple(DIMENSIONAL) + tuple(AVANTIS) + ('CGCV',) + tuple(JPM) + (
    'BUSA', 'MFSG', 'MFSV', 'LSGR', 'OAKM', 'PCLG', 'BCHP', 'TCHP')
EQUITY_TYPES = {
    'EQUITY', 'COMMON STOCK', 'DOMESTIC COMMON STOCK', 'ADR', 'REIT',
    'S', 'FS', 'CS(COMMON STOCK)', 'S(COMMON STOCK)', 'FS(FOREIGN STOCK)',
}
NON_EQUITY_TYPES = {
    'CASH', 'CASH & EQUIVALENT', 'CURRENCIES', 'MONEY MARKET',
    'EQUITY LINKED NOTES', 'EQUITY INDEX FUTURES', 'RIGHTS', 'WARRANTS',
    'NCA', 'MM', 'MONEY MARKET FUND', 'INVESTMENT COMPANY', 'SWEEP INVESTMENT VEHICLE',
}
LEDGER_NAMES = {'US DOLLAR', 'NET OTHER ASSETS', 'NET CURRENT ASSETS',
                'CASH', 'CASH & CASH EQUIVALENTS'}


def text(value):
    if value is None or pd.isna(value):
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def number(value):
    s = text(value).replace(',', '').replace('$', '').replace('%', '')
    if s in {'', '-', '--'}:
        return None
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        n = float(s)
        return n if math.isfinite(n) else None
    except ValueError:
        return None


def actual_date(value, today):
    s = text(value)
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%m-%d-%y'):
        try:
            d = datetime.strptime(s, fmt).date()
            if not 0 <= (today - d).days <= 14:
                raise ValueError('Source date is future or stale: ' + s)
            return d.isoformat()
        except ValueError as exc:
            if 'Source date' in str(exc):
                raise
    raise ValueError('Missing or unrecognized explicit source date: ' + s)


def preamble_date(frame, today):
    found = set()
    for row in frame.head(8).values:
        for cell in row:
            s = text(cell)
            if re.search(r'as of', s, re.I):
                m = re.search(r'\d{1,2}/\d{1,2}/\d{4}', s)
                if m:
                    found.add(actual_date(m.group(), today))
    if len(found) != 1:
        raise ValueError('Expected exactly one explicit as-of date')
    return found.pop()


def row(symbol, company, weight, shares, kind, scale=1):
    w = number(weight)
    if w is None:
        raise ValueError('Invalid weight for ' + text(company))
    return dict(ticker=text(symbol).upper(), company=text(company),
                weight=w * scale, shares=number(shares), asset_type=text(kind).upper())


def validate(ticker, records, source_date, raw_count=None):
    if len(records) < 5:
        raise ValueError('Incomplete source table')
    total = sum(r['weight'] for r in records)
    if not 95 <= total <= 105:
        raise ValueError(f'Full-source weight coverage is unsafe: {total:.5f}%')
    equities, excluded, seen = [], [], set()
    for r in records:
        kind = r['asset_type']
        ledger = r['company'].upper() in LEDGER_NAMES
        if ledger or kind in NON_EQUITY_TYPES:
            excluded.append(r)
            continue
        if kind not in EQUITY_TYPES:
            raise ValueError('Unknown asset classification: ' + kind + ' / ' + r['company'])
        symbol = r['ticker']
        parts = symbol.split()
        if len(parts) == 2 and parts[-1] in {'US', 'UN', 'UQ', 'UW', 'UR', 'UA', 'UP'}:
            symbol = parts[0]
        if not symbol or symbol in {'NAN', '-', '--'}:
            raise ValueError('Equity has no tradable ticker: ' + r['company'])
        if symbol in seen:
            raise ValueError('Duplicate equity ticker: ' + symbol)
        seen.add(symbol)
        if r['shares'] is None or r['shares'] < 0 or r['weight'] < 0:
            raise ValueError('Invalid equity shares/weight: ' + symbol)
        equities.append(dict(etf=ticker, ticker=symbol, company=r['company'],
                             weight=r['weight'], shares=r['shares'], date=source_date))
    if len(equities) < 5:
        raise ValueError('No complete equity portfolio')
    equities.sort(key=lambda r: (-r['weight'], r['ticker']))
    return equities, dict(date=source_date, source_rows=raw_count or len(records),
        rows=len(equities), with_shares=len(equities), full_weight_total=round(total, 6),
        equity_weight_total=round(sum(r['weight'] for r in equities), 6),
        excluded_rows=len(excluded), excluded=excluded)


def parse(ticker, content, today):
    if ticker in AVANTIS:
        # Parse inert JSON5 data, never execute JavaScript from the issuer.
        import json5
        s = content.decode('utf-8')
        identity = re.search(r'a.ticker="([^"]+)"', s)
        if not identity or identity.group(1) != ticker:
            raise ValueError('Issuer page fund identity mismatch')
        match = re.search(r'a.portfolio=(.*?);a\.', s)
        if not match:
            raise ValueError('Full ETF holdings data absent from issuer page')
        p = json5.loads(match.group(1))
        d = actual_date(p['etfHoldingsAsOfDate'], today)
        records = [row(r['ticker'], r['name'], r['weight'], r['shareQuantity'],
                       r['securityType'] or ('CASH' if r['name'] == 'US DOLLAR' else ''))
                   for r in p['etfHoldings']]
    elif ticker in JPM:
        frame = pd.read_excel(BytesIO(content), sheet_name='Holdings', header=None)
        if JPM[ticker] not in ' '.join(text(v) for v in frame.iloc[5]):
            raise ValueError('JPMorgan workbook fund identity mismatch')
        d = preamble_date(frame, today)
        frame.columns = frame.iloc[7]
        frame = frame.iloc[8:].dropna(subset=['Security Type'])
        records = [row(r['Ticker'], r['Security Description'], r['% of Net Assets'],
                       r['Shares/Par'], r['Security Type']) for _, r in frame.iterrows()]
    elif ticker in {'CGCV', 'BCHP'}:
        name = 'Daily Fund Holdings' if ticker == 'CGCV' else 'Content'
        f = pd.read_excel(BytesIO(content), sheet_name=name, header=None)
        if ticker == 'CGCV' and 'CGCV' not in ' '.join(text(v) for v in f.iloc[0]):
            raise ValueError('Capital Group workbook identity mismatch')
        d = preamble_date(f, today)
        f.columns = f.iloc[2]
        f = f.iloc[3:]
        kind, company, weight, shares = (
            ('Asset Type', 'Security Name', 'Percent of Net Assets', 'Shares or Principal Amount')
            if ticker == 'CGCV' else
            ('Security Type', 'Description', '% of Net Assets', 'Par Value/Quantity/Notional'))
        f = f.dropna(subset=[kind])
        records = [row(r['Ticker'], r[company], r[weight], r[shares], r[kind], 100)
                   for _, r in f.iterrows()]
    elif ticker in {'MFSG', 'MFSV'}:
        soup = BeautifulSoup(content, 'html.parser')
        table = soup.find('table', {'data-daily-holdings-securitiesdate': True})
        if not table:
            raise ValueError('Daily holdings table absent')
        if not soup.find('a', href=re.compile('/' + ticker + '-')):
            raise ValueError('MFS daily page fund identity mismatch')
        d = actual_date(table['data-daily-holdings-securitiesdate'], today)
        records = []
        for tr in table.select('tbody tr'):
            cells = [c.get_text(' ', strip=True) for c in tr.find_all('td')]
            if len(cells) != 8:
                raise ValueError('MFS table shape changed')
            # CASH is the subtotal; SWEEP/CASHEUR are its detail, never double count.
            if cells[1] == 'CASH' and cells[0] != 'CASH':
                continue
            kind = 'CASH' if cells[1] == 'CASH' else 'EQUITY'
            records.append(row(cells[1], cells[2], cells[5], cells[3], kind))
    elif ticker == 'PCLG':
        soup = BeautifulSoup(content, 'html.parser')
        template = soup.find('template', id='pclg-holdings-csv-data')
        if not template:
            raise ValueError('Full holdings CSV template absent')
        d = actual_date(template['data-as-of'], today)
        records = []
        for tr in template.select('tbody tr'):
            c = [text(td.string) for td in tr.find_all('td')]
            if len(c) != 8:
                raise ValueError('Polen full holdings shape changed')
            records.append(row(c[1], c[0], c[5], c[3], c[2]))
    elif ticker in {'OAKM', 'LSGR'}:
        s = content.decode('utf-8-sig')
        if ticker == 'OAKM':
            data = list(csv.DictReader(StringIO(s)))
            dates = {actual_date(r['as_of_date'], today) for r in data}
            if {r['etf_fund'] for r in data} != {ticker}:
                raise ValueError('Oakmark CSV identity mismatch')
            records = [row(r['ticker'], r['issue_name'], r['weight'], r['shares_held'],
                           'CASH' if r['issue_name'].upper() in LEDGER_NAMES else 'EQUITY')
                       for r in data]
        else:
            lines = s.splitlines()
            if 'Ticker: LSGR' not in lines:
                raise ValueError('Natixis CSV identity mismatch')
            date_line = next(x for x in lines if x.startswith('As Of Date: '))
            dates = {actual_date(date_line.split(': ', 1)[1], today)}
            start = next(i for i, x in enumerate(lines) if x.startswith('Ticker,CUSIP,'))
            data = list(csv.DictReader(StringIO('\n'.join([lines[start]] + lines[start+2:]))))
            records = [row(r['Ticker'], r['Security name'], r['Percent of net assets'],
                           r['Quantity held'], 'CASH' if r['Security name'].upper() in LEDGER_NAMES else 'EQUITY')
                       for r in data if r.get('Security name')]
        if len(dates) != 1:
            raise ValueError('Mixed CSV source dates')
        d = dates.pop()
    elif ticker == 'BUSA':
        data = [r for r in csv.DictReader(StringIO(content.decode('utf-8-sig')))
                if r['Basket Ticker'] == 'BUSA.P']
        if not data:
            raise ValueError('BUSA portfolio basket absent')
        dates = {actual_date(r['Basket Evaluation Date'], today) for r in data}
        if len(dates) != 1:
            raise ValueError('Mixed BUSA evaluation dates')
        d = dates.pop()
        records = [row(r['Ticker'], r['Security Description'], r['Calculated Weight - Base'],
                       r['Benchmark Quantity'], r['Fund Accounting Asset Group Code'], 100)
                   for r in data]
        # The file is basket data; validation does not promote it to actual holdings.
        return validate(ticker, records, d)
    elif ticker in DIMENSIONAL:
        raise ValueError('Official page retrieved, but no verified full daily holdings endpoint/table yet')
    elif ticker == 'TCHP':
        raise ValueError('Semi-transparent ETF: daily proxy portfolio is not actual holdings; quarterly actual holdings are unsuitable for daily signals')
    else:
        raise ValueError('Unapproved candidate')
    return validate(ticker, records, d)


def source(ticker):
    if ticker in AVANTIS:
        return 'https://www.avantisinvestors.com/avantis-investments/en-us/' + AVANTIS[ticker] + '/' + ticker + '/'
    if ticker in DIMENSIONAL:
        return 'https://www.dimensional.com/us-en/funds/' + ticker.lower() + '/' + DIMENSIONAL[ticker]
    if ticker in JPM:
        return ('https://am.jpmorgan.com/FundsMarketingHandler/excel?type=dailyETFHoldings&cusip='
                + JPM[ticker] + '&country=us&role=adv&fundType=ETF&locale=en-US&isUnderlyingHolding=false&isProxyHolding=false')
    return {
        'CGCV': 'https://www.capitalgroup.com/api/investments/investment-service/v1/etfs/CGCV/download/daily-holdings?audience=advisor',
        'BUSA': 'https://etfs.brandes.com/assets/data/6c11_Report.csv',
        'MFSG': 'https://www.mfs.com/en-us/individual-investor/product-strategies/exchange-traded-funds/daily-holdings/MFSG-active-growth-etf.html',
        'MFSV': 'https://www.mfs.com/en-us/individual-investor/product-strategies/exchange-traded-funds/daily-holdings/MFSV-active-value-etf.html',
        'LSGR': 'https://mkt.im.natixis.com/files/etfs/LSGR_daily_full_holdings.csv',
        'OAKM': 'https://oakmark.com/wp-content/uploads/etf_data/oakm_holdings.csv',
        'PCLG': 'https://www.polencapital.com/etfs/focus-growth-etf-pclg',
        'BCHP': 'https://api.assetmgmt.principalam.com/public/files?key=BCHP.xlsx',
        'TCHP': 'https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/blue-chip-growth-etf.html',
    }[ticker]


def download(session, url):
    host = urlparse(url).hostname
    for _ in range(6):
        if urlparse(url).scheme != 'https' or urlparse(url).hostname != host:
            raise ValueError('Download redirected outside exact verified issuer host')
        r = session.get(url, timeout=35, allow_redirects=False)
        if r.is_redirect:
            url = urljoin(url, r.headers['Location'])
            continue
        r.raise_for_status()
        return r.content
    raise ValueError('Too many redirects')


def main():
    import requests
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/equity-expansion')
    parser.add_argument('--etfs', nargs='+', choices=CANDIDATES, default=CANDIDATES)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (AlphaRadar read-only source verification)'
    today = datetime.now(ZoneInfo('America/New_York')).date()
    report = []
    for ticker in args.etfs:
        url = source(ticker)
        result = {'etf': ticker, 'source': url}
        try:
            content = download(session, url)
            (out / (ticker + '.source')).write_bytes(content)
            result['source_sha256'] = hashlib.sha256(content).hexdigest()
            records, audit = parse(ticker, content, today)
            result.update(audit)
            result['status'] = 'needs_review' if ticker == 'BUSA' else 'validated_equities'
            if ticker == 'BUSA':
                result['reason'] = 'Official portfolio basket uses benchmark quantities; reconcile with actual full holdings before promotion'
            (out / (ticker + '.json')).write_text(json.dumps(records, indent=2, allow_nan=False))
        except Exception as exc:
            result.update(status='blocked', reason=str(exc))
        report.append(result)
        print(json.dumps({k:v for k,v in result.items() if k != 'excluded'}), flush=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print('Read-only: no database credentials, imports, writes, production ETL or schedule changes.')


if __name__ == '__main__':
    main()
