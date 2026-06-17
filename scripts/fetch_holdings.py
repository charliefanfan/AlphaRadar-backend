
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

# # ── ETF sources ───────────────────────────────────────────────────────────────
# ARK_BASE = "https://assets.ark-funds.com/fund-documents/funds-etf-csv"

# # All ARK ETFs with confirmed CSV URLs
# ARK_ETFS = {
#     # ── Core active ETFs ──────────────────────────────────────────────────────
#     "ARKK": f"{ARK_BASE}/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
#     "ARKW": f"{ARK_BASE}/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
#     "ARKG": f"{ARK_BASE}/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
#     "ARKF": f"{ARK_BASE}/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
#     "ARKQ": f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     "ARKX": f"{ARK_BASE}/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv",
#     # ── Indexed ETFs ─────────────────────────────────────────────────────────
#     "PRNT": f"{ARK_BASE}/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv",
#     "IZRL": f"{ARK_BASE}/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv",
# }

# TODAY     = date.today().isoformat()
# YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
# HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; AlphaRadar/1.0)"}

# # ARK CSV format: no header row, fixed columns
# ARK_COLS = ["date", "fund", "company", "ticker", "cusip", "shares", "market_value", "weight"]


# # ── Fetch one ARK ETF ─────────────────────────────────────────────────────────
# def fetch_ark(etf_ticker: str, url: str):
#     try:
#         resp = requests.get(url, headers=HEADERS, timeout=30)
#         resp.raise_for_status()
#         from io import StringIO

#         df = pd.read_csv(StringIO(resp.text), header=None, names=ARK_COLS)
#         df = df[df["ticker"].notna()]
#         df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]

#         # Clean weight: "10.12%" → 10.12
#         df["weight"] = (
#             df["weight"].astype(str)
#             .str.replace("%", "", regex=False)
#             .str.replace(",", "", regex=False)
#             .str.strip()
#         )
#         df["weight"]  = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
#         df["ticker"]  = df["ticker"].astype(str).str.strip().str.upper()
#         df["company"] = df["company"].astype(str).str.strip()
#         df["etf"]     = etf_ticker
#         df["date"]    = TODAY

#         result = df[["etf", "ticker", "company", "weight", "date"]]
#         result = result[result["ticker"] != "NAN"]
#         print(f"  [{etf_ticker}] {len(result)} holdings — top: {result['ticker'].head(3).tolist()}")
#         return result

#     except Exception as e:
#         print(f"  [{etf_ticker}] ✗ {e}")
#         return None


# # ── Detect changes vs yesterday ───────────────────────────────────────────────
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
#                 "etf": etf, "ticker": tkr,
#                 "change_type": "new_position",
#                 "delta": round(weight, 4),
#                 "description": f"{etf} opened new position in {tkr}"
#             })
#         else:
#             delta = weight - yesterday_map[tkr]
#             if abs(delta) > 0.3:
#                 changes.append({
#                     "etf": etf, "ticker": tkr,
#                     "change_type": "accumulation" if delta > 0 else "reduction",
#                     "delta": round(delta, 4),
#                     "description": f"{etf} {'increased' if delta > 0 else 'reduced'} {tkr} by {abs(round(delta, 2))}%"
#                 })

#     for tkr in yesterday_map:
#         if tkr not in today_map:
#             changes.append({
#                 "etf": etf, "ticker": tkr,
#                 "change_type": "removed",
#                 "delta": 0.0,
#                 "description": f"{etf} removed {tkr} from portfolio"
#             })

#     return changes


# # ── Multi-ETF cross signal ────────────────────────────────────────────────────
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

#     signals = []
#     for tkr, etfs in ticker_etfs.items():
#         if len(etfs) >= 3:
#             signals.append({
#                 "etf": "MULTI", "ticker": tkr,
#                 "change_type": "multi_etf_buy",
#                 "delta": float(len(etfs)),
#                 "description": f"{len(etfs)} ETFs simultaneously buying {tkr}: {', '.join(etfs)}"
#             })

#     if signals:
#         supabase.table("holding_changes").insert(signals).execute()
#         print(f"  ✓ {len(signals)} multi-ETF signals generated")
#     else:
#         print("  No multi-ETF signals today")


# # ── Main ──────────────────────────────────────────────────────────────────────
# def run():
#     print(f"AlphaRadar ETL — {TODAY}")
#     print("=" * 55)
#     all_changes = []
#     success = 0

