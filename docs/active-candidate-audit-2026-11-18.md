# Active ETF candidate audit — November 18, 2026

Live official-source validation: [GitHub Actions run 44369649449](https://github.com/charliefanfan/AlphaRadar-backend/actions/runs/44369649449). All 10 parser regression tests passed in CI. This workflow has no database credentials and never imports the production ETL.

## Scope and interpretation

All 36 candidate entries below were inspected, including corrected fund identities and additional examples from the requested issuers. **Parsed and audited means the downloaded snapshot passed this parser's identity/date/coverage checks; it does not establish ongoing source reliability, US listing identity, or production approval.** No changes were made to the scheduled ETL, database, or iOS project.

The parser preserves actual issuer dates and original NAV weight percentages, requires positive source coverage near 100%, rejects duplicate stock identities and unknown classifications, and excludes identified cash, fixed income, options, futures, equity-linked notes, SPVs, swaps, and private positions from the equity signal output. The full original source remains in the run artifacts. Filtered stock weights are not rescaled to 100%.

## Live results

| Ticker | Issuer | Result | Source date | Equity rows | Notes |
|---|---|---|---|---:|---|
| RSHO | Tema | renamed | — | — | Official product page redirects to WELD; do not add duplicate RSHO snapshots |
| WELD | Tema | parsed_and_audited | 2026-11-17 | 21 |  |
| CANC | Tema | parsed_and_audited | 2026-11-17 | 56 |  |
| HRTS | Tema | parsed_and_audited | 2026-11-17 | 45 |  |
| VOLT | Tema | parsed_and_audited | 2026-11-17 | 24 |  |
| LUX | Tema | rejected | — | — | Only a stale 2025-08-07 cash-only file is available |
| TOLL | Tema | parsed_and_audited | 2026-11-17 | 36 |  |
| DISK | Tema | parsed_and_audited | 2026-11-17 | 16 |  |
| LAZR | Tema | parsed_and_audited | 2026-11-17 | 23 |  |
| HLTH | Tema | parsed_and_audited | 2026-11-17 | 32 |  |
| CGXU | Capital Group | parsed_and_audited | 2026-11-17 | 78 | Source parses, but unqualified foreign symbols still require exchange/security identity mapping before stock-signal integration. |
| CGIE | Capital Group | parsed_and_audited | 2026-11-17 | 72 | Source parses, but unqualified foreign symbols still require exchange/security identity mapping before stock-signal integration. |
| CGCV | Capital Group | parsed_and_audited | 2026-11-17 | 72 |  |
| CGNG | Capital Group | rejected | — | — | Missing/duplicate stock identity: ASML |
| CGBL | Capital Group | parsed_and_audited | 2026-11-17 | 74 |  |
| BGRO | iShares | parsed_and_audited | 2026-11-17 | 43 |  |
| BALI | iShares | parsed_and_audited | 2026-11-17 | 190 |  |
| JEPI | JPMorgan | parsed_and_audited | 2026-11-17 | 117 |  |
| JEPQ | JPMorgan | parsed_and_audited | 2026-11-17 | 94 |  |
| JPEF | JPMorgan | parsed_and_audited | 2026-11-17 | 40 |  |
| JPSV | JPMorgan | parsed_and_audited | 2026-11-17 | 118 |  |
| TCHP | T. Rowe Price | rejected | — | — | Issuer identifies a semi-transparent ETF and a daily proxy portfolio |
| TGRT | T. Rowe Price | parsed_and_audited | 2026-11-18 | 88 |  |
| TCAF | T. Rowe Price | parsed_and_audited | 2026-11-18 | 92 |  |
| TVAL | T. Rowe Price | parsed_and_audited | 2026-11-18 | 139 |  |
| TEQI | T. Rowe Price | rejected | — | — | Issuer identifies a semi-transparent ETF and a daily proxy portfolio |
| FBCG | Fidelity | rejected | — | — | Research page provides Basket Holdings as of 2026-09-30; not a current full daily portfolio |
| FBCV | Fidelity | rejected | — | — | Research page provides Basket Holdings as of 2026-09-30; not a current full daily portfolio |
| FMAG | Fidelity | rejected | — | — | Research page provides Basket Holdings as of 2026-09-30; not a current full daily portfolio |
| ALAI | Alger | daily CSV downloaded; classification adapter pending | 2026-11-17 | — | Official transparent fund data frame links to daily CSV. File includes private or unlisted positions and cash; internal identifiers must not become stock tickers. |
| ATFV | Alger | daily CSV downloaded; classification adapter pending | 2026-11-17 | — | Official transparent fund data frame links to daily CSV. File includes private or unlisted positions and cash; internal identifiers must not become stock tickers. |
| JXX | Janus Henderson | parsed_and_audited | 2026-11-17 | 23 |  |
| JMID | Janus Henderson | parsed_and_audited | 2026-11-17 | 94 |  |
| JPLG | JPMorgan UCITS (London) | different_market | — | — | London-listed UCITS fund, not a US ETF; needs market-qualified identities |
| GTEK | Goldman Sachs | official_json_available | 2026-11-17 | — | Full official daily JSON verified; asset classification and foreign listing mapping still needed |
| GSGO | Goldman Sachs | official_json_available | 2026-11-17 | — | Full official daily JSON verified; asset classification and foreign listing mapping still needed |

## Important findings

- **RSHO / WELD:** the official RSHO page resolves to the current WELD product and WELD download. Do not create a duplicate fund under the old identifier. Current Tema CSV links carry dates, so production retrieval should discover the product page's exact matching download link rather than assume a static path.
- **LUX:** the legacy CSV is HTTP-successful but contains only a cash row dated 2025-08-07. Download success alone is not a valid portfolio.
- **CGNG:** ASML occurs under both NL0010273215 and USN070592100. WPM also occurs with different listing identifiers. Keeping the first row, summing all quantities without resolving listing identity, or silently dropping duplicates would corrupt signals.
- **CGBL:** 74 stock rows represent **58.56% of fund NAV**, not 100%. Fixed-income and cash holdings remain in the full-source audit and are excluded from stock signals.
- **TCHP / TEQI:** official disclosures identify daily proxy portfolios. Only the independently verified transparent TGRT/TCAF/TVAL full portfolio component is parsed. Their source effective date is 2026-11-18; it is preserved as reported, not converted to a guessed trade date.
- **FBCG / FBCV / FMAG:** the inspected Fidelity research pages provide Basket Holdings dated 2026-09-30. These are unsuitable as current complete daily portfolios.
- **JMID:** Janus Henderson Mid Cap Growth Alpha ETF, not JPMorgan.
- **JPLG:** London-listed UCITS share listing, not a US ETF candidate. Keep market-qualified fund and security identities separate.
- **Alger:** ALAI and ATFV official embedded product data both report transparency and expose current daily CSV downloads. The files include internal identifiers for private holdings, such as VAST DATA / SPV interests, so a generic ticker-column parser would create false stock signals. Older non-transparent descriptions of ATFV are stale; the official fund list states its conversion became effective December 2, 2024.
- **Goldman Sachs:** both full daily portfolios are available through the official public GraphQL API, even though a CSV link was not found. GTEK: 64 source rows, 100.01% source coverage; GSGO: 55 source rows, 100.00%. Asset classification and international listing mapping remain pending; these raw rows are not passed to stock signals.
- **Tema SLS metadata:** CANC's SELLAS position has blank country/sector fields. The parser accepts only the exact disclosed ticker/name/CUSIP combination (SLS / SELLAS LIFE SCIENCES GROUP INC / 81642T209), rather than treating all missing-classification rows as stocks. [Issuer stock information](https://ir.sellaslifesciences.com/investor-resources/).

## Official endpoints verified

- [Tema fund list](https://temaetfs.com/funds); fund-matched CSV links are discovered from individual fund pages.
- Capital Group: `https://www.capitalgroup.com/api/investments/investment-service/v1/etfs/{ticker}/download/daily-holdings?audience=advisor` (XLSX).
- iShares: BGRO product ID **337538**; BALI **333207**. `https://www.ishares.com/us/products/{product_id}/holdings/latest-holdings.csv`.
- JPMorgan: official `FundsMarketingHandler/excel` with `type=dailyETFHoldings`, `isUnderlyingHolding=false`, `isProxyHolding=false`; verified fund CUSIPs are in the candidate adapter.
- T. Rowe Price: full portfolio JSON in the official page's `pop-holdings-component`, verified transparent configuration and fund product codes CFX/GRX/VLX.
- [ALAI daily CSV](https://www.alger.com/AlgerETFDailyHoldings/Daily_Holdings_Alger_AI_Enablers_%26_Adopters_ETF.csv).
- [ATFV daily CSV](https://www.alger.com/AlgerETFDailyHoldings/Daily_Holdings_Alger_35_ETF.csv).
- Janus Henderson: each verified product's `/full-holdings/` official table, including quantity and real as-of date.
- Goldman Sachs: `POST https://am.gs.com/services/funds`, read-only `fundsDetail` query / `allHoldings` field. Verified identities GTEK/PV103849/38149W812 and GSGO/PV109510/38149W440.

## Reproduce

The branch-specific `Probe active ETF candidates (no database)` workflow installs the existing pinned dependencies, runs `python -m unittest discover -s tests -p 'test_active_candidate_adapter.py' -v`, and runs `python -u scripts/probe_active_candidates.py`. Its artifact includes raw official downloads, normalized snapshots, and machine-readable and Markdown reports. Detailed exploratory diagnostics are opt-in through `CANDIDATE_DIAGNOSTICS=1`.

Before enabling these in production, add issuer-specific fetching around the validated parsers, resolve remaining international/private security identity issues, and smoke-test that integration without database access. Existing production CGCV, JEPI and JEPQ are regression candidates and must not be registered twice.
