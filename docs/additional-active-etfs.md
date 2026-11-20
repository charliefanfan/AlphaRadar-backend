# Additional active ETF onboarding

## Verified live sources

| ETF | Source date | Records | Records with shares | Reported weight coverage |
| --- | --- | ---: | ---: | ---: |
| CGUS | 2026-11-13 | 68 | 68 | 99.93% |
| CGGO | 2026-11-13 | 100 | 100 | 99.89% |

Live validation: https://github.com/charliefanfan/AlphaRadar-backend/actions/runs/44006256160

DIVO, JEPI, JEPQ and DFAC currently fail closed: their product pages do not expose
complete static holdings tables or verified download links to this adapter.
They are not eligible for import.

The Capital Group adapter omits only tickerless ledger rows explicitly named
NET OTHER ASSETS and US DOLLAR. It does not renormalize weights. Unknown material
holdings without an instrument ticker remain errors. Numeric overseas tickers
are retained. Missing share counts remain null, and source dates are never
replaced with the execution date.

## Read-only use

Install the existing requirements, then run:

```sh
python scripts/probe_active_etfs.py
python scripts/import_candidate_etfs.py --etfs CGUS CGGO
```

Both commands default to local JSON previews. No Supabase credentials are needed.
The probe-only workflow contains no Supabase environment variables or scheduled
trigger and cannot write to a database.

The import adapter has an explicit write option for a later owner-approved
production trial. It permits only the two validated new symbols, refuses symbols
already registered in the production fetcher, and validates the full downloaded
batch before importing the existing database client. Production writing and
additional scheduled jobs are NOT activated by this change.

## Compatibility

Existing scripts/fetch_holdings.py, requirements.txt and
.github/workflows/daily_update.yml remain unchanged. No schema changes,
historical updates, existing-fund writes, production scheduling changes, or
App changes are included. The existing storage contract is reused only when a
future production import is explicitly authorized.

New snapshots alone cannot establish share changes. The first stored snapshot
is not evidence that every holding is a new purchase. Today's signals must still
require a source snapshot on the displayed market date.

## Tests

```sh
python -m unittest discover -s tests -p 'test_probe_active_etfs.py' -v
python -m unittest discover -s tests -p 'test_import_candidate_etfs.py' -v
```

11 parser/source checks and 5 import-isolation checks are included. The latter
use a mock backend and never require a live Supabase connection.