#     for ticker, url in ARK_ETFS.items():
#         print(f"\nFetching {ticker}...")
#         df = fetch_ark(ticker, url)
#         if df is not None and not df.empty:
#             records = df.to_dict("records")
#             for i in range(0, len(records), 100):
#                 supabase.table("holdings").upsert(records[i:i+100]).execute()
#             changes = detect_changes(ticker, df)
#             if changes:
#                 supabase.table("holding_changes").insert(changes).execute()
#             all_changes.extend(changes)
#             print(f"  ✓ saved, {len(changes)} changes")
#             success += 1
#         time.sleep(1)

#     print(f"\nGenerating cross-ETF signals...")
#     generate_multi_etf_signals()
#     print(f"\n{'='*55}")
#     print(f"Done: {success}/{len(ARK_ETFS)} ETFs · {len(all_changes)} changes today")


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

# ── ETF sources ───────────────────────────────────────────────────────────────
ARK_BASE = "https://assets.ark-funds.com/fund-documents/funds-etf-csv"

# All ARK ETFs with confirmed CSV URLs
ARK_ETFS = {
    # ── Core active ETFs ──────────────────────────────────────────────────────
    "ARKK": f"{ARK_BASE}/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKW": f"{ARK_BASE}/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKG": f"{ARK_BASE}/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKF": f"{ARK_BASE}/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
    "ARKX": f"{ARK_BASE}/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv",
    # ARKQ URL currently returns 404 from ARK — re-enable once confirmed
    # "ARKQ": f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    # ── Indexed ETFs ─────────────────────────────────────────────────────────
    "PRNT": f"{ARK_BASE}/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv",
    "IZRL": f"{ARK_BASE}/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv",
}

# iShares (BlackRock) active ETFs — different CSV format, fetched via ajax endpoint
# URL pattern: https://www.ishares.com/us/products/{fund_id}/{fund_slug}/{asset_id}.ajax?fileType=csv&fileName={TICKER}_holdings&dataType=fund
ISHARES_ETFS = {
    "IETC": {
        "url": "https://www.ishares.com/us/products/292425/ishares-us-tech-independence-focused-etf/1467271812596.ajax?fileType=csv&fileName=IETC_holdings&dataType=fund",
        "name": "iShares US Tech Independence Focused ETF",
    },
}


TODAY     = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; AlphaRadar/1.0)"}

# ARK CSV format: no header row, fixed columns
ARK_COLS = ["date", "fund", "company", "ticker", "cusip", "shares", "market_value", "weight"]


# ── Fetch one ARK ETF ─────────────────────────────────────────────────────────
def fetch_ark(etf_ticker: str, url: str):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        from io import StringIO

        df = pd.read_csv(StringIO(resp.text), header=None, names=ARK_COLS)
        df = df[df["ticker"].notna()]
        df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]

        # Clean weight: "10.12%" → 10.12
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
        result = result[result["ticker"] != "NAN"]

        # De-duplicate on (etf, ticker, date) — keep the row with highest weight
        # if the same ticker appears twice (e.g. share classes, ADRs)
        before = len(result)
        result = (result
                  .sort_values("weight", ascending=False)
                  .drop_duplicates(subset=["etf", "ticker", "date"], keep="first"))
        if len(result) < before:
            print(f"  [{etf_ticker}] removed {before - len(result)} duplicate ticker rows")

        print(f"  [{etf_ticker}] {len(result)} holdings — top: {result['ticker'].head(3).tolist()}")
        return result

    except Exception as e:
        print(f"  [{etf_ticker}] ✗ {e}")
        return None


