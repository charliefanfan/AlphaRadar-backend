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
ARK_ETFS = {
    "ARKK": "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKW": "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKG": "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKF": "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
    # ARKQ uses a different filename pattern
    "ARKQ": "https://assets.ark-funds.com/fund-documents/funds-etf-csv/ARK_AUTONOMOUS_TECH_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
}

TODAY     = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; AlphaRadar/1.0)"}

# ARK CSV has NO header row — columns are in this fixed order:
# date | fund | company | ticker | cusip | shares | market_value | weight
ARK_COLS = ["date", "fund", "company", "ticker", "cusip", "shares", "market_value", "weight"]


# ── Fetch ARK CSV ─────────────────────────────────────────────────────────────
def fetch_ark(etf_ticker: str, url: str):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        from io import StringIO

        # No header — assign column names manually
        df = pd.read_csv(StringIO(resp.text), header=None, names=ARK_COLS)

        # Drop rows where ticker looks like a header or is empty
        df = df[df["ticker"].notna()]
        df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]

        # Clean weight: "10.12%" → 10.12
        df["weight"] = (
            df["weight"].astype(str)
            .str.replace("%", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip()
        )
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)

        df["ticker"]  = df["ticker"].astype(str).str.strip().str.upper()
        df["company"] = df["company"].astype(str).str.strip()
        df["etf"]     = etf_ticker
        df["date"]    = TODAY

        result = df[["etf", "ticker", "company", "weight", "date"]]
        result = result[result["ticker"] != "NAN"]
        print(f"  [{etf_ticker}] parsed {len(result)} holdings, sample: {result['ticker'].head(3).tolist()}")
        return result

    except Exception as e:
        print(f"  [{etf_ticker}] fetch error: {e}")
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
        print(f"  [{etf}] no yesterday data — first run, skipping diff")
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
        print(f"  Generated {len(signals)} multi-ETF signals")
    else:
        print("  No multi-ETF signals today")


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print(f"AlphaRadar ETL — {TODAY}")
    print("=" * 50)
    all_changes = []

    for ticker, url in ARK_ETFS.items():
        print(f"Fetching {ticker}...")
        df = fetch_ark(ticker, url)
        if df is not None and not df.empty:
            records = df.to_dict("records")
            for i in range(0, len(records), 100):
                supabase.table("holdings").upsert(records[i:i+100]).execute()
            changes = detect_changes(ticker, df)
            if changes:
                supabase.table("holding_changes").insert(changes).execute()
            all_changes.extend(changes)
            print(f"  {len(df)} holdings saved, {len(changes)} changes detected")
        time.sleep(1)

    print("\nGenerating cross-ETF signals...")
    generate_multi_etf_signals()
    print(f"\nDone. Total changes today: {len(all_changes)}")


if __name__ == "__main__":
    run()
