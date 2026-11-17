"""Read-only onboarding probe. No Supabase import, credentials, or writes.

Existing scripts/fetch_holdings.py and scheduled workflows are intentionally
untouched. Validated snapshots go to local JSON artifacts for review only.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import date, datetime
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import pandas as pd

SPECS = {
    'CGUS': ('capitalgroup.com', 'https://www.capitalgroup.com/api/investments/investment-service/v1/etfs/CGUS/download/daily-holdings?audience=advisor'),
    'CGGO': ('capitalgroup.com', 'https://www.capitalgroup.com/api/investments/investment-service/v1/etfs/CGGO/download/daily-holdings?audience=advisor'),
    'DIVO': ('amplifyetfs.com', 'https://amplifyetfs.com/DIVO-holdings/'),
    'JEPI': ('jpmorgan.com', 'https://am.jpmorgan.com/us/en/asset-management/adv/products/jpmorgan-equity-premium-income-etf-46641q332/'),
    'JEPQ': ('jpmorgan.com', 'https://am.jpmorgan.com/us/en/asset-management/adv/products/jpmorgan-nasdaq-equity-premium-income-etf-46654q203/'),
    'DFAC': ('dimensional.com', 'https://www.dimensional.com/us-en/funds/dfac/us-core-equity-2-etf'),
}
ALIASES = {
    'ticker': {'ticker', 'symbol', 'security ticker', 'holding ticker'},
    'company': {'name', 'company', 'security name', 'security description', 'holding', 'description'},
    'weight': {'weight', 'weight (%)', 'weight %', 'portfolio weight', 'percent of net assets', '% of net assets', '% of assets', 'percent of assets', 'market value (%)', 'market value %'},
    'shares': {'shares', 'quantity', 'units', 'shares held', 'number of shares', 'shares or principal amount', 'shares/principal amount', 'shares / principal amount', 'shares / par', 'shares/par'},
    'date': {'date', 'as of date', 'holdings date', 'holdings_date'},
}
DATE_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}')


def clean_text(value):
    if value is None or pd.isna(value):
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def number(value):
    s = clean_text(value)
    if s.lower() in {'', '-', '--', 'nan', 'n/a', 'none'}:
        return None
    s = s.replace(',', '').replace('$', '').replace('%', '')
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        result = float(s)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def source_date(value, today):
    if isinstance(value, (date, datetime, pd.Timestamp)):
        result = value.date() if isinstance(value, datetime) else value
    else:
        match = DATE_PATTERN.search(clean_text(value))
        if not match:
            return None
        parsed = pd.to_datetime(match.group(), errors='coerce')
        if pd.isna(parsed):
            return None
        result = parsed.date()
    if not 0 <= (today - result).days <= 14:
        return None
    return result.isoformat()


def normalize(frame, ticker, today, context_date=None):
    """Require a full issuer table and a real as-of date. Never invent history."""
    for header_index in range(min(80, len(frame))):
        headers = [clean_text(v).lower() for v in frame.iloc[header_index]]
        mapping = {name: next((i for i, h in enumerate(headers) if h in choices), None)
                   for name, choices in ALIASES.items()}
        if any(mapping[k] is None for k in ('ticker', 'company', 'weight')):
            continue
        dates = set()
        # Prefer explicitly labelled issuer dates in the file's preamble.
        for _, row in frame.iloc[:header_index].iterrows():
            cells = [clean_text(v) for v in row]
            for i, cell in enumerate(cells):
                if 'as of' in cell.lower() or 'holdings date' in cell.lower():
                    for value in cells[i:i + 3]:
                        parsed = source_date(value, today)
                        if parsed:
                            dates.add(parsed)
        records = []
        missing_ticker_weight = 0.0
        missing_ticker_examples = []
        invalid_weight_rows = 0
        for values in frame.iloc[header_index + 1:].itertuples(index=False, name=None):
            symbol = clean_text(values[mapping['ticker']]).upper()
            company = clean_text(values[mapping['company']])
            if symbol.lower() in {'ticker', 'symbol', 'total', 'totals', 'grand total'} or company.lower() in {'total', 'totals', 'grand total'}:
                continue
            weight = number(values[mapping['weight']])
            if weight is None:
                if symbol and company and re.fullmatch(r'[A-Z0-9./ -]{1,24}', symbol):
                    invalid_weight_rows += 1
                continue
            if weight == 0:
                continue
            if not symbol or symbol in {'NAN', '-', '--'}:
                missing_ticker_weight += abs(weight)
                missing_ticker_examples.append({'name': company, 'weight': weight})
                continue
            if mapping['date'] is not None:
                parsed = source_date(values[mapping['date']], today)
                if parsed:
                    dates.add(parsed)
            shares = number(values[mapping['shares']]) if mapping['shares'] is not None else None
            # Keep foreign numeric tickers; do not treat them as invalid equities.
            if symbol.endswith('.0') and symbol[:-2].isdigit():
                symbol = symbol[:-2]
            parts = symbol.split()
            if len(parts) == 2 and parts[-1] in {'UN', 'UQ', 'UW', 'UR', 'UA', 'UP', 'US'}:
                symbol = parts[0]
            records.append({'etf': ticker, 'ticker': symbol, 'company': company,
                            'weight': weight, 'shares': shares})
        if not dates and context_date:
            dates.add(context_date)
        if len(dates) != 1:
            raise ValueError(f'Expected one explicit holdings date, got {sorted(dates)}')
        if len(records) < 5 or invalid_weight_rows:
            raise ValueError(f'Incomplete table: {len(records)} rows, {invalid_weight_rows} invalid weights')
        total = sum(r['weight'] for r in records)
        scale = 100 if ticker in {'CGUS', 'CGGO'} and 0.70 <= total <= 1.30 else 1
        if missing_ticker_weight * scale > 0.05:
            raise ValueError(f'Material holdings have no ticker: {missing_ticker_examples[:8]}')
        if not 95 <= total * scale <= 105:
            raise ValueError(f'Unsafe/incomplete weight coverage: {total * scale:.4f}%')
        seen = set()
        for record in records:
            if record['ticker'] in seen:
                raise ValueError(f'Duplicate ticker needs review: {record["ticker"]}')
            seen.add(record['ticker'])
            record['weight'] *= scale
            record['date'] = next(iter(dates))
        return sorted(records, key=lambda r: (-r['weight'], r['ticker']))
    raise ValueError('No complete ticker/name/weight table found')


def parse_file(content, ticker, today):
    if content.startswith(b'PK'):
        frames = pd.read_excel(BytesIO(content), sheet_name=None, header=None, dtype=object)
    else:
        sample = content[:500].lower()
        if b'<html' in sample or b'<!doctype' in sample:
            raise ValueError('HTML received instead of holdings file')
        rows = list(csv.reader(StringIO(content.decode('utf-8-sig'))))
        width = max((len(r) for r in rows), default=0)
        frames = {'csv': pd.DataFrame([r + [''] * (width - len(r)) for r in rows])}
    errors = []
    for frame in frames.values():
        try:
            return normalize(frame, ticker, today)
        except ValueError as exc:
            errors.append(str(exc))
    raise ValueError('; '.join(errors))


def allowed(url, domain):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and (host == domain or host.endswith('.' + domain))


def get(session, url, domain):
    # Validate every redirect rather than silently requesting a third-party host.
    for _ in range(6):
        if not allowed(url, domain):
            raise ValueError('Download left the verified issuer domain')
        response = session.get(url, timeout=30, allow_redirects=False)
        if response.is_redirect:
            url = urljoin(url, response.headers['Location'])
            continue
        response.raise_for_status()
        return response
    raise ValueError('Too many issuer redirects')


def fetch(ticker, session, today, capture=None):
    import requests
    from bs4 import BeautifulSoup

    domain, url = SPECS[ticker]
    response = get(session, url, domain)
    if capture:
        suffix = 'xlsx' if response.content.startswith(b'PK') else 'html'
        (capture / f'{ticker}.source.{suffix}').write_bytes(response.content)
    if response.content.startswith(b'PK') or 'csv' in response.headers.get('Content-Type', '').lower():
        return parse_file(response.content, ticker, today), response.url
    soup = BeautifulSoup(response.text, 'html.parser')
    # Use complete holdings HTML only on the issuer's dedicated holdings page.
    if 'holdings' in urlparse(response.url).path.lower():
        matches = []
        for line in soup.get_text(' ', strip=True).split('As of ')[1:]:
            parsed = source_date(line[:35], today)
            if parsed:
                matches.append(parsed)
        context_date = matches[0] if len(set(matches)) == 1 else None
        for table in soup.find_all('table'):
            rows = [[c.get_text(' ', strip=True) for c in row.find_all(['th', 'td'])]
                    for row in table.find_all('tr')]
            try:
                return normalize(pd.DataFrame(rows), ticker, today, context_date), response.url
            except ValueError:
                pass
    candidates = []
    for anchor in soup.find_all('a', href=True):
        href = urljoin(response.url, anchor['href'])
        label = anchor.get_text(' ', strip=True).lower()
        if allowed(href, domain) and 'holding' in (href + label).lower() and re.search(r'\.(csv|xlsx)(\?|$)', href, re.I):
            candidates.append(href)
    for candidate in dict.fromkeys(candidates):
        try:
            download = get(session, candidate, domain)
            return parse_file(download.content, ticker, today), candidate
        except (ValueError, requests.RequestException):
            continue
    hints = [a['href'] for a in soup.find_all('a', href=True)
             if any(w in a['href'].lower() for w in ('holding', 'download', '.csv', '.xlsx'))]
    scripts = [a.get('src') for a in soup.find_all('script', src=True)][:8]
    raise ValueError(f'No validated full holdings table. Link hints: {hints[:10]}; scripts: {scripts}')


def main():
    import requests

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--etfs', nargs='+', choices=sorted(SPECS), default=list(SPECS))
    parser.add_argument('--output', default='artifacts/new-etf-probe')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ZoneInfo('America/New_York')).date()
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (compatible; AlphaRadar holdings validation)'
    report = []
    for ticker in args.etfs:
        try:
            records, url = fetch(ticker, session, today, capture=output)
            with_shares = sum(r['shares'] is not None for r in records)
            result = {'etf': ticker, 'status': 'validated' if with_shares == len(records) else 'weight_only',
                      'date': records[0]['date'], 'rows': len(records), 'with_shares': with_shares,
                      'weight_total': round(sum(r['weight'] for r in records), 6), 'source': url}
            (output / f'{ticker}.json').write_text(json.dumps(records, indent=2, allow_nan=False))
        except Exception as exc:
            result = {'etf': ticker, 'status': 'blocked', 'reason': str(exc)}
        report.append(result)
        print(json.dumps(result), flush=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print('Read-only probe finished. No database access or production ETL changes.', flush=True)


if __name__ == '__main__':
    main()