# ── Fetch one iShares ETF ─────────────────────────────────────────────────────
def fetch_ishares(etf_ticker: str, url: str):
    """
    iShares CSV format is different from ARK:
    - First several rows are fund metadata (fund name, as-of date, etc.) — must be skipped
    - Then a header row: Ticker, Name, Sector, Asset Class, Market Value, Weight (%), ...
    - Then a footer with disclaimers — must be filtered out
    The skiprows count can shift, so we detect the header row dynamically
    by searching for "Ticker" in the raw text instead of hardcoding a row number.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        from io import StringIO

        lines = resp.text.splitlines()

        # Find the header row dynamically (the row that starts with "Ticker")
        header_idx = None
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("ticker,") or line.strip().lower().startswith('"ticker",'):
                header_idx = i
                break

        if header_idx is None:
            print(f"  [{etf_ticker}] ✗ could not find header row in iShares CSV")
            return None

        csv_text = "\n".join(lines[header_idx:])
        df = pd.read_csv(StringIO(csv_text))
        df.columns = [c.strip().lower() for c in df.columns]

        ticker_col = next((c for c in df.columns if c == "ticker"), None)
        name_col   = next((c for c in df.columns if "name" in c), None)
        weight_col = next((c for c in df.columns if "weight" in c), None)

        if not all([ticker_col, name_col, weight_col]):
            print(f"  [{etf_ticker}] ✗ unexpected columns: {list(df.columns)}")
            return None

        df = df[[ticker_col, name_col, weight_col]].copy()
        df.columns = ["ticker", "company", "weight"]
        df = df.dropna(subset=["ticker"])

        # Drop footer rows (cash, disclaimers, blanks) — real tickers don't contain these
        bad_values = ["ticker", "nan", "", "-", "cash", "usd"]
        df = df[~df["ticker"].astype(str).str.strip().str.lower().isin(bad_values)]

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
        result = result[(result["ticker"] != "NAN") & (result["weight"] > 0)]

        before = len(result)
        result = (result
                  .sort_values("weight", ascending=False)
                  .drop_duplicates(subset=["etf", "ticker", "date"], keep="first"))
        if len(result) < before:
            print(f"  [{etf_ticker}] removed {before - len(result)} duplicate ticker rows")

        print(f"  [{etf_ticker}] {len(result)} holdings — top: {result['ticker'].head(3).tolist()}")
        return result

    except Exception as e:
        print(f"  [{etf_ticker}] ✗ {e}")
        return None


# ── Detect changes vs yesterday ───────────────────────────────────────────────
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
                "etf": etf, "ticker": tkr,
                "change_type": "new_position",
                "delta": round(weight, 4),
                "description": f"{etf} opened new position in {tkr}"
            })
        else:
            delta = weight - yesterday_map[tkr]
            if abs(delta) > 0.3:
                changes.append({
                    "etf": etf, "ticker": tkr,
                    "change_type": "accumulation" if delta > 0 else "reduction",
                    "delta": round(delta, 4),
                    "description": f"{etf} {'increased' if delta > 0 else 'reduced'} {tkr} by {abs(round(delta, 2))}%"
                })

    for tkr in yesterday_map:
        if tkr not in today_map:
            changes.append({
                "etf": etf, "ticker": tkr,
                "change_type": "removed",
                "delta": 0.0,
                "description": f"{etf} removed {tkr} from portfolio"
            })

    return changes


# ── Multi-ETF cross signal ────────────────────────────────────────────────────
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

    signals = []
    for tkr, etfs in ticker_etfs.items():
        if len(etfs) >= 3:
            signals.append({
                "etf": "MULTI", "ticker": tkr,
                "change_type": "multi_etf_buy",
                "delta": float(len(etfs)),
                "description": f"{len(etfs)} ETFs simultaneously buying {tkr}: {', '.join(etfs)}"
            })

    if signals:
        supabase.table("holding_changes").insert(signals).execute()
        print(f"  ✓ {len(signals)} multi-ETF signals generated")
    else:
        print("  No multi-ETF signals today")


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print(f"AlphaRadar ETL — {TODAY}")
    print("=" * 55)
    all_changes = []
    success = 0
    total = len(ARK_ETFS) + len(ISHARES_ETFS)

    # ARK ETFs
    for ticker, url in ARK_ETFS.items():
        print(f"\nFetching {ticker} (ARK)...")
        df = fetch_ark(ticker, url)
        if df is not None and not df.empty:
            records = df.to_dict("records")
            for i in range(0, len(records), 100):
                supabase.table("holdings").upsert(records[i:i+100]).execute()
            changes = detect_changes(ticker, df)
            if changes:
                supabase.table("holding_changes").insert(changes).execute()
            all_changes.extend(changes)
            print(f"  ✓ saved, {len(changes)} changes")
            success += 1
        time.sleep(1)

    # iShares ETFs
    for ticker, info in ISHARES_ETFS.items():
        print(f"\nFetching {ticker} (iShares)...")
        df = fetch_ishares(ticker, info["url"])
        if df is not None and not df.empty:
            records = df.to_dict("records")
            for i in range(0, len(records), 100):
                supabase.table("holdings").upsert(records[i:i+100]).execute()
            changes = detect_changes(ticker, df)
            if changes:
                supabase.table("holding_changes").insert(changes).execute()
            all_changes.extend(changes)
            print(f"  ✓ saved, {len(changes)} changes")
            success += 1
        time.sleep(1)

    print(f"\nGenerating cross-ETF signals...")
    generate_multi_etf_signals()
    print(f"\n{'='*55}")
    print(f"Done: {success}/{total} ETFs · {len(all_changes)} changes today")


if __name__ == "__main__":
    run()
