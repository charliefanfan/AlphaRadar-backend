"""Candidate parsers: real dates, full weight audit, equity-only output; no database."""
from __future__ import annotations
import csv
import json
import math
import re
from datetime import datetime
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo

import pandas as pd

TEMA = {'WELD', 'CANC', 'HRTS', 'VOLT', 'TOLL', 'DISK', 'LAZR', 'HLTH'}
CAPITAL = {'CGXU', 'CGIE', 'CGCV', 'CGNG', 'CGBL'}
ISHARES = {'BGRO': '337538', 'BALI': '333207'}
JPM = {'JEPI': '46641Q332', 'JEPQ': '46654Q203', 'JPEF': '46654Q781', 'JPSV': '46654Q708'}
JANUS = {'JXX', 'JMID'}
TRP = {'TGRT':'growth-etf', 'TCAF':'capital-appreciation-equity-etf', 'TVAL':'value-etf'}


def clean(v):
    return '' if v is None or pd.isna(v) else re.sub(r'\s+', ' ', str(v)).strip()


def number(v):
    s = clean(v).replace(',', '').replace('%', '').replace('$', '')
    if s.startswith('(') and s.endswith(')'):
        s = '-'+s[1:-1]
    try:
        n = float(s)
    except ValueError:
        raise ValueError('Invalid numeric value: '+s)
    if not math.isfinite(n):
        raise ValueError('Nonfinite numeric value')
    return n


def actual_date(value, today):
    s = clean(value)
    m = re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]{3,9} \d{1,2}, \d{4}', s)
    if not m:
        raise ValueError('Explicit holdings date missing')
    d = pd.to_datetime(m.group(),errors='raise').date()
    if not 0 <= (today-d).days <= 7:
        raise ValueError('Stale or future holdings date: '+d.isoformat())
    return d.isoformat()


def finish(ticker, rows, dates, today):
    dates = {actual_date(d,today) for d in dates}
    if len(dates) != 1:
        raise ValueError('Mixed source dates')
    total = sum(r['weight'] for r in rows)
    if not 95 <= total <= 105 or len(rows) < 5:
        raise ValueError(f'Incomplete source: {len(rows)} rows, {total:.5f}%')
    result, excluded, seen = [], [], set()
    for r in rows:
        if r['kind'] != 'equity':
            excluded.append(r)
            continue
        symbol = r['ticker']
        parts = symbol.split()
        if len(parts)==2 and parts[-1] in {'US','UN','UQ','UW','UA','UP','UR'}:
            symbol = parts[0]
        if not symbol or symbol in {'-','--','NAN'} or symbol in seen:
            raise ValueError('Missing/duplicate stock identity: '+symbol)
        seen.add(symbol)
        if r['shares'] is None or r['shares'] < 0 or r['weight'] < 0:
            raise ValueError('Invalid equity quantities: '+symbol)
        result.append(dict(etf=ticker,ticker=symbol,company=r['company'],
                           weight=r['weight'],shares=r['shares'],date=next(iter(dates))))
    if len(result)<5:
        raise ValueError('Insufficient equity holdings')
    result.sort(key=lambda r: (-r['weight'],r['ticker']))
    return result, {'date': next(iter(dates)), 'source_rows':len(rows), 'equity_rows':len(result),
        'full_weight':round(total,6),'equity_weight':round(sum(r['weight'] for r in result),6),
        'excluded':excluded}


def row(symbol,name,weight,shares,kind,scale=1):
    return dict(ticker=clean(symbol).upper(),company=clean(name),weight=number(weight)*scale,
                shares=number(shares) if clean(shares) else None,kind=kind)


