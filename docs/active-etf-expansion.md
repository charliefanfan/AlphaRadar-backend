# Read-only evaluation of 20 active ETF candidates

This branch only adds an independent probe, its tests, a branch/manual-only workflow, and this document. It does not change fetch_holdings.py, requirements.txt, existing workflows, production configuration, or Supabase data. No database credentials are referenced. Do not merge this as production ETF onboarding.

## Scope

DFAC, DFAU, DCOR, DUHP, DFLV, AVUV, AVUS, AVLV, CGCV, JEPI, JEPQ, JUSA, BUSA, MFSG, MFSV, LSGR, OAKM, PCLG, BCHP, TCHP.

## Source adapters

- Avantis: parse the full inert ETF holdings object embedded in the official product page with JSON5. Never evaluate issuer JavaScript. Use etfHoldingsAsOfDate, not the separate monthly characteristics date.
- Capital Group CGCV: dedicated official daily XLSX, percent values stored as fractions. Classify cash equivalents explicitly, including the CMQXX cash fund.
- JPMorgan: official FundsMarketingHandler Excel download with isProxyHolding=false and isUnderlyingHolding=false. Check workbook CUSIP and as-of date. Keep stocks, ADRs, and REITs; audit cash, money market instruments, rights, futures, and equity linked notes separately.
- MFS: full daily holdings HTML. Strip US exchange suffixes. Cash subtotal is retained for coverage; detailed sweep/currency cash subrows are not double-counted.
- Oakmark: official full CSV with per-row source date and fund identity.
- Natixis: official full daily CSV linked from the fund service JSON.
- Polen: full CSV data template on the official PCLG product page, not the top-ten display table.
- Principal: official BCHP XLSX, fractional weights and Par Value/Quantity/Notional as share quantity.
- Brandes: official BUSA.P portfolio basket in 6c11_Report.csv. Remains needs_review because Benchmark Quantity must be reconciled with actual holdings. No production promotion.
- Dimensional: official product pages and Document Center inspected. No verified complete daily holdings source for the five candidates in this run. Remain blocked; quarterly/monthly files are not substituted.
- TCHP: daily Proxy Portfolio is not actual holdings. Remains blocked for daily stock signals.

## Validation

Require a real as-of date within 14 days and no future dates, complete source weights between 95% and 105%, finite share/weight values, known asset classifications, unique equity tickers, at least five equities, and nonnegative equity shares/weights. Preserve numeric foreign tickers and zero rounded weights. Never invent a ticker or renormalize stock weights after excluding non-equities. Missing equity tickers (including AVUS corporate-action residuals) block promotion.

The workflow exports original source files, SHA256 fingerprints, normalized equity JSON, excluded non-equity audit rows, and a report. A successful workflow only means all candidates were evaluated; it does not mean every candidate is eligible.

Run locally:
python -m unittest discover -s tests -p test_equity_expansion.py -v
python scripts/probe_equity_expansion.py

Production onboarding requires a separate focused change after reviewing this report.
