"""Read-only official-source exploration. Never imports ETL or connects to a database."""
from __future__ import annotations
import csv
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

OUT = Path('artifacts/active-candidates')
TODAY = datetime.now(ZoneInfo('America/New_York')).date()
TEMA = ('RSHO', 'WELD', 'CANC', 'HRTS', 'VOLT', 'LUX', 'TOLL', 'DISK', 'LAZR', 'HLTH')
CAPITAL = ('CGXU', 'CGIE', 'CGCV', 'CGNG', 'CGBL')
ISHARES = {'BGRO': '337538', 'BALI': '333207'}
JPM = {'JEPI': '46641Q332', 'JEPQ': '46654Q203', 'JPEF': '46654Q781', 'JPSV': '46654Q708'}
TRP = ('TCHP', 'TGRT', 'TCAF', 'TVAL', 'TEQI')
FIDELITY = ('FBCG', 'FBCV', 'FMAG')
ALGER = {'ALAI': '2494', 'ATFV': '2489'}
JANUS = {'JXX': 'transformational-growth-etf-jxx', 'JMID': 'mid-cap-growth-alpha-etf-jmid'}
ROOTS = ('temaetfs.com', 'capitalgroup.com', 'ishares.com', 'jpmorgan.com',
         'troweprice.com', 'fidelity.com', 'alger.com', 'janushenderson.com',
         'am.gs.com', 'gsam.com')


def official(url):
    host = (urlparse(url).hostname or '').lower()
    return urlparse(url).scheme == 'https' and any(host == h or host.endswith('.' + h) for h in ROOTS)


def get(url):
    with requests.Session() as s:
        s.headers['User-Agent'] = 'Mozilla/5.0 (AlphaRadar official holdings validation)'
        for _ in range(6):
            if not official(url):
                raise ValueError('Unverified source host: ' + url)
            r = s.get(url, timeout=25, allow_redirects=False)
            if r.is_redirect:
                url = urljoin(url, r.headers['Location'])
                continue
            r.raise_for_status()
            return r.content, url, r.headers.get('Content-Type', '')
    raise ValueError('Too many redirects')


def links(content, base, pattern='holding|portfolio|download|csv|xlsx'):
    soup = BeautifulSoup(content, 'html.parser')
    found = []
    for a in soup.select('a[href]'):
        label = a.get_text(' ', strip=True)
        u = urljoin(base, a['href'])
        if official(u) and re.search(pattern, u + ' ' + label, re.I):
            found.append({'label': label[:160], 'url': u})
    return list({v['url']: v for v in found}.values())


def tables(content):
    if content[:2] == b'PK':
        return pd.read_excel(BytesIO(content), sheet_name=None, header=None, dtype=object)
    if b'<html' in content[:1000].lower() or b'<!doctype' in content[:1000].lower():
        raise ValueError('HTML page, not a holdings file')
    rows = list(csv.reader(StringIO(content.decode('utf-8-sig'))))
    width = max(map(len, rows), default=0)
    return {'csv': pd.DataFrame([r + [''] * (width-len(r)) for r in rows])}


def describe(content):
    result = []
    for name, f in tables(content).items():
        headers = None
        index = None
        for i in range(min(60, len(f))):
            vals = [str(v).strip() for v in f.iloc[i]]
            if any(v.lower() in {'ticker', 'symbol', 'security ticker'} for v in vals):
                headers, index = vals, i
                break
        item = {'sheet': name, 'rows': len(f), 'headers': headers,
                'preamble': f.head(min(index or 8, 8)).fillna('').astype(str).values.tolist()}
        if index is not None:
            item['sample'] = f.iloc[index+1:index+4].fillna('').astype(str).values.tolist()
        result.append(item)
    return result


