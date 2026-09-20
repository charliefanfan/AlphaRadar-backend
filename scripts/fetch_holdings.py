# import requests
# import pandas as pd
# from datetime import date, timedelta
# from supabase import create_client
# import os
# import time

# # ── Supabase client ───────────────────────────────────────────────────────────
# SUPABASE_URL = os.environ["SUPABASE_URL"]
# SUPABASE_KEY = os.environ["SUPABASE_KEY"]
# supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# # ── Constants ─────────────────────────────────────────────────────────────────
# TODAY     = date.today().isoformat()
# YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
# HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; AlphaRadar/1.0)"}

# # ── ARK ETFs ──────────────────────────────────────────────────────────────────
# # CSV: no header row, 8 fixed columns
# # date | fund | company | ticker | cusip | shares | market_value | weight
# ARK_BASE = "https://assets.ark-funds.com/fund-documents/funds-etf-csv"
# ARK_COLS  = ["date", "fund", "company", "ticker", "cusip", "shares", "market_value", "weight"]

# ARK_ETFS = {
#     "ARKK": f"{ARK_BASE}/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
#     "ARKW": f"{ARK_BASE}/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
#     "ARKG": f"{ARK_BASE}/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
#     "ARKF": f"{ARK_BASE}/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
#     "ARKX": f"{ARK_BASE}/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv",
#     "PRNT": f"{ARK_BASE}/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv",
#     "IZRL": f"{ARK_BASE}/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv",
# }

# # ARKQ — ARK CDN accepts literal & in filenames (confirmed from ARKX URL pattern)
# ARKQ_URLS = [
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECH._%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECH_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARKQ_HOLDINGS.csv",
# ]

# # ── Tema ETFs ─────────────────────────────────────────────────────────────────
# # Official CSV URL confirmed from temaetfs.com/nasa page source
# TEMA_ETFS = {
#     "NASA": "https://temaetfs.com/hubfs/Website/Holdings/NASA-holdings.csv",
# }


# # ─────────────────────────────────────────────────────────────────────────────
# # SHARED HELPERS
# # ─────────────────────────────────────────────────────────────────────────────

# def _clean_and_dedup(df, etf_ticker):
#     """Clean weight column, tag etf/date, deduplicate on (etf, ticker, date)."""
#     df["weight"] = (
#         df["weight"].astype(str)
#         .str.replace("%", "", regex=False)
#         .str.replace(",", "", regex=False)
#         .str.strip()
#     )
#     df["weight"]  = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
#     df["ticker"]  = df["ticker"].astype(str).str.strip().str.upper()
#     df["company"] = df["company"].astype(str).str.strip()
#     df["etf"]     = etf_ticker
#     df["date"]    = TODAY

#     result = df[["etf", "ticker", "company", "weight", "date"]]
#     result = result[~result["ticker"].isin(["NAN", "", "-", "TICKER"])]
#     result = result[result["weight"] > 0]

#     before = len(result)
#     result = (result
#               .sort_values("weight", ascending=False)
#               .drop_duplicates(subset=["etf", "ticker", "date"], keep="first"))
#     if len(result) < before:
#         print(f"  [{etf_ticker}] removed {before - len(result)} duplicate rows")

#     print(f"  [{etf_ticker}] {len(result)} holdings — top: {result['ticker'].head(3).tolist()}")
#     return result


# def save_etf(ticker: str, df) -> bool:
#     if df is None or df.empty:
#         return False
#     records = df.to_dict("records")
#     for i in range(0, len(records), 100):
#         supabase.table("holdings").upsert(records[i:i+100]).execute()
#     changes = detect_changes(ticker, df)
#     if changes:
#         supabase.table("holding_changes").insert(changes).execute()
#     print(f"  ✓ saved, {len(changes)} changes detected")
#     return True


# # ─────────────────────────────────────────────────────────────────────────────
# # FETCH FUNCTIONS
# # ─────────────────────────────────────────────────────────────────────────────

# def fetch_ark(etf_ticker: str, url: str):
#     """ARK CSV: no header row, fixed 8-column format."""
#     try:
#         resp = requests.get(url, headers=HEADERS, timeout=30)
#         resp.raise_for_status()
#         from io import StringIO
#         df = pd.read_csv(StringIO(resp.text), header=None, names=ARK_COLS)
#         df = df[df["ticker"].notna()]
#         df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]
#         return _clean_and_dedup(df[["ticker", "company", "weight"]].copy(), etf_ticker)
#     except Exception as e:
#         print(f"  [{etf_ticker}] ✗ {e}")
#         return None


