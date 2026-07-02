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
    "ARKX": f"{ARK_BASE}/ARK_SPACE_EXPLORATION_%26_INNOVATION_ETF_ARKX_HOLDINGS.csv",
    "PRNT": f"{ARK_BASE}/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv",
    "IZRL": f"{ARK_BASE}/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv",
}

# ARKQ — try multiple URL variants (& encoding inconsistent across CDN)
ARKQ_URLS = [
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_AND_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECH_AND_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_AUTONOMOUS_TECHNOLOGY_%2526_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
]

# ── Tema ETFs ─────────────────────────────────────────────────────────────────
# Official CSV URL confirmed from temaetfs.com/nasa page source
TEMA_ETFS = {
    "NASA": "https://temaetfs.com/hubfs/Website/Holdings/NASA-holdings.csv",
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
    Tema CSV: standard header row with columns like
    Ticker, Name, Weight (%), Shares, Market Value, ...
    Detect ticker/name/weight columns dynamically.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        from io import StringIO

        # The file may have a metadata header; find the real CSV header row
        lines = resp.text.splitlines()
        header_idx = 0
        for i, line in enumerate(lines):
            low = line.strip().lower()
            if "ticker" in low or "symbol" in low:
                header_idx = i
                break

        df = pd.read_csv(StringIO("\n".join(lines[header_idx:])))
        df.columns = [c.strip().lower() for c in df.columns]

        ticker_col = next((c for c in df.columns if "ticker" in c or c == "symbol"), None)
        name_col   = next((c for c in df.columns if "name" in c or "company" in c or "security" in c), None)
        weight_col = next((c for c in df.columns if "weight" in c or "% of" in c or "pct" in c), None)

        if not all([ticker_col, name_col, weight_col]):
            print(f"  [{etf_ticker}] ✗ unexpected columns: {list(df.columns)}")
            return None

        df = df[[ticker_col, name_col, weight_col]].copy()
        df.columns = ["ticker", "company", "weight"]
        df = df.dropna(subset=["ticker"])
        df = df[~df["ticker"].astype(str).str.strip().str.lower().isin(
            ["ticker", "nan", "", "-", "cash", "usd"])]
        return _clean_and_dedup(df, etf_ticker)
    except Exception as e:
        print(f"  [{etf_ticker}] ✗ {e}")
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

    total = len(ARK_ETFS) + 1 + len(TEMA_ETFS)
    print(f"\nGenerating cross-ETF signals...")
    generate_multi_etf_signals()
    print(f"\n{'='*55}")
    print(f"Done: {success}/{total} ETFs updated")


if __name__ == "__main__":
    run()
