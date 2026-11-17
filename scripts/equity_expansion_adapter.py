"""Validated equity adapters for eleven approved new funds; no database access."""
from __future__ import annotations
import csv
import math
import re
from datetime import datetime
from io import BytesIO, StringIO
from urllib.parse import urlparse, urljoin
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup

APPROVED_ETFS = ('AVUV', 'AVLV', 'CGCV', 'JEPI', 'JEPQ', 'JUSA', 'MFSG', 'MFSV', 'OAKM', 'PCLG', 'BCHP')
AVANTIS = {'AVUV': 'avantis-us-small-cap-value-etf', 'AVLV': 'avantis-us-large-cap-value-etf'}
JPM = {'JEPI': '46641Q332', 'JEPQ': '46654Q203', 'JUSA': '46654Q617'}
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
    if ticker not in APPROVED_ETFS:
        raise ValueError('Unapproved candidate: ' + ticker)
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
    elif ticker == 'OAKM':
        data = list(csv.DictReader(StringIO(content.decode('utf-8-sig'))))
        dates = {actual_date(r['as_of_date'], today) for r in data}
        if {r['etf_fund'] for r in data} != {ticker} or len(dates) != 1:
            raise ValueError('Oakmark CSV fund/date identity mismatch')
        d = dates.pop()
        records = [row(r['ticker'], r['issue_name'], r['weight'], r['shares_held'],
                       'CASH' if r['issue_name'].upper() in LEDGER_NAMES else 'EQUITY')
                   for r in data]
    else:
        raise ValueError('Unapproved candidate')
    return validate(ticker, records, d)


def source(ticker):
    if ticker not in APPROVED_ETFS:
        raise ValueError('Unapproved candidate: ' + ticker)
    if ticker in AVANTIS:
        return 'https://www.avantisinvestors.com/avantis-investments/en-us/' + AVANTIS[ticker] + '/' + ticker + '/'
    if ticker in JPM:
        return ('https://am.jpmorgan.com/FundsMarketingHandler/excel?type=dailyETFHoldings&cusip='
                + JPM[ticker] + '&country=us&role=adv&fundType=ETF&locale=en-US&isUnderlyingHolding=false&isProxyHolding=false')
    return {
        'CGCV': 'https://www.capitalgroup.com/api/investments/investment-service/v1/etfs/CGCV/download/daily-holdings?audience=advisor',
        'MFSG': 'https://www.mfs.com/en-us/individual-investor/product-strategies/exchange-traded-funds/daily-holdings/MFSG-active-growth-etf.html',
        'MFSV': 'https://www.mfs.com/en-us/individual-investor/product-strategies/exchange-traded-funds/daily-holdings/MFSV-active-value-etf.html',
        'OAKM': 'https://oakmark.com/wp-content/uploads/etf_data/oakm_holdings.csv',
        'PCLG': 'https://www.polencapital.com/etfs/focus-growth-etf-pclg',
        'BCHP': 'https://api.assetmgmt.principalam.com/public/files?key=BCHP.xlsx',
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



def fetch_equity_expansion(ticker):
    """Fetch one approved fund; keep actual issuer dates and original weights."""
    import requests
    url = source(ticker)
    with requests.Session() as session:
        session.headers['User-Agent'] = 'Mozilla/5.0 (AlphaRadar official holdings)'
        content = download(session, url)
    today = datetime.now(ZoneInfo('America/New_York')).date()
    records, audit = parse(ticker, content, today)
    print(f"  [{ticker}] {len(records)} equity holdings as of {audit['date']}; "
          f"{audit['excluded_rows']} non-equity rows excluded")
    return pd.DataFrame(records)
