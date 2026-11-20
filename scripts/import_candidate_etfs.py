"""Opt-in onboarding of live-validated ETFs, separate from the production schedule.

Defaults to a read-only preview. --write uses the existing storage contract for
new ETF symbols only; all source downloads are validated before any DB import.
"""
from __future__ import annotations

import argparse
import importlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from probe_active_etfs import fetch

# Only these sources have passed live issuer-data validation in Actions.
WRITE_CANDIDATES = frozenset({'CGUS', 'CGGO'})


def collect(tickers, session, today, output=None):
    if not tickers or len(set(tickers)) != len(tickers) or not set(tickers) <= WRITE_CANDIDATES:
        raise ValueError('Only the distinct, live-validated CGUS/CGGO candidates can be imported')
    snapshots = {}
    for ticker in tickers:
        records, _ = fetch(ticker, session, today, capture=output)
        if not records or any(r['etf'] != ticker for r in records):
            raise ValueError(f'{ticker}: snapshot identity mismatch')
        snapshots[ticker] = records
    return snapshots


def write_new_funds(snapshots, backend=None):
    # Validate the complete batch before importing the module that creates a DB client.
    if not snapshots or not set(snapshots) <= WRITE_CANDIDATES:
        raise ValueError('Cannot write an existing or unvalidated ETF')
    for ticker, rows in snapshots.items():
        if not rows or any(row['etf'] != ticker for row in rows):
            raise ValueError('Candidate snapshot identity mismatch')
    backend = backend if backend is not None else importlib.import_module('fetch_holdings')
    existing = {'ARKQ'}
    for name in ('ARK_ETFS', 'TEMA_ETFS', 'ISHARES_ETFS', 'ADDITIONAL_ETFS'):
        existing.update(getattr(backend, name, {}))
    if set(snapshots) & existing:
        raise ValueError('This command cannot overwrite an ETF registered in the production fetcher')
    results = {}
    for ticker, records in snapshots.items():
        status = backend.save_etf(ticker, pd.DataFrame(records))
        if status not in {'saved', 'unchanged'}:
            raise RuntimeError(f'{ticker}: storage returned {status}')
        results[ticker] = status
    return results


def main():
    import requests

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--etfs', nargs='+', choices=sorted(WRITE_CANDIDATES), default=sorted(WRITE_CANDIDATES))
    parser.add_argument('--output', default='artifacts/candidate-etf-import')
    parser.add_argument('--write', action='store_true', help='Explicitly opt in to saving these new ETF symbols')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (compatible; AlphaRadar holdings validation)'
    snapshots = collect(args.etfs, session, datetime.now(ZoneInfo('America/New_York')).date(), output)
    for ticker, records in snapshots.items():
        (output / f'{ticker}.json').write_text(json.dumps(records, indent=2, allow_nan=False))
    if args.write:
        print(json.dumps(write_new_funds(snapshots)))
    else:
        print(json.dumps({t: {'status': 'preview_only', 'date': rows[0]['date'], 'rows': len(rows)}
                          for t, rows in snapshots.items()}))


if __name__ == '__main__':
    main()