# def fetch_ark_with_fallback(etf_ticker: str, urls: list):
#     """Try multiple URL variants; use first that returns HTTP 200."""
#     for i, url in enumerate(urls):
#         try:
#             resp = requests.get(url, headers=HEADERS, timeout=30)
#             if resp.status_code == 200:
#                 print(f"  [{etf_ticker}] variant {i+1} OK")
#                 from io import StringIO
#                 df = pd.read_csv(StringIO(resp.text), header=None, names=ARK_COLS)
#                 df = df[df["ticker"].notna()]
#                 df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]
#                 return _clean_and_dedup(df[["ticker", "company", "weight"]].copy(), etf_ticker)
#             else:
#                 print(f"  [{etf_ticker}] variant {i+1} → HTTP {resp.status_code}")
#         except Exception as e:
#             print(f"  [{etf_ticker}] variant {i+1} ✗ {e}")
#     print(f"  [{etf_ticker}] all variants failed — skipping")
#     return None


# def fetch_tema(etf_ticker: str, url: str):
#     """
#     Tema CSV columns (confirmed from NASA live response):
#     holdings_date, ticker, cusip, proper_name, shares,
#     market_value, percent_of_nav, is_cash, country, sector
#     """
#     try:
#         resp = requests.get(url, headers=HEADERS, timeout=30)
#         resp.raise_for_status()
#         from io import StringIO

#         df = pd.read_csv(StringIO(resp.text))
#         df.columns = [c.strip().lower() for c in df.columns]

#         # Use confirmed column names; fall back to dynamic detection
#         ticker_col = next((c for c in df.columns if c == "ticker" or "ticker" in c), None)
#         name_col   = next((c for c in df.columns if c == "proper_name" or "name" in c or "company" in c), None)
#         weight_col = next((c for c in df.columns if c == "percent_of_nav" or "weight" in c or "percent" in c or "nav" in c), None)

#         if not all([ticker_col, name_col, weight_col]):
#             print(f"  [{etf_ticker}] ✗ unexpected columns: {list(df.columns)}")
#             return None

#         df = df[[ticker_col, name_col, weight_col]].copy()
#         df.columns = ["ticker", "company", "weight"]
#         df = df.dropna(subset=["ticker"])

#         # Filter out cash rows using is_cash column if available (already dropped above, use weight filter)
#         df = df[~df["ticker"].astype(str).str.strip().str.lower().isin(
#             ["ticker", "nan", "", "-", "cash", "usd"])]
#         return _clean_and_dedup(df, etf_ticker)
#     except Exception as e:
#         print(f"  [{etf_ticker}] ✗ {e}")
#         return None


# # ─────────────────────────────────────────────────────────────────────────────
# # CHANGE DETECTION
# # ─────────────────────────────────────────────────────────────────────────────

# def detect_changes(etf: str, today_df) -> list:
#     result = supabase.table("holdings") \
#         .select("ticker, weight") \
#         .eq("etf", etf) \
#         .eq("date", YESTERDAY) \
#         .execute()
#     yesterday_map = {r["ticker"]: float(r["weight"]) for r in (result.data or [])}

#     if not yesterday_map:
#         print(f"  [{etf}] no yesterday data — first run for this ETF")
#         return []

#     today_map = dict(zip(today_df["ticker"], today_df["weight"].astype(float)))
#     changes = []

#     for tkr, weight in today_map.items():
#         if tkr not in yesterday_map:
#             changes.append({
#                 "etf": etf, "ticker": tkr, "change_type": "new_position",
#                 "delta": round(weight, 4),
#                 "description": f"{etf} opened new position in {tkr}"
#             })
#         else:
#             delta = weight - yesterday_map[tkr]
#             if abs(delta) > 0.3:
#                 verb = "increased" if delta > 0 else "reduced"
#                 changes.append({
#                     "etf": etf, "ticker": tkr,
#                     "change_type": "accumulation" if delta > 0 else "reduction",
#                     "delta": round(delta, 4),
#                     "description": f"{etf} {verb} {tkr} by {abs(round(delta, 2))}%"
#                 })

#     for tkr in yesterday_map:
#         if tkr not in today_map:
#             changes.append({
#                 "etf": etf, "ticker": tkr, "change_type": "removed",
#                 "delta": 0.0, "description": f"{etf} removed {tkr} from portfolio"
#             })

#     return changes


