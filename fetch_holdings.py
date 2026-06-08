import requests
import pandas as pd
from datetime import date, timedelta
from supabase import create_client
import os
import time

# ── Supabase client ──────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── ETF sources ───────────────────────────────────────────────────────────────
ARK_ETFS = {
    "ARKK": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKW": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKG": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKF": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
    "ARKQ": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
}

YIELDMAX_ETFS = {
    "TSLY": "https://yieldmaxetfs.com/our-etfs/tsly/",
    "NVDY": "https://yieldmaxetfs.com/our-etfs/nvdy/",
    "CONY": "https://yieldmaxetfs.com/our-etfs/cony/",
}

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlphaRadar/1.0)"}


# ── Fetch ARK CSV ─────────────────────────────────────────────────────────────
def fetch_ark(ticker: str, url: str) -> pd.DataFrame | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text), skiprows=1)
        # ARK CSV columns vary slightly — normalise
        df.columns = [c.strip().lower() for c in df.columns]
        # find the right columns
        ticker_col = next((c for c in df.columns if "ticker" in c), None)
        company_col = next((c for c in df.columns if "company" in c), None)
        weight_col = next((c for c in df.columns if "weight" in c), None)
        if not all([ticker_col, company_col, weight_col]):
            print(f"  [{ticker}] unexpected CSV columns: {list(df.columns)}")
            return None
        df = df[[ticker_col, company_col, weight_col]].copy()
        df.columns = ["ticker", "company", "weight"]
        df = df.dropna(subset=["ticker"])
        df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
        df["etf"] = ticker
        df["date"] = TODAY
        return df[df["ticker"] != "NAN"]
    except Exception as e:
        print(f"  [{ticker}] fetch error: {e}")
        return None


# ── Detect holding changes vs yesterday ──────────────────────────────────────
def detect_changes(etf: str, today_df: pd.DataFrame) -> list[dict]:
    result = supabase.table("holdings") \
        .select("ticker, weight") \
        .eq("etf", etf) \
        .eq("date", YESTERDAY) \
        .execute()
    yesterday_map = {r["ticker"]: float(r["weight"]) for r in (result.data or [])}

    if not yesterday_map:
        print(f"  [{etf}] no yesterday data — skipping change detection (first run?)")
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
            if abs(delta) > 0.3:          # only flag moves > 0.3%
                changes.append({
                    "etf": etf, "ticker": tkr,
                    "change_type": "accumulation" if delta > 0 else "reduction",
                    "delta": round(delta, 4),
                    "description": f"{etf} {'increased' if delta > 0 else 'reduced'} {tkr} by {abs(round(delta,2))}%"
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


# ── Upsert holdings snapshot ──────────────────────────────────────────────────
def save_holdings(df: pd.DataFrame):
    records = df[["etf", "ticker", "company", "weight", "date"]].to_dict("records")
    # upsert in batches of 100
    batch_size = 100
    for i in range(0, len(records), batch_size):
        supabase.table("holdings").upsert(records[i:i+batch_size]).execute()


# ── Save changes ──────────────────────────────────────────────────────────────
def save_changes(changes: list[dict]):
    if changes:
        supabase.table("holding_changes").insert(changes).execute()


# ── Multi-ETF signal: same stock bought by 3+ ETFs on the same day ────────────
def generate_multi_etf_signals():
    result = supabase.table("holding_changes") \
        .select("ticker, etf, change_type") \
        .eq("change_type", "accumulation") \
        .gte("created_at", TODAY) \
        .execute()

    from collections import defaultdict
    ticker_etfs: dict[str, list] = defaultdict(list)
    for row in (result.data or []):
        ticker_etfs[row["ticker"]].append(row["etf"])

    signals = []
    for tkr, etfs in ticker_etfs.items():
        if len(etfs) >= 3:
            signals.append({
                "etf": "MULTI",
                "ticker": tkr,
                "change_type": "multi_etf_buy",
                "delta": float(len(etfs)),
                "description": f"{len(etfs)} ETFs simultaneously buying {tkr}: {', '.join(etfs)}"
            })

    if signals:
        save_changes(signals)
        print(f"  Generated {len(signals)} multi-ETF signals")


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print(f"AlphaRadar ETL — {TODAY}")
    print("=" * 50)

    all_changes = []

    # ARK ETFs
    for ticker, url in ARK_ETFS.items():
        print(f"Fetching {ticker}...")
        df = fetch_ark(ticker, url)
        if df is not None and not df.empty:
            save_holdings(df)
            changes = detect_changes(ticker, df)
            save_changes(changes)
            all_changes.extend(changes)
            print(f"  {len(df)} holdings saved, {len(changes)} changes detected")
        time.sleep(1)   # be polite to ARK's servers

    # Multi-ETF cross signals
    print("\nGenerating cross-ETF signals...")
    generate_multi_etf_signals()

    print(f"\nDone. Total changes today: {len(all_changes)}")


if __name__ == "__main__":
    run()