def inspect_file(ticker, url, tag='holdings'):
    data, final, mime = get(url)
    ext = 'xlsx' if data[:2] == b'PK' else 'html' if b'<html' in data[:1000].lower() else 'csv'
    (OUT / f'{ticker}-{tag}.{ext}').write_bytes(data)
    info = {'url': final, 'bytes': len(data), 'content_type': mime}
    try:
        info['tables'] = describe(data)
        info['status'] = 'downloaded_table'
    except Exception as e:
        info['status'] = 'page_only'
        info['reason'] = str(e)
        info['links'] = links(data, final)[:30]
    return info


def probe(ticker, issuer, urls, page=None):
    result = {'ticker': ticker, 'issuer': issuer, 'attempts': [], 'status': 'unresolved'}
    try:
        if page:
            data, final, _ = get(page)
            (OUT / f'{ticker}-page.html').write_bytes(data)
            found = links(data, final)
            result['page'] = final
            result['links'] = found[:30]
            soup = BeautifulSoup(data, 'html.parser')
            text = soup.get_text(' ', strip=True)
            result['disclosure'] = [text[max(0,m.start()-80):m.end()+180]
                for m in list(re.finditer('tracking basket|proxy portfolio|will not|each business day', text, re.I))[:4]]
            downloads = [v['url'] for v in found if re.search(r'\.csv|\.xlsx|dailyETFHoldings', v['url'], re.I)]
            urls = downloads[:3] + urls
        for url in dict.fromkeys(urls):
            try:
                info = inspect_file(ticker, url)
                result['attempts'].append(info)
                if info['status'] == 'downloaded_table':
                    result['status'] = 'downloaded_table'
                    break
            except Exception as e:
                result['attempts'].append({'url': url, 'error': str(e)})
        if result['status'] != 'downloaded_table' and page:
            result['status'] = 'needs_adapter'
    except Exception as e:
        result['error'] = str(e)
    return result