def parse(ticker,content,today=None):
    today = today or datetime.now(ZoneInfo('America/New_York')).date()
    rows, dates = [], set()
    if ticker in TRP:
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(content,'html.parser')
        canonical=soup.find('link',rel='canonical')
        if not canonical or not canonical.get('href','').split('?')[0].endswith('/'+TRP[ticker]+'.html'):
            raise ValueError('T. Rowe fund identity mismatch')
        components=[c for c in soup.select('[data-component-object]') if 'holding' in c.name]
        if len(components)!=1:
            raise ValueError('Full holdings component missing or ambiguous')
        data=json.loads(components[0]['data-component-object'])
        full=data.get('full')
        if not full or not full.get('holdings'):
            raise ValueError('No full actual holdings; proxy basket is not accepted')
        dates.add(full['effectiveDate'][:10])
        for r in full['holdings']:
            name=clean(r['name']).upper(); symbol=clean(r['tickerSymbol'])
            if name.startswith('CASH/CASH EQUIVALENT') or name in {'EURO CURRENCY','US DOLLAR','US DOLLARS'}:
                kind='cash'
            elif not symbol and (r['percentageTotalNetAssets']==0 or re.search(r'\bSERIES\b|\bCVT PFD\b',name)):
                kind='private_or_rights'
            elif r['investmentType']=='LT' and symbol and re.search(r'COMMON STOCK|\bADR\b|\bREIT\b|NY REG SH',name) and r['strikePrice']==0:
                kind='equity'
            else:
                raise ValueError('Unclassified T. Rowe holding: '+name)
            rows.append(row(symbol,r['name'],r['percentageTotalNetAssets'],r['shareQuantity'],kind))
    elif ticker in TEMA:
        data = list(csv.DictReader(StringIO(content.decode('utf-8-sig'))))
        for r in data:
            dates.add(r['holdings_date'])
            name = r['proper_name'].upper()
            if r['is_cash'] == '1':
                kind='cash'
            elif re.search(r'\bSPV\b|\bSWAP\b|\bTRS\b', name+' '+r['ticker']):
                kind='private_or_swap'
            elif r['is_cash']=='0' and r['sector'] and r['country']:
                kind='equity'
            else:
                raise ValueError('Unclassified Tema asset: '+name)
            rows.append(row(r['ticker'],r['proper_name'],r['percent_of_nav'],r['shares'],kind,100))
    elif ticker in CAPITAL:
        raw=pd.read_excel(BytesIO(content),sheet_name='Daily Fund Holdings',header=None,dtype=str)
        if ticker+' - ' not in ' '.join(clean(v) for v in raw.iloc[0]):
            raise ValueError('Capital fund identity mismatch')
        dates.add(next(clean(v) for v in raw.iloc[0] if 'As Of' in clean(v)))
        raw.columns=raw.iloc[2]
        for _,r in raw.iloc[3:].iterrows():
            kind=clean(r['Asset Type']).upper()
            name=clean(r['Security Name'])
            if not kind:
                if name.upper() in {'NET OTHER ASSETS','US DOLLAR'}:
                    kind='CASH & EQUIVALENT'
                else:
                    raise ValueError('Unclassified Capital row: '+name)
            if kind not in {'EQUITY','CASH & EQUIVALENT','FIXED INCOME','SPOT FX'}:
                raise ValueError('Unclassified Capital type: '+kind)
            rows.append(row(r['Ticker'],name,r['Percent of Net Assets'],r['Shares or Principal Amount'],
                            'equity' if kind=='EQUITY' else kind,100))
    elif ticker in JPM:
        raw=pd.read_excel(BytesIO(content),sheet_name='Holdings',header=None,dtype=str)
        identity=' '.join(clean(v) for v in raw.iloc[5])
        if JPM[ticker] not in identity:
            raise ValueError('JPMorgan fund identity mismatch')
        dates.add(identity)
        raw.columns=raw.iloc[7]
        for _,r in raw.iloc[8:].dropna(subset=['Security Type']).iterrows():
            kind=clean(r['Security Type']).upper()
            if kind in {'DOMESTIC COMMON STOCK','COMMON STOCK','ADR','REIT'}:
                kind='equity'
            elif kind not in {'MONEY MARKET','EQUITY LINKED NOTES','CASH','CURRENCIES','EQUITY INDEX FUTURES','RIGHTS','WARRANTS'}:
                raise ValueError('Unclassified JPMorgan type: '+kind)
            rows.append(row(r['Ticker'],r['Security Description'],r['% of Net Assets'],r['Shares/Par'],kind))
    elif ticker in ISHARES:
        data=list(csv.reader(StringIO(content.decode('utf-8-sig'))))
        if not data or ticker=='BGRO' and 'Large Cap Growth' not in data[0][0] or ticker=='BALI' and 'Premium Income' not in data[0][0]:
            raise ValueError('iShares fund identity mismatch')
        dates.add(next(r[1] for r in data if r and r[0]=='Fund Holdings as of'))
        idx=next(i for i,r in enumerate(data) if r and r[0]=='Ticker')
        headers=data[idx]
        for values in data[idx+1:]:
            if len(values)!=len(headers):
                if any(v.strip() for v in values):
                    # Issuer legal footer follows a blank separator.
                    break
                continue
            r=dict(zip(headers,values)); kind=r['Type'].upper()
            if kind=='EQUITY' and r['Asset Class']=='Equity':
                kind='equity'
            elif kind not in {'CASH','FUND','OPTION','FUTURE','FX','CASH COLLATERAL AND MARGINS'}:
                raise ValueError('Unclassified iShares type: '+kind)
            rows.append(row(r['Ticker'],r['Name'],r['Weight (%)'],r['Quantity'],kind))
    elif ticker in JANUS:
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(content,'html.parser')
        text=soup.get_text(' ',strip=True)
        if not soup.select_one('[data-product-ticker="'+ticker+'"]'):
            raise ValueError('Janus fund identity mismatch')
        m=re.search(r'As of ([A-Za-z]+ \d{1,2}, \d{4})',text,re.I)
        if not m:
            raise ValueError('Janus explicit date missing')
        dates.add(m.group(1))
        table=next(t for t in soup.find_all('table') if 'Quantity' in t.get_text() and 'Ticker' in t.get_text())
        trs=table.find_all('tr')
        headers=[c.get_text(' ',strip=True) for c in trs[0].find_all(['th','td'])]
        for tr in table.select('tbody tr'):
            values=[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'])]
            if not values:
                continue
            if len(values)!=len(headers):
                raise ValueError('Janus table shape changed')
            r=dict(zip(headers,values)); symbol=r['Ticker']
            qty=next(k for k in r if 'Quantity' in k)
            if symbol=='USD':
                kind='cash'
            elif re.fullmatch(r'[A-Z0-9./-]+ (US|UN|UQ|UW)',symbol) and r['Strike Price'] in {'-',''} and not r['Underlying Security']:
                kind='equity'
            else:
                raise ValueError('Janus stock identity/type needs review: '+symbol)
            rows.append(row(symbol,values[0],r['Weight %'],r[qty],kind))
    else:
        raise ValueError('No validated candidate parser: '+ticker)
    return finish(ticker,rows,dates,today)