# def generate_multi_etf_signals():
#     result = supabase.table("holding_changes") \
#         .select("ticker, etf, change_type") \
#         .eq("change_type", "accumulation") \
#         .gte("created_at", TODAY) \
#         .execute()

#     from collections import defaultdict
#     ticker_etfs: dict = defaultdict(list)
#     for row in (result.data or []):
#         ticker_etfs[row["ticker"]].append(row["etf"])

#     signals = [
#         {
#             "etf": "MULTI", "ticker": tkr,
#             "change_type": "multi_etf_buy",
#             "delta": float(len(etfs)),
#             "description": f"{len(etfs)} ETFs simultaneously buying {tkr}: {', '.join(etfs)}"
#         }
#         for tkr, etfs in ticker_etfs.items() if len(etfs) >= 3
#     ]

#     if signals:
#         supabase.table("holding_changes").insert(signals).execute()
#         print(f"  ✓ {len(signals)} multi-ETF signals")
#     else:
#         print("  No multi-ETF signals today")


# # ─────────────────────────────────────────────────────────────────────────────
# # MAIN
# # ─────────────────────────────────────────────────────────────────────────────

# def run():
#     print(f"AlphaRadar ETL — {TODAY}")
#     print("=" * 55)
#     success = 0

#     # ── ARK core ─────────────────────────────────────────
#     for ticker, url in ARK_ETFS.items():
#         print(f"\nFetching {ticker} (ARK)...")
#         if save_etf(ticker, fetch_ark(ticker, url)):
#             success += 1
#         time.sleep(1)

#     # ── ARKQ fallback ─────────────────────────────────────
#     print(f"\nFetching ARKQ (ARK, multi-URL fallback)...")
#     if save_etf("ARKQ", fetch_ark_with_fallback("ARKQ", ARKQ_URLS)):
#         success += 1
#     time.sleep(1)

#     # ── Tema ──────────────────────────────────────────────
#     for ticker, url in TEMA_ETFS.items():
#         print(f"\nFetching {ticker} (Tema)...")
#         if save_etf(ticker, fetch_tema(ticker, url)):
#             success += 1
#         time.sleep(1)

#     total = len(ARK_ETFS) + 1 + len(TEMA_ETFS)
#     print(f"\nGenerating cross-ETF signals...")
#     generate_multi_etf_signals()
#     print(f"\n{'='*55}")
#     print(f"Done: {success}/{total} ETFs updated")


# if __name__ == "__main__":
#     run()
import requests
import pandas as pd
from datetime import date, timedelta
from supabase import create_client
import os
import time

# ── Supabase client ───────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Constants ─────────────────────────────────────────────────────────────────
TODAY     = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; AlphaRadar/1.0)"}

# ── ARK ETFs ──────────────────────────────────────────────────────────────────
# CSV: no header row, 8 fixed columns
# date | fund | company | ticker | cusip | shares | market_value | weight
ARK_BASE = "https://assets.ark-funds.com/fund-documents/funds-etf-csv"
ARK_COLS  = ["date", "fund", "company", "ticker", "cusip", "shares", "market_value", "weight"]

ARK_ETFS = {
    "ARKK": f"{ARK_BASE}/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKW": f"{ARK_BASE}/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKG": f"{ARK_BASE}/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKF": f"{ARK_BASE}/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
    "ARKX": f"{ARK_BASE}/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv",
    "PRNT": f"{ARK_BASE}/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv",
    "IZRL": f"{ARK_BASE}/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv",
}

# ARKQ — ARK CDN accepts literal & in filenames (confirmed from ARKX URL pattern)
ARKQ_URLS = [
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECH._%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECH_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARKQ_HOLDINGS.csv",
]

# ── Tema ETFs ─────────────────────────────────────────────────────────────────
# Official CSV URL confirmed from temaetfs.com/nasa page source
TEMA_ETFS = {
    "NASA": "https://temaetfs.com/hubfs/Website/Holdings/NASA-holdings.csv",
}