def discover_trp():
    url = 'https://www.troweprice.com/financial-intermediary/us/en/investments/etfs.html/'
    data, final, _ = get(url)
    soup = BeautifulSoup(data, 'html.parser')
    return {t: next((urljoin(final,a['href']) for a in soup.select('a[href]')
                    if a.get_text(' ',strip=True).strip() == t), None) for t in TRP}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for t in TEMA:
        jobs.append((t, 'Tema', [f'https://temaetfs.com/hubfs/Website/Holdings/{t}-holdings.csv'],
                     f'https://temaetfs.com/{t.lower()}'))
    for t in CAPITAL:
        jobs.append((t, 'Capital Group', [f'https://www.capitalgroup.com/api/investments/investment-service/v1/etfs/{t}/download/daily-holdings?audience=advisor'], None))
    for t, pid in ISHARES.items():
        base = f'https://www.ishares.com/us/products/{pid}/holdings'
        jobs.append((t, 'iShares', [base+'/latest-holdings.csv', base+'/1467271812596.ajax?fileType=csv&fileName='+t+'_holdings&dataType=fund'], None))
    for t, cusip in JPM.items():
        url = 'https://am.jpmorgan.com/FundsMarketingHandler/excel?type=dailyETFHoldings&cusip='+cusip+'&country=us&role=adv&fundType=ETF&locale=en-US&isUnderlyingHolding=false&isProxyHolding=false'
        jobs.append((t, 'JPMorgan', [url], None))
    try:
        trp_pages = discover_trp()
    except Exception as e:
        trp_pages = {}
        print('TRP discovery:', e, flush=True)
    for t in TRP:
        jobs.append((t, 'T. Rowe Price', [], trp_pages.get(t) or 'https://www.troweprice.com/financial-intermediary/us/en/investments/etfs.html/'))
    for t in FIDELITY:
        jobs.append((t, 'Fidelity', [], 'https://research2.fidelity.com/fidelity/screeners/etf/etfholdings.asp?symbol='+t+'&view=Holdings'))
    for t, code in ALGER.items():
        jobs.append((t, 'Alger', [], 'https://www.alger.com/pages/Products.aspx?productCode='+code))
    for t, slug in JANUS.items():
        jobs.append((t, 'Janus Henderson', [], 'https://www.janushenderson.com/en-us/institutional/product/'+slug+'/full-holdings/'))
    jobs.append(('JPLG', 'JPMorgan UCITS (London)', [], 'https://am.jpmorgan.com/fr/en/asset-management/institutional/products/jpm-global-equity-multi-factor-ucits-etf-usd-acc-ie00bjrcll96'))
    jobs.append(('GTEK', 'Goldman Sachs', [], 'https://am.gs.com/en-us/advisors/products/active-etfs'))
    jobs.append(('GSGO', 'Goldman Sachs', [], 'https://am.gs.com/en-us/advisors/funds/detail/PV109510/38149W440/goldman-sachs-growth-opportunities-etf'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda job: probe(*job), jobs))
    for r in results:
        print('CANDIDATE '+json.dumps(r, ensure_ascii=False, default=str), flush=True)
    (OUT / 'report.json').write_text(json.dumps({'checked_at': datetime.now().isoformat(), 'results': results}, indent=2, default=str))
    summary = '| Ticker | Issuer | Result |\n|---|---|---|\n'
    summary += '\n'.join(f"| {r['ticker']} | {r['issuer']} | {r['status']} |" for r in results)
    (OUT / 'report.md').write_text(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(summary)
    deep_audit()
    validate_candidates()


def validate_candidates():
    from active_candidate_adapter import parse, TEMA, CAPITAL, ISHARES, JPM, JANUS
    for ticker in sorted(TEMA | CAPITAL | set(ISHARES) | set(JPM) | JANUS):
        paths = list(OUT.glob(ticker+'-holdings.*')) if ticker not in JANUS else [OUT/(ticker+'-page.html')]
        try:
            if len(paths)!=1:
                raise ValueError('Expected exactly one downloaded source')
            records, audit = parse(ticker, paths[0].read_bytes(), TODAY)
            (OUT/(ticker+'-normalized.json')).write_text(json.dumps({'audit':audit,'records':records},indent=2))
            print('VALIDATED '+json.dumps({'ticker':ticker,**{k:v for k,v in audit.items() if k!='excluded'},'excluded_types':sorted({r['kind'] for r in audit['excluded']})}),flush=True)
        except Exception as e:
            print('REJECTED '+json.dumps({'ticker':ticker,'reason':str(e)}),flush=True)


def deep_audit():
    for p in sorted(OUT.glob('*-holdings.*')):
        if p.suffix == '.html':
            continue
        for name, f in tables(p.read_bytes()).items():
            for i in range(min(60, len(f))):
                h = [str(v).strip() for v in f.iloc[i]]
                if not any(v.lower() in {'ticker', 'symbol'} for v in h):
                    continue
                f = f.iloc[i+1:].copy()
                f.columns = h
                kinds = [v for v in h if v.lower() in {'type', 'asset class', 'asset type', 'security type', 'is_cash'}]
                weights = [v for v in h if v.lower() in {'percent_of_nav', 'weight (%)', 'percent of net assets', '% of net assets'}]
                print('DETAIL '+json.dumps({'file': p.name, 'sheet': name,
                    'types': {k: f[k].fillna('').astype(str).value_counts().to_dict() for k in kinds},
                    'weights': {k: float(pd.to_numeric(f[k].astype(str).str.replace('%','',regex=False).str.replace(',','',regex=False),errors='coerce').sum()) for k in weights},
                    'tail': f.tail(6).fillna('').astype(str).values.tolist()}, default=str), flush=True)
                break
    for ticker in ('TCAF', 'TGRT', 'TVAL', 'ALAI', 'JXX', 'JMID', 'FBCG', 'FBCV', 'FMAG', 'GTEK', 'GSGO'):
        path = OUT / (ticker+'-page.html')
        if not path.exists():
            continue
        raw = path.read_text(errors='replace')
        soup = BeautifulSoup(raw, 'html.parser')
        if ticker in {'TCAF','TGRT','TVAL'}:
            for component in soup.select('[data-component-object]'):
                if 'holding' in component.name:
                    obj=json.loads(component['data-component-object'])
                    (OUT/(ticker+'-component.json')).write_text(json.dumps(obj,indent=2))
                    full=obj.get('full') or {}
                    holdings=full.get('holdings') or []
                    print('TRPCOMPONENT '+json.dumps({'ticker':ticker,'keys':list(obj),'full_keys':list(full),
                        'date':full.get('effectiveDate'),'rows':len(holdings),
                        'types':{k:sum(r.get('investmentType')==k for r in holdings) for k in {r.get('investmentType') for r in holdings}},
                        'total':sum(r.get('percentageTotalNetAssets') or 0 for r in holdings),
                        'special':[r for r in holdings if not r.get('tickerSymbol') or not re.search('COMMON STOCK| ADR',r.get('name',''))],
                        'sample':holdings[:2]}),flush=True)
        if ticker=='GTEK':
            print('GSFUNDS '+json.dumps(links(path.read_bytes(),'https://am.gs.com','funds/detail|gtek|growth-opportunities|technology-opportunities')),flush=True)
        if ticker=='GSGO':
            print('GSDATA '+json.dumps({'links':links(path.read_bytes(),'https://am.gs.com','holding|csv|xlsx|download'),
                'snippets':[raw[max(0,m.start()-130):m.end()+250] for m in list(re.finditer(r'holdings|portfolioId|download.*?csv',raw,re.I))[:20]]}),flush=True)
        if ticker=='ALAI':
            print('ALGERINIT '+json.dumps([raw[max(0,m.start()-150):m.end()+500] for m in list(re.finditer(r'product\.init|product\.data\s*=|\.json|webservice|productData|dataURL',raw,re.I))[:15]]),flush=True)
        tab = []
        for table in soup.find_all('table'):
            rows = [[c.get_text(' ',strip=True) for c in tr.find_all(['th','td'])] for tr in table.find_all('tr')]
            if any(any('ticker' in c.lower() or 'symbol' in c.lower() for c in r) for r in rows[:3]):
                tab.append({'rows': len(rows), 'head': rows[:3], 'tail': rows[-2:]})
        scripts = [urljoin('https://www.troweprice.com' if ticker=='TCAF' else 'https://www.alger.com' if ticker=='ALAI' else 'https://am.gs.com', s['src']) for s in soup.select('script[src]')]
        snippets = [raw[max(0,m.start()-180):m.end()+250] for m in list(re.finditer(r'data-product|productCode|apiEndpoint|fundCode|fundId|holdingsUrl|dailyhold|\.csv|GTEK|As of|AS OF', raw, re.I))[:18]]
        print('PAGEDETAIL '+json.dumps({'ticker':ticker, 'tables':tab,'scripts':scripts,'snippets':snippets},default=str),flush=True)
        if ticker in {'TCAF','ALAI'}:
            candidates = [u for u in scripts if official(u) and re.search('clientlib|product|fund|main|bundle|/Alger.js',u,re.I)]
            for n,u in enumerate(candidates[-4:]):
                try:
                    data, final, _ = get(u)
                    (OUT / f'{ticker}-script-{n}.js').write_bytes(data)
                    js = data.decode('utf-8',errors='replace')
                    fragments = [js[max(0,m.start()-150):m.end()+350] for m in list(re.finditer(r'\.getJSON|url:|\.ajax|/api/|\.asmx|\.svc|dataUrl|dataURL|\.json|product\.init|loadData',js,re.I))[:18]]
                    print('JSDETAIL '+json.dumps({'ticker':ticker,'url':final,'fragments':fragments}),flush=True)
                except Exception as e:
                    print('JSERROR',ticker,u,str(e),flush=True)


if __name__ == '__main__':
    main()