# ── iShares Active ETFs ────────────────────────────────────────────────────────
# iShares public holdings CSV endpoint.
# Selected active ETFs with current official holdings pages:
# BAI  A.I. Innovation and Tech Active
# TEK  Technology Opportunities Active
# DYNF U.S. Equity Factor Rotation Active
# THRO U.S. Thematic Rotation Active
# INRO U.S. Industry Rotation Active
# BMED Health Innovation Active
# IDYN International Equity Factor Rotation Active
ISHARES_ETFS = {
    "BAI":  {"product_id": "339081"},
    "TEK":  {"product_id": "339083"},
    "DYNF": {"product_id": "307283"},
    "THRO": {"product_id": "325384"},
    "INRO": {"product_id": "336430"},
    "BMED": {"product_id": "316007"},
    "IDYN": {"product_id": "345128"},
}


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _clean_and_dedup(df, etf_ticker):
    """Clean weight column, tag etf/date, deduplicate on (etf, ticker, date)."""
    df["weight"] = (
        df["weight"].astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    df["weight"]  = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
    df["ticker"]  = df["ticker"].astype(str).str.strip().str.upper()
    df["company"] = df["company"].astype(str).str.strip()
    df["etf"]     = etf_ticker
    df["date"]    = TODAY

    result = df[["etf", "ticker", "company", "weight", "date"]]
    result = result[~result["ticker"].isin(["NAN", "", "-", "TICKER"])]
    result = result[result["weight"] > 0]

    before = len(result)
    result = (result
              .sort_values("weight", ascending=False)
              .drop_duplicates(subset=["etf", "ticker", "date"], keep="first"))
    if len(result) < before:
        print(f"  [{etf_ticker}] removed {before - len(result)} duplicate rows")

    print(f"  [{etf_ticker}] {len(result)} holdings — top: {result['ticker'].head(3).tolist()}")
    return result


def save_etf(ticker: str, df) -> bool:
    if df is None or df.empty:
        return False
    records = df.to_dict("records")
    for i in range(0, len(records), 100):
        supabase.table("holdings").upsert(records[i:i+100]).execute()
    changes = detect_changes(ticker, df)
    if changes:
        supabase.table("holding_changes").insert(changes).execute()
    print(f"  ✓ saved, {len(changes)} changes detected")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# FETCH FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ark(etf_ticker: str, url: str):
    """ARK CSV: no header row, fixed 8-column format."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text), header=None, names=ARK_COLS)
        df = df[df["ticker"].notna()]
        df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]
        return _clean_and_dedup(df[["ticker", "company", "weight"]].copy(), etf_ticker)
    except Exception as e:
        print(f"  [{etf_ticker}] ✗ {e}")
        return None


def fetch_ark_with_fallback(etf_ticker: str, urls: list):
    """Try multiple URL variants; use first that returns HTTP 200."""
    for i, url in enumerate(urls):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                print(f"  [{etf_ticker}] variant {i+1} OK")
                from io import StringIO
                df = pd.read_csv(StringIO(resp.text), header=None, names=ARK_COLS)
                df = df[df["ticker"].notna()]
                df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]
                return _clean_and_dedup(df[["ticker", "company", "weight"]].copy(), etf_ticker)
            else:
                print(f"  [{etf_ticker}] variant {i+1} → HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [{etf_ticker}] variant {i+1} ✗ {e}")
    print(f"  [{etf_ticker}] all variants failed — skipping")
    return None


def fetch_tema(etf_ticker: str, url: str):
    """
    Tema CSV columns (confirmed from NASA live response):
    holdings_date, ticker, cusip, proper_name, shares,
    market_value, percent_of_nav, is_cash, country, sector
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        from io import StringIO

        df = pd.read_csv(StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]

        # Use confirmed column names; fall back to dynamic detection
        ticker_col = next((c for c in df.columns if c == "ticker" or "ticker" in c), None)
        name_col   = next((c for c in df.columns if c == "proper_name" or "name" in c or "company" in c), None)
        weight_col = next((c for c in df.columns if c == "percent_of_nav" or "weight" in c or "percent" in c or "nav" in c), None)

        if not all([ticker_col, name_col, weight_col]):
            print(f"  [{etf_ticker}] ✗ unexpected columns: {list(df.columns)}")
            return None

        df = df[[ticker_col, name_col, weight_col]].copy()
        df.columns = ["ticker", "company", "weight"]
        df = df.dropna(subset=["ticker"])

        # Filter out cash rows using is_cash column if available (already dropped above, use weight filter)
        df = df[~df["ticker"].astype(str).str.strip().str.lower().isin(
            ["ticker", "nan", "", "-", "cash", "usd"])]
        return _clean_and_dedup(df, etf_ticker)
    except Exception as e:
        print(f"  [{etf_ticker}] ✗ {e}")
        return None


def fetch_ishares(etf_ticker: str, product_id: str):
    """Fetch an iShares holdings CSV and normalize it to AlphaRadar format.

    iShares CSVs are "ragged": a handful of 1-field metadata rows at the
    top (fund name, "as of" date, etc.), then the real header + data rows,
    then trailing disclaimer/footnote text that often contains embedded
    commas. Handing the *whole* file straight to pandas' C parser with
    header=None locks the expected column count to the first row (1 field)
    and then blows up ("Expected 1 fields in line 16, saw 4") the moment a
    wider row shows up — before we ever get a chance to look for the
    header row.

    Fix: scan for the header row using csv.reader() line-by-line (which
    tolerates ragged files fine, since it doesn't enforce one column count
    across the whole document), then let pandas parse only from that row
    onward, skipping any bad trailing rows.
    """
    from io import StringIO
    import csv

    # NOTE: the real product page needs a name slug we don't have per
    # ticker (e.g. /us/products/339081/ishares-ai-innovation-and-tech-active-etf),
    # so we warm up against the products index instead — this is enough to
    # pick up any domain-level session cookie Akamai sets, without needing
    # to know or guess the exact slug.
    product_page = "https://www.ishares.com/us/products/etf-product-list"
    endpoint = (
        f"https://www.ishares.com/us/products/{product_id}/"
        f"holdings/1467271812596.ajax"
    )

    # Use a Session + warm-up GET of the human-facing product page first.
    # iShares' edge (Akamai) will often reject the raw .ajax CSV request
    # with a short 403/empty body if it doesn't see a prior session/cookie
    # from the same client — this mimics a browser visiting the fund page
    # before it downloads the holdings CSV.
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(product_page, timeout=30)
    except Exception as e:
        print(f"  [{etf_ticker}] warm-up request failed: {e}")

    # Holdings may not be published for today on weekends/holidays.
    for days_back in range(0, 10):
        candidate = date.today() - timedelta(days=days_back)
        params = {
            "fileType": "csv",
            "fileName": f"{etf_ticker}_holdings",
            "dataType": "fund",
            "asOfDate": candidate.strftime("%m%d%Y"),
        }

        try:
            resp = session.get(
                endpoint,
                params=params,
                headers={
                    "Referer": product_page,
                    "Accept": "text/csv,text/plain,*/*",
                },
                timeout=30,
            )
            if resp.status_code != 200 or len(resp.text) < 100:
                # DIAGNOSTIC: log what we actually got back so failures are
                # debuggable from CI logs instead of a silent skip.
                snippet = resp.text[:200].replace("\n", " ") if resp.text else ""
                print(
                    f"  [{etf_ticker}] {candidate.isoformat()} → "
                    f"HTTP {resp.status_code}, {len(resp.text)} bytes: {snippet!r}"
                )
                continue

            # Find the header row (the one containing "ticker") using
            # csv.reader per-line, NOT pandas — pandas would choke on the
            # ragged rows before we even locate the header.
            lines = resp.text.splitlines()
            header_idx = None
            for idx, line in enumerate(lines):
                try:
                    values = {
                        v.strip().lower()
                        for v in next(csv.reader([line]))
                    }
                except Exception:
                    continue
                if "ticker" in values:
                    header_idx = idx
                    break

            if header_idx is None:
                continue

            # Now parse from the header row onward. Use the python engine
            # with on_bad_lines="skip" so ragged trailing disclaimer rows
            # (which may have a different field count) don't blow up the
            # whole parse.
            df = pd.read_csv(
                StringIO(resp.text),
                skiprows=header_idx,
                dtype=str,
                on_bad_lines="skip",
                engine="python",
            )
            df.columns = [str(c).strip() for c in df.columns]

            ticker_col = next(
                (c for c in df.columns if c.lower() == "ticker"), None
            )
            name_col = next(
                (
                    c for c in df.columns
                    if c.lower() in {"name", "security name"}
                ),
                None,
            )
            weight_col = next(
                (
                    c for c in df.columns
                    if c.lower() in {"weight (%)", "weight"}
                ),
                None,
            )

            if not all([ticker_col, name_col, weight_col]):
                print(
                    f"  [{etf_ticker}] unexpected iShares columns: "
                    f"{list(df.columns)}"
                )
                continue

            df = df[[ticker_col, name_col, weight_col]].copy()
            df.columns = ["ticker", "company", "weight"]
            df["ticker"] = df["ticker"].astype(str).str.strip()

            # Remove cash/summary/non-equity rows.
            df = df[
                ~df["ticker"].str.lower().isin(
                    ["", "nan", "ticker", "cash", "usd", "total"]
                )
            ]

            result = _clean_and_dedup(df, etf_ticker)
            if result is not None and not result.empty:
                print(
                    f"  [{etf_ticker}] iShares holdings date "
                    f"{candidate.isoformat()}"
                )
                return result

        except Exception as e:
            print(
                f"  [{etf_ticker}] iShares {candidate.isoformat()} failed: {e}"
            )

    print(f"  [{etf_ticker}] all iShares date attempts failed — skipping")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CHANGE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_changes(etf: str, today_df) -> list:
    result = supabase.table("holdings") \
        .select("ticker, weight") \
        .eq("etf", etf) \
        .eq("date", YESTERDAY) \
        .execute()
    yesterday_map = {r["ticker"]: float(r["weight"]) for r in (result.data or [])}

    if not yesterday_map:
        print(f"  [{etf}] no yesterday data — first run for this ETF")
        return []

    today_map = dict(zip(today_df["ticker"], today_df["weight"].astype(float)))
    changes = []

    for tkr, weight in today_map.items():
        if tkr not in yesterday_map:
            changes.append({
                "etf": etf, "ticker": tkr, "change_type": "new_position",
                "delta": round(weight, 4),
                "description": f"{etf} opened new position in {tkr}"
            })
        else:
            delta = weight - yesterday_map[tkr]
            if abs(delta) > 0.3:
                verb = "increased" if delta > 0 else "reduced"
                changes.append({
                    "etf": etf, "ticker": tkr,
                    "change_type": "accumulation" if delta > 0 else "reduction",
                    "delta": round(delta, 4),
                    "description": f"{etf} {verb} {tkr} by {abs(round(delta, 2))}%"
                })

    for tkr in yesterday_map:
        if tkr not in today_map:
            changes.append({
                "etf": etf, "ticker": tkr, "change_type": "removed",
                "delta": 0.0, "description": f"{etf} removed {tkr} from portfolio"
            })

    return changes


def generate_multi_etf_signals():
    result = supabase.table("holding_changes") \
        .select("ticker, etf, change_type") \
        .eq("change_type", "accumulation") \
        .gte("created_at", TODAY) \
        .execute()

    from collections import defaultdict
    ticker_etfs: dict = defaultdict(list)
    for row in (result.data or []):
        ticker_etfs[row["ticker"]].append(row["etf"])

    signals = [
        {
            "etf": "MULTI", "ticker": tkr,
            "change_type": "multi_etf_buy",
            "delta": float(len(etfs)),
            "description": f"{len(etfs)} ETFs simultaneously buying {tkr}: {', '.join(etfs)}"
        }
        for tkr, etfs in ticker_etfs.items() if len(etfs) >= 3
    ]

    if signals:
        supabase.table("holding_changes").insert(signals).execute()
        print(f"  ✓ {len(signals)} multi-ETF signals")
    else:
        print("  No multi-ETF signals today")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print(f"AlphaRadar ETL — {TODAY}")
    print("=" * 55)
    success = 0

    # ── ARK core ─────────────────────────────────────────
    for ticker, url in ARK_ETFS.items():
        print(f"\nFetching {ticker} (ARK)...")
        if save_etf(ticker, fetch_ark(ticker, url)):
            success += 1
        time.sleep(1)

    # ── ARKQ fallback ─────────────────────────────────────
    print(f"\nFetching ARKQ (ARK, multi-URL fallback)...")
    if save_etf("ARKQ", fetch_ark_with_fallback("ARKQ", ARKQ_URLS)):
        success += 1
    time.sleep(1)

    # ── Tema ──────────────────────────────────────────────
    for ticker, url in TEMA_ETFS.items():
        print(f"\nFetching {ticker} (Tema)...")
        if save_etf(ticker, fetch_tema(ticker, url)):
            success += 1
        time.sleep(1)

    # ── iShares Active ETFs ─────────────────────────────────
    for ticker, config in ISHARES_ETFS.items():
        print(f"\nFetching {ticker} (iShares Active)...")
        if save_etf(
            ticker,
            fetch_ishares(ticker, config["product_id"])
        ):
            success += 1
        time.sleep(1)

    total = (
        len(ARK_ETFS)
        + 1
        + len(TEMA_ETFS)
        + len(ISHARES_ETFS)
    )
    print(f"\nGenerating cross-ETF signals...")
    generate_multi_etf_signals()
    print(f"\n{'='*55}")
    print(f"Done: {success}/{total} ETFs updated")


if __name__ == "__main__":
    run()
