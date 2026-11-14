# import csv
# import os
# import re
# import sys
# import time
# from collections import defaultdict
# from datetime import date, timedelta
# from io import BytesIO, StringIO
# from urllib.parse import urljoin, urlparse

# import pandas as pd
# import requests
# from supabase import create_client


# # ── Supabase client ───────────────────────────────────────────────────────────

# SUPABASE_URL = os.environ["SUPABASE_URL"]
# SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# # ── Constants ─────────────────────────────────────────────────────────────────

# TODAY = date.today().isoformat()

# HEADERS = {
#     "User-Agent": (
#         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
#         "AppleWebKit/537.36 (KHTML, like Gecko) "
#         "Chrome/150.0.0.0 Safari/537.36"
#     ),
#     "Accept-Language": "en-US,en;q=0.9",
# }

# # Bloomberg-style US exchange suffixes (RKLB UQ -> RKLB).
# # Foreign suffixes (FP, GR, LN ...) are intentionally NOT stripped.
# US_EXCHANGE_SUFFIXES = {"UN", "UQ", "UW", "UR", "UA", "UP", "US"}

# DATE_RE = re.compile(
#     r"\d{4}-\d{2}-\d{2}"
#     r"|\d{1,2}/\d{1,2}/\d{4}"
#     r"|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}"
# )


# # ── ARK ETFs ──────────────────────────────────────────────────────────────────

# ARK_BASE = "https://assets.ark-funds.com/fund-documents/funds-etf-csv"

# ARK_COLS = [
#     "date", "fund", "company", "ticker",
#     "cusip", "shares", "market_value", "weight",
# ]

# ARK_ETFS = {
#     "ARKK": f"{ARK_BASE}/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
#     "ARKW": f"{ARK_BASE}/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
#     "ARKG": f"{ARK_BASE}/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
#     "ARKF": f"{ARK_BASE}/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
#     "ARKX": f"{ARK_BASE}/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv",
#     "PRNT": f"{ARK_BASE}/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv",
#     "IZRL": f"{ARK_BASE}/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv",
# }

# ARKQ_URLS = [
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECH._%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARK_AUTONOMOUS_TECH_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
#     f"{ARK_BASE}/ARKQ_HOLDINGS.csv",
# ]


# # ── Tema ETFs ─────────────────────────────────────────────────────────────────

# TEMA_ETFS = {
#     "NASA": "https://temaetfs.com/hubfs/Website/Holdings/NASA-holdings.csv",
# }


# # ── iShares Active ETFs ───────────────────────────────────────────────────────

# ISHARES_ETFS = {
#     "BAI": {"product_id": "339081"},
#     "TEK": {"product_id": "339083"},
#     "DYNF": {"product_id": "307283"},
#     "THRO": {"product_id": "325384"},
#     "INRO": {"product_id": "336430"},
#     "BMED": {"product_id": "316007"},
#     "IDYN": {"product_id": "345128"},
# }


# # ── Additional actively managed ETFs ──────────────────────────────────────────

# ADDITIONAL_ETFS = {
#     "CGGR": "capital",
#     "CGDV": "capital",
#     "AVUV": "avantis",
#     "AVLV": "avantis",
#     "JGRO": "jpmorgan",
#     "JAVA": "jpmorgan",
# }

# AVANTIS_SLUGS = {
#     "AVUV": "avantis-us-small-cap-value-etf",
#     "AVLV": "avantis-us-large-cap-value-etf",
# }


# # ─────────────────────────────────────────────────────────────────────────────
# # SHARED HELPERS
# # ─────────────────────────────────────────────────────────────────────────────


# def _norm_ticker(raw) -> str:
#     """'RKLB UQ' -> 'RKLB'. Only strips US exchange suffixes."""
#     t = str(raw).strip().upper()
#     parts = t.split()
#     if len(parts) >= 2 and parts[-1] in US_EXCHANGE_SUFFIXES:
#         return " ".join(parts[:-1])
#     return t


# def _parse_date(value):
#     """Return ISO date string, or None if missing / implausible."""
#     if value is None:
#         return None
#     s = str(value).strip()
#     if s.lower() in ("", "-", "nan", "nat", "none"):
#         return None
#     try:
#         d = pd.to_datetime(s, errors="coerce")
#     except Exception:
#         return None
#     if pd.isna(d):
#         return None
#     d = d.date()
#     lo = date.today() - timedelta(days=14)
#     hi = date.today() + timedelta(days=5)
#     return d.isoformat() if lo <= d <= hi else None


# def _asof_from_series(series):
#     """Most common valid date found in a column of date-like values."""
#     vals = [_parse_date(v) for v in series.dropna().astype(str)]
#     vals = [v for v in vals if v]
#     if not vals:
#         return None
#     return max(set(vals), key=vals.count)


# def _find_asof_in_frame(raw, max_rows=40):
#     """Look for an 'as of <date>' cell in the rows above the table."""
#     for idx in range(min(len(raw), max_rows)):
#         cells = [str(v).strip() for v in raw.iloc[idx].tolist()]
#         cells = [c for c in cells if c and c.lower() not in ("nan", "nat", "none")]
#         for j, cell in enumerate(cells):
#             if "as of" in cell.lower():
#                 for cand in [cell] + cells[j + 1:j + 3]:
#                     m = DATE_RE.search(cand)
#                     if m:
#                         d = _parse_date(m.group(0))
#                         if d:
#                             return d
#     return None


# def _clean_and_dedup(df, etf_ticker, as_of=None):
#     """Clean weight column, tag etf/date, normalize tickers, deduplicate."""

#     df["weight"] = (
#         df["weight"].astype(str)
#         .str.replace("%", "", regex=False)
#         .str.replace(",", "", regex=False)
#         .str.strip()
#     )
#     df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)

#     df["ticker"] = df["ticker"].astype(str).str.strip().str.upper().map(_norm_ticker)
#     df["company"] = df["company"].astype(str).str.strip()

#     df["etf"] = etf_ticker
#     df["date"] = as_of or TODAY

#     result = df[["etf", "ticker", "company", "weight", "date"]]
#     result = result[~result["ticker"].isin(["NAN", "", "-", "TICKER"])]
#     result = result[result["weight"] > 0]

#     before = len(result)

#     result = (
#         result.sort_values("weight", ascending=False)
#         .drop_duplicates(subset=["etf", "ticker", "date"], keep="first")
#     )

#     if len(result) < before:
#         print(f"  [{etf_ticker}] removed {before - len(result)} duplicate rows")

#     print(
#         f"  [{etf_ticker}] {len(result)} holdings — top: "
#         f"{result['ticker'].head(3).tolist()}"
#     )
#     print(
#         f"  [{etf_ticker}] snapshot date: {as_of or TODAY}"
#         + ("" if as_of else "  (no as-of date in file, using today)")
#     )

#     return result


# def _read_holdings_bytes(content: bytes, etf: str):
#     """
#     Read an XLSX/CSV holdings file, locate the header row containing a ticker
#     column, and return (table, as_of_date_or_None).
#     """

#     if content[:2] == b"PK":
#         raw = pd.read_excel(BytesIO(content), header=None)
#     elif b"<html" not in content[:500].lower():
#         rows = list(csv.reader(StringIO(content.decode("utf-8-sig"))))
#         width = max((len(r) for r in rows), default=0)
#         raw = pd.DataFrame([r + [""] * (width - len(r)) for r in rows])
#     else:
#         raise ValueError(f"{etf}: HTML received instead of holdings file")

#     for idx in range(min(len(raw), 40)):
#         vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist()]
#         if any(v in ("ticker", "symbol", "security ticker") for v in vals):
#             body = raw.iloc[idx + 1:].copy()
#             body.columns = raw.iloc[idx].tolist()
#             return body, _find_asof_in_frame(raw.iloc[:idx])

#     raise ValueError(f"{etf}: header row with ticker not found")


# def _new_number(series):
#     return pd.to_numeric(
#         series.astype(str)
#         .str.replace(r"[$,%]", "", regex=True)
#         .str.replace(",", "", regex=False)
#         .str.strip(),
#         errors="coerce",
#     )


# def _normalize_extra_holdings(raw, etf, source_date=None):
#     """Convert issuer data to the existing Supabase schema without inventing data."""

#     if raw is None or raw.empty:
#         return None

#     df = raw.copy()
#     df.columns = [
#         str(c).strip().lower().replace("\n", " ") for c in df.columns
#     ]

#     aliases = {
#         "ticker": ["ticker", "symbol", "security ticker"],
#         "company": [
#             "security name", "security description", "company",
#             "name", "holding", "description",
#         ],
#         "weight": [
#             "percent of net assets", "% of net assets", "% of assets",
#             "weight", "weight (%)", "portfolio weight", "percent of assets",
#         ],
#     }

#     mapping = {}
#     for target, options in aliases.items():
#         for option in options:
#             if option in df.columns:
#                 mapping[target] = option
#                 break

#     if len(mapping) != 3:
#         raise ValueError(
#             f"{etf}: required columns missing; received {list(df.columns)}"
#         )

#     df = df[[mapping[x] for x in ("ticker", "company", "weight")]].copy()
#     df.columns = ["ticker", "company", "weight"]

#     df["ticker"] = df["ticker"].astype(str).str.upper().str.strip().map(_norm_ticker)
#     df["company"] = df["company"].astype(str).str.strip()
#     df["weight"] = _new_number(df["weight"])

#     df = df[df["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", na=False)]
#     df = df[~df["ticker"].isin(["CASH", "USD", "TOTAL", "NAN"])]
#     df = df[df["weight"].notna() & (df["weight"] > 0)]
#     df = df.sort_values("weight", ascending=False)
#     df = df.drop_duplicates(subset=["ticker"], keep="first")

#     if len(df) < 5 or df["weight"].sum() > 125:
#         raise ValueError(
#             f"{etf}: suspicious holdings: {len(df)} rows, "
#             f"weight sum {df['weight'].sum():.2f}"
#         )

#     df["etf"] = etf
#     df["date"] = source_date or TODAY

#     print(
#         f"  [{etf}] {len(df)} holdings, snapshot date: {df['date'].iloc[0]}"
#         + ("" if source_date else "  (no as-of date in file, using today)")
#     )

#     return df[["etf", "ticker", "company", "weight", "date"]]


# # ─────────────────────────────────────────────────────────────────────────────
# # SNAPSHOT STORAGE / CHANGE DETECTION
# # ─────────────────────────────────────────────────────────────────────────────


# def _load_snapshot(etf: str, snap_date: str) -> dict:
#     res = (
#         supabase.table("holdings")
#         .select("ticker,weight")
#         .eq("etf", etf)
#         .eq("date", snap_date)
#         .execute()
#     )
#     out = {}
#     for r in res.data or []:
#         t = _norm_ticker(r["ticker"])
#         out[t] = max(float(r["weight"]), out.get(t, 0.0))
#     return out


# def _load_prev_snapshot(etf: str, snap_date: str):
#     latest = (
#         supabase.table("holdings")
#         .select("date")
#         .eq("etf", etf)
#         .lt("date", snap_date)
#         .order("date", desc=True)
#         .limit(1)
#         .execute()
#     )
#     if not latest.data:
#         return None, {}
#     prev_date = latest.data[0]["date"]
#     return prev_date, _load_snapshot(etf, prev_date)


# def _same_weights(a: dict, b: dict) -> bool:
#     if a.keys() != b.keys():
#         return False
#     return all(abs(a[k] - b[k]) < 1e-4 for k in a)


# def _diff_snapshots(etf: str, old: dict, new: dict) -> list:

#     if not old:
#         return []

#     out = []

#     for ticker, weight in new.items():
#         if ticker not in old:
#             out.append({
#                 "etf": etf,
#                 "ticker": ticker,
#                 "change_type": "new_position",
#                 "delta": round(weight, 4),
#                 "description": f"{etf} added {ticker} to reported holdings",
#             })
#         elif abs(weight - old[ticker]) > 0.3:
#             delta = round(weight - old[ticker], 4)
#             out.append({
#                 "etf": etf,
#                 "ticker": ticker,
#                 "change_type": "accumulation" if delta > 0 else "reduction",
#                 "delta": delta,
#                 "description": (
#                     f"{etf} {ticker} portfolio weight changed "
#                     f"{delta:+.2f} percentage points (not verified trades)"
#                 ),
#             })

#     for ticker in old.keys() - new.keys():
#         out.append({
#             "etf": etf,
#             "ticker": ticker,
#             "change_type": "removed",
#             "delta": 0.0,
#             "description": f"{etf} no longer reports {ticker}",
#         })

#     return out


# def save_etf(ticker: str, df) -> str:
#     """Returns 'saved', 'unchanged' or 'failed'."""

#     if df is None or df.empty:
#         return "failed"

#     snap_date = str(df["date"].iloc[0])
#     new = dict(zip(df["ticker"], df["weight"].astype(float)))

#     # 1) this snapshot date is already stored with identical data
#     cur = _load_snapshot(ticker, snap_date)
#     if cur and _same_weights(cur, new):
#         print(f"  = {snap_date} already stored, identical — nothing to do")
#         return "unchanged"

#     # 2) identical to the previous snapshot: issuer file not updated yet
#     prev_date, old = _load_prev_snapshot(ticker, snap_date)
#     if old and _same_weights(old, new):
#         print(f"  = identical to {prev_date}; issuer has not updated — skipping")
#         return "unchanged"

#     changes = _diff_snapshots(ticker, old, new)

#     # 3) same date but different content: replace that snapshot cleanly
#     if cur:
#         print(f"  ~ {snap_date} already stored but differs — replacing")
#         supabase.table("holdings").delete() \
#             .eq("etf", ticker).eq("date", snap_date).execute()
#         supabase.table("holding_changes").delete() \
#             .eq("etf", ticker).gte("created_at", TODAY).execute()

#     records = df.to_dict("records")

#     for i in range(0, len(records), 100):
#         supabase.table("holdings").upsert(records[i:i + 100]).execute()

#     if changes:
#         supabase.table("holding_changes").insert(changes).execute()

#     print(
#         f"  ✓ saved snapshot {snap_date}, {len(changes)} changes detected "
#         f"(vs {prev_date or 'no earlier snapshot'})"
#     )

#     return "saved"


# # ─────────────────────────────────────────────────────────────────────────────
# # ARK
# # ─────────────────────────────────────────────────────────────────────────────


# def _parse_ark_text(text: str, etf_ticker: str):
#     """ARK CSV: no header row, fixed 8-column format.
#     The date column is the NEXT trading day (per ARK's help center)."""

#     df = pd.read_csv(StringIO(text), header=None, names=ARK_COLS)

#     df = df[df["ticker"].notna()]
#     df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]

#     as_of = _asof_from_series(df["date"])

#     return _clean_and_dedup(
#         df[["ticker", "company", "weight"]].copy(), etf_ticker, as_of
#     )


# def fetch_ark(etf_ticker: str, url: str):

#     try:
#         resp = requests.get(url, headers=HEADERS, timeout=30)
#         resp.raise_for_status()
#         return _parse_ark_text(resp.text, etf_ticker)

#     except Exception as e:
#         print(f"  [{etf_ticker}] ✗ {e}")
#         return None


# def fetch_ark_with_fallback(etf_ticker: str, urls: list):
#     """Try multiple ARK URLs."""

#     for i, url in enumerate(urls):

#         try:
#             resp = requests.get(url, headers=HEADERS, timeout=30)

#             if resp.status_code == 200:
#                 print(f"  [{etf_ticker}] variant {i + 1} OK")
#                 return _parse_ark_text(resp.text, etf_ticker)

#             print(f"  [{etf_ticker}] variant {i + 1} → HTTP {resp.status_code}")

#         except Exception as e:
#             print(f"  [{etf_ticker}] variant {i + 1} ✗ {e}")

#     print(f"  [{etf_ticker}] all variants failed — skipping")
#     return None


# # ─────────────────────────────────────────────────────────────────────────────
# # TEMA
# # ─────────────────────────────────────────────────────────────────────────────


# def fetch_tema(etf_ticker: str, url: str):
#     """
#     Tema CSV columns: holdings_date, ticker, cusip, proper_name, shares,
#     market_value, percent_of_nav, is_cash, country, sector
#     """

#     try:
#         resp = requests.get(url, headers=HEADERS, timeout=30)
#         resp.raise_for_status()

#         df = pd.read_csv(StringIO(resp.text))
#         df.columns = [c.strip().lower() for c in df.columns]

#         ticker_col = next((c for c in df.columns if "ticker" in c), None)

#         name_col = next(
#             (
#                 c for c in df.columns
#                 if c == "proper_name" or "name" in c or "company" in c
#             ),
#             None,
#         )

#         weight_col = next(
#             (
#                 c for c in df.columns
#                 if c == "percent_of_nav"
#                 or "weight" in c or "percent" in c or "nav" in c
#             ),
#             None,
#         )

#         date_col = next(
#             (c for c in df.columns if c == "holdings_date" or "date" in c),
#             None,
#         )

#         if not all([ticker_col, name_col, weight_col]):
#             print(
#                 f"  [{etf_ticker}] ✗ unexpected columns: {list(df.columns)}"
#             )
#             return None

#         as_of = _asof_from_series(df[date_col]) if date_col else None

#         df = df[[ticker_col, name_col, weight_col]].copy()
#         df.columns = ["ticker", "company", "weight"]

#         df = df.dropna(subset=["ticker"])
#         df = df[
#             ~df["ticker"].astype(str).str.strip().str.lower()
#             .isin(["ticker", "nan", "", "-", "cash", "usd"])
#         ]

#         return _clean_and_dedup(df, etf_ticker, as_of)

#     except Exception as e:
#         print(f"  [{etf_ticker}] ✗ {e}")
#         return None


# # ─────────────────────────────────────────────────────────────────────────────
# # iSHARES
# # ─────────────────────────────────────────────────────────────────────────────


# def fetch_ishares(etf_ticker: str, product_id: str):
#     """
#     iShares holdings downloader.
#     1. Direct latest-holdings.csv URL.
#     2. Fallback: legacy .ajax endpoint with dated lookback.
#     The 'Fund Holdings as of' line above the table is used as snapshot date.
#     """

#     latest_csv_url = (
#         f"https://www.ishares.com/us/products/"
#         f"{product_id}/holdings/latest-holdings.csv"
#     )
#     legacy_endpoint = (
#         f"https://www.ishares.com/us/products/"
#         f"{product_id}/holdings/1467271812596.ajax"
#     )
#     product_page = f"https://www.ishares.com/us/products/{product_id}/holdings"

#     session = requests.Session()
#     session.headers.update({
#         "User-Agent": HEADERS["User-Agent"],
#         "Accept-Language": "en-US,en;q=0.9",
#         "Accept": "text/csv,text/plain,application/octet-stream,*/*",
#         "Connection": "keep-alive",
#     })

#     def row_cells(line):
#         try:
#             return [v.strip() for v in next(csv.reader([line]))]
#         except Exception:
#             return None

#     def parse_ishares_csv(body: str, source_url: str):

#         if not body or len(body) < 100:
#             print(f"  [{etf_ticker}] CSV too short from {source_url}")
#             return None

#         sample = body[:5000].lower()
#         if "<!doctype html" in sample or "<html" in sample or "<head" in sample:
#             print(f"  [{etf_ticker}] source returned HTML instead of CSV")
#             return None

#         lines = body.splitlines()
#         header_idx = None

#         for idx, line in enumerate(lines):
#             cells = row_cells(line)
#             if cells is None:
#                 continue
#             values = [c.lower() for c in cells]
#             if "ticker" in values and (
#                 "name" in values or "security name" in values
#             ):
#                 header_idx = idx
#                 break

#         if header_idx is None:
#             for idx, line in enumerate(lines):
#                 cells = row_cells(line)
#                 if cells is not None and "ticker" in [c.lower() for c in cells]:
#                     header_idx = idx
#                     break

#         if header_idx is None:
#             print(f"  [{etf_ticker}] could not find CSV header from {source_url}")
#             print(f"  [{etf_ticker}] first 500 chars: {body[:500]!r}")
#             return None

#         # "Fund Holdings as of","Nov 11, 2026"
#         as_of = None
#         for line in lines[:header_idx]:
#             cells = row_cells(line)
#             if cells and len(cells) > 1 and "as of" in cells[0].lower():
#                 as_of = _parse_date(cells[1])
#                 break

#         try:
#             df = pd.read_csv(
#                 StringIO(body),
#                 skiprows=header_idx,
#                 dtype=str,
#                 on_bad_lines="skip",
#                 engine="python",
#             )
#         except Exception as e:
#             print(f"  [{etf_ticker}] CSV parsing failed: {e}")
#             return None

#         df.columns = [str(c).strip() for c in df.columns]
#         print(f"  [{etf_ticker}] CSV columns: {list(df.columns)}")

#         ticker_col = next(
#             (c for c in df.columns if c.lower() == "ticker"), None
#         )
#         name_col = next(
#             (c for c in df.columns if c.lower() in {"name", "security name"}),
#             None,
#         )
#         weight_col = next(
#             (c for c in df.columns if c.lower() in {"weight (%)", "weight"}),
#             None,
#         )
#         if weight_col is None:
#             weight_col = next(
#                 (c for c in df.columns if "weight" in c.lower()), None
#             )

#         for label, col in (
#             ("Ticker", ticker_col),
#             ("Name", name_col),
#             ("Weight", weight_col),
#         ):
#             if col is None:
#                 print(f"  [{etf_ticker}] {label} column not found")
#                 return None

#         df = df[[ticker_col, name_col, weight_col]].copy()
#         df.columns = ["ticker", "company", "weight"]

#         df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
#         df = df[
#             ~df["ticker"].isin(["", "NAN", "TICKER", "CASH", "USD", "TOTAL"])
#         ]

#         df["weight"] = (
#             df["weight"].astype(str)
#             .str.replace("%", "", regex=False)
#             .str.replace(",", "", regex=False)
#             .str.strip()
#         )
#         df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
#         df = df[df["weight"].notna() & (df["weight"] > 0)]

#         if df.empty:
#             print(
#                 f"  [{etf_ticker}] CSV parsed but no positive-weight holdings"
#             )
#             return None

#         print(f"  [{etf_ticker}] parsed {len(df)} raw holdings")

#         return _clean_and_dedup(
#             df[["ticker", "company", "weight"]].copy(), etf_ticker, as_of
#         )

#     # ATTEMPT 1: direct latest-holdings.csv
#     print(f"  [{etf_ticker}] trying direct latest-holdings.csv...")

#     try:
#         resp = session.get(
#             latest_csv_url,
#             headers={"Referer": product_page},
#             timeout=30,
#         )

#         content_type = resp.headers.get("Content-Type", "").lower()

#         print(
#             f"  [{etf_ticker}] latest CSV → HTTP {resp.status_code}, "
#             f"content-type={content_type}, {len(resp.content)} bytes"
#         )

#         if resp.status_code == 200:
#             result = parse_ishares_csv(resp.text, latest_csv_url)
#             if result is not None and not result.empty:
#                 print(f"  [{etf_ticker}] ✓ direct latest CSV worked")
#                 return result

#     except Exception as e:
#         print(f"  [{etf_ticker}] direct CSV request failed: {e}")

#     # ATTEMPT 2: legacy endpoint with dates
#     print(f"  [{etf_ticker}] trying legacy iShares endpoint...")

#     for days_back in range(0, 10):

#         candidate = date.today() - timedelta(days=days_back)

#         params = {
#             "fileType": "csv",
#             "fileName": f"{etf_ticker}_holdings",
#             "dataType": "fund",
#             "asOfDate": candidate.strftime("%m%d%Y"),
#         }

#         try:
#             resp = session.get(
#                 legacy_endpoint,
#                 params=params,
#                 headers={"Referer": product_page},
#                 timeout=30,
#             )

#             body = resp.text
#             sample = body[:5000].lower()

#             if "<!doctype html" in sample or "<html" in sample or "<head" in sample:
#                 print(
#                     f"  [{etf_ticker}] {candidate.isoformat()} → "
#                     f"HTTP {resp.status_code}, HTML ({len(resp.content)} bytes)"
#                 )
#                 continue

#             if resp.status_code != 200:
#                 print(
#                     f"  [{etf_ticker}] {candidate.isoformat()} → "
#                     f"HTTP {resp.status_code}"
#                 )
#                 continue

#             result = parse_ishares_csv(body, legacy_endpoint)

#             if result is not None and not result.empty:
#                 print(
#                     f"  [{etf_ticker}] ✓ legacy endpoint worked for "
#                     f"{candidate.isoformat()}"
#                 )
#                 return result

#         except Exception as e:
#             print(f"  [{etf_ticker}] legacy {candidate.isoformat()} failed: {e}")

#     print(f"  [{etf_ticker}] all iShares attempts failed — skipping")
#     return None


# # ─────────────────────────────────────────────────────────────────────────────
# # CAPITAL GROUP / AVANTIS / JPMORGAN
# # ─────────────────────────────────────────────────────────────────────────────


# def fetch_capital(etf):
#     """Official Capital Group XLSX daily holdings endpoint (needs openpyxl)."""

#     url = (
#         "https://www.capitalgroup.com/api/investments/"
#         f"investment-service/v1/etfs/{etf}/download/daily-holdings"
#         "?audience=advisor"
#     )

#     r = requests.get(url, headers=HEADERS, timeout=35)
#     r.raise_for_status()

#     if not r.content.startswith(b"PK"):
#         raise ValueError(
#             f"{etf}: expected XLSX, got {r.headers.get('Content-Type')}"
#         )

#     sheets = pd.read_excel(BytesIO(r.content), sheet_name=None, header=None)

#     for sheet in sheets.values():
#         for idx in range(min(len(sheet), 30)):
#             headers = [str(v).strip().lower() for v in sheet.iloc[idx].tolist()]
#             if "ticker" in headers and (
#                 "percent of net assets" in headers or "weight" in headers
#             ):
#                 as_of = _find_asof_in_frame(sheet.iloc[:idx])
#                 body = sheet.iloc[idx + 1:].copy()
#                 body.columns = sheet.iloc[idx].tolist()
#                 try:
#                     return _normalize_extra_holdings(body, etf, as_of)
#                 except ValueError:
#                     continue

#     raise ValueError(f"{etf}: no valid holdings table found in XLSX")


# def fetch_avantis(etf):
#     """
#     1) Use ALPHARADAR_<ETF>_HOLDINGS_URL if set (find it via browser DevTools).
#     2) Otherwise scrape the official fund page for a holdings download link.
#     """

#     override = os.getenv(f"ALPHARADAR_{etf}_HOLDINGS_URL", "")

#     if override.startswith("https://"):
#         r = requests.get(override, headers=HEADERS, timeout=30)
#         r.raise_for_status()
#         body, as_of = _read_holdings_bytes(r.content, etf)
#         return _normalize_extra_holdings(body, etf, as_of)

#     from bs4 import BeautifulSoup

#     slug = AVANTIS_SLUGS[etf]
#     page = (
#         "https://www.avantisinvestors.com/avantis-investments/en-us/"
#         f"{slug}/{etf}/"
#     )

#     r = requests.get(page, headers=HEADERS, timeout=30)
#     r.raise_for_status()

#     soup = BeautifulSoup(r.text, "html.parser")
#     candidates = []

#     for a in soup.find_all("a", href=True):
#         href = urljoin(page, a["href"])
#         label = a.get_text(" ", strip=True).lower()
#         if (
#             ("csv" in href.lower() or "download" in href.lower())
#             and "holding" in (href + label).lower()
#         ):
#             host = urlparse(href).hostname or ""
#             if host.endswith("avantisinvestors.com"):
#                 candidates.append(href)

#     for url in dict.fromkeys(candidates):
#         try:
#             resp = requests.get(url, headers=HEADERS, timeout=30)
#             resp.raise_for_status()
#             body, as_of = _read_holdings_bytes(resp.content, etf)
#             return _normalize_extra_holdings(body, etf, as_of)
#         except Exception as exc:
#             print(f"  [{etf}] candidate rejected: {exc}")

#     raise RuntimeError(
#         f"{etf}: no verified holdings link found on official page; "
#         f"set ALPHARADAR_{etf}_HOLDINGS_URL (find it via browser DevTools)"
#     )


# def fetch_jpmorgan(etf):
#     """Fail closed until a validated official JPMorgan holdings URL is configured."""

#     url = os.getenv(f"ALPHARADAR_{etf}_HOLDINGS_URL", "")

#     if not url or not url.startswith("https://"):
#         raise RuntimeError(
#             f"{etf}: set ALPHARADAR_{etf}_HOLDINGS_URL to a VERIFIED "
#             f"official holdings download URL"
#         )

#     host = urlparse(url).hostname or ""
#     if not (
#         host == "jpmorgan.com" or host.endswith(".jpmorgan.com")
#         or host == "jpmorganfunds.com" or host.endswith(".jpmorganfunds.com")
#     ):
#         raise ValueError(f"{etf}: URL must be hosted by JPMorgan")

#     r = requests.get(url, headers=HEADERS, timeout=35)
#     r.raise_for_status()

#     body, as_of = _read_holdings_bytes(r.content, etf)
#     return _normalize_extra_holdings(body, etf, as_of)


# def fetch_additional(etf, issuer):
#     try:
#         return {
#             "capital": fetch_capital,
#             "avantis": fetch_avantis,
#             "jpmorgan": fetch_jpmorgan,
#         }[issuer](etf)
#     except Exception as exc:
#         print(f"  [{etf}] SKIPPED: {exc}")
#         return None


# # ─────────────────────────────────────────────────────────────────────────────
# # CROSS-ETF SIGNALS
# # ─────────────────────────────────────────────────────────────────────────────


# def generate_multi_etf_signals():

#     # Rebuild today's MULTI signals from scratch so reruns never duplicate
#     supabase.table("holding_changes").delete() \
#         .eq("etf", "MULTI").gte("created_at", TODAY).execute()

#     result = (
#         supabase.table("holding_changes")
#         .select("ticker, etf, change_type")
#         .eq("change_type", "accumulation")
#         .gte("created_at", TODAY)
#         .execute()
#     )

#     ticker_etfs = defaultdict(set)

#     for row in result.data or []:
#         ticker_etfs[row["ticker"]].add(row["etf"])

#     signals = [
#         {
#             "etf": "MULTI",
#             "ticker": tkr,
#             "change_type": "multi_etf_buy",
#             "delta": float(len(etfs)),
#             "description": (
#                 f"{len(etfs)} ETFs simultaneously "
#                 f"buying {tkr}: {', '.join(sorted(etfs))}"
#             ),
#         }
#         for tkr, etfs in ticker_etfs.items()
#         if len(etfs) >= 3
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

#     results = {}   # ticker -> saved | unchanged | failed | skipped
#     core = []      # ETFs whose failure should fail the whole job

#     # ARK
#     for ticker, url in ARK_ETFS.items():
#         print(f"\nFetching {ticker} (ARK)...")
#         core.append(ticker)
#         results[ticker] = save_etf(ticker, fetch_ark(ticker, url))
#         time.sleep(1)

#     # ARKQ
#     print("\nFetching ARKQ (ARK, multi-URL fallback)...")
#     core.append("ARKQ")
#     results["ARKQ"] = save_etf("ARKQ", fetch_ark_with_fallback("ARKQ", ARKQ_URLS))
#     time.sleep(1)

#     # Tema
#     for ticker, url in TEMA_ETFS.items():
#         print(f"\nFetching {ticker} (Tema)...")
#         core.append(ticker)
#         results[ticker] = save_etf(ticker, fetch_tema(ticker, url))
#         time.sleep(1)

#     # iShares
#     for ticker, config in ISHARES_ETFS.items():
#         print(f"\nFetching {ticker} (iShares Active)...")
#         core.append(ticker)
#         results[ticker] = save_etf(
#             ticker, fetch_ishares(ticker, config["product_id"])
#         )
#         time.sleep(1)

#     # Capital Group / Avantis / JPMorgan (optional: skips don't fail the job)
#     for ticker, issuer in ADDITIONAL_ETFS.items():
#         print(f"\nFetching {ticker} ({issuer})...")
#         df = fetch_additional(ticker, issuer)
#         results[ticker] = save_etf(ticker, df) if df is not None else "skipped"
#         time.sleep(1)

#     print("\nGenerating cross-ETF signals...")
#     generate_multi_etf_signals()

#     saved = [t for t, s in results.items() if s == "saved"]
#     unchanged = [t for t, s in results.items() if s == "unchanged"]
#     skipped = [t for t, s in results.items() if s == "skipped"]
#     failed = [t for t, s in results.items() if s == "failed"]

#     print(f"\n{'=' * 55}")
#     print(
#         f"Done: {len(saved)} new snapshots, {len(unchanged)} unchanged, "
#         f"{len(skipped)} skipped, {len(failed)} failed (of {len(results)})"
#     )
#     if saved:
#         print(f"  new:       {', '.join(saved)}")
#     if unchanged:
#         print(f"  unchanged: {', '.join(unchanged)}")
#     if skipped:
#         print(f"  skipped:   {', '.join(skipped)}")
#     if failed:
#         print(f"  failed:    {', '.join(failed)}")

#     core_failed = [t for t in core if results.get(t) == "failed"]
#     if core_failed:
#         print(f"\nCore ETFs failed: {', '.join(core_failed)}")
#         sys.exit(1)


# if __name__ == "__main__":
#     run()
import csv
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from io import BytesIO, StringIO
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from supabase import create_client


# ── Supabase client ───────────────────────────────────────────────────────────

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Constants ─────────────────────────────────────────────────────────────────

TODAY = date.today().isoformat()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Bloomberg-style US exchange suffixes (RKLB UQ -> RKLB).
# Foreign suffixes (FP, GR, LN ...) are intentionally NOT stripped.
US_EXCHANGE_SUFFIXES = {"UN", "UQ", "UW", "UR", "UA", "UP", "US"}

DATE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}"
)


# ── ARK ETFs ──────────────────────────────────────────────────────────────────

ARK_BASE = "https://assets.ark-funds.com/fund-documents/funds-etf-csv"

ARK_COLS = [
    "date", "fund", "company", "ticker",
    "cusip", "shares", "market_value", "weight",
]

ARK_ETFS = {
    "ARKK": f"{ARK_BASE}/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKW": f"{ARK_BASE}/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKG": f"{ARK_BASE}/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKF": f"{ARK_BASE}/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
    "ARKX": f"{ARK_BASE}/ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS.csv",
    "PRNT": f"{ARK_BASE}/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv",
    "IZRL": f"{ARK_BASE}/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv",
}

ARKQ_URLS = [
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECH._%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECHNOLOGY_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARK_AUTONOMOUS_TECH_%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    f"{ARK_BASE}/ARKQ_HOLDINGS.csv",
]


# ── Tema ETFs ─────────────────────────────────────────────────────────────────

TEMA_ETFS = {
    "NASA": "https://temaetfs.com/hubfs/Website/Holdings/NASA-holdings.csv",
}


# ── iShares Active ETFs ───────────────────────────────────────────────────────

ISHARES_ETFS = {
    "BAI": {"product_id": "339081"},
    "TEK": {"product_id": "339083"},
    "DYNF": {"product_id": "307283"},
    "THRO": {"product_id": "325384"},
    "INRO": {"product_id": "336430"},
    "BMED": {"product_id": "316007"},
    "IDYN": {"product_id": "345128"},
}


# ── Additional actively managed ETFs ──────────────────────────────────────────

ADDITIONAL_ETFS = {
    "CGGR": "capital",
    "CGDV": "capital",
    "JGRO": "jpmorgan",
    "JAVA": "jpmorgan",
}

# AVUV / AVLV intentionally excluded for now.
AVANTIS_SLUGS = {}


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _norm_ticker(raw) -> str:
    """'RKLB UQ' -> 'RKLB'. Only strips US exchange suffixes."""
    t = str(raw).strip().upper()
    parts = t.split()
    if len(parts) >= 2 and parts[-1] in US_EXCHANGE_SUFFIXES:
        return " ".join(parts[:-1])
    return t


def _parse_date(value):
    """Return ISO date string, or None if missing / implausible."""
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in ("", "-", "nan", "nat", "none"):
        return None
    try:
        d = pd.to_datetime(s, errors="coerce")
    except Exception:
        return None
    if pd.isna(d):
        return None
    d = d.date()
    lo = date.today() - timedelta(days=14)
    hi = date.today() + timedelta(days=5)
    return d.isoformat() if lo <= d <= hi else None


def _asof_from_series(series):
    """Most common valid date found in a column of date-like values."""
    vals = [_parse_date(v) for v in series.dropna().astype(str)]
    vals = [v for v in vals if v]
    if not vals:
        return None
    return max(set(vals), key=vals.count)


def _find_asof_in_frame(raw, max_rows=40):
    """Look for an 'as of <date>' cell in the rows above the table."""
    for idx in range(min(len(raw), max_rows)):
        cells = [str(v).strip() for v in raw.iloc[idx].tolist()]
        cells = [c for c in cells if c and c.lower() not in ("nan", "nat", "none")]
        for j, cell in enumerate(cells):
            if "as of" in cell.lower():
                for cand in [cell] + cells[j + 1:j + 3]:
                    m = DATE_RE.search(cand)
                    if m:
                        d = _parse_date(m.group(0))
                        if d:
                            return d
    return None


def _clean_shares(series):
    """Parse issuer-reported shares/units. Missing values remain NULL."""
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace('"', "", regex=False)
        .str.strip()
        .replace({"": None, "-": None, "nan": None, "NaN": None,
                  "None": None, "N/A": None, "n/a": None, "<NA>": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _clean_and_dedup(df, etf_ticker, as_of=None):
    """Normalize common issuer rows while preserving reported shares."""
    df = df.copy()

    df["weight"] = (
        df["weight"].astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)

    if "shares" not in df.columns:
        df["shares"] = None
    df["shares"] = _clean_shares(df["shares"])

    df["ticker"] = (
        df["ticker"].astype(str).str.strip().str.upper().map(_norm_ticker)
    )
    df["company"] = df["company"].astype(str).str.strip()
    df["etf"] = etf_ticker
    df["date"] = as_of or TODAY

    result = df[["etf", "ticker", "company", "weight", "shares", "date"]].copy()
    result = result[~result["ticker"].isin(["NAN", "", "-", "TICKER"])]
    result = result[result["weight"] > 0]
    before = len(result)
    result = (
        result.sort_values("weight", ascending=False)
        .drop_duplicates(subset=["etf", "ticker", "date"], keep="first")
    )

    if len(result) < before:
        print(f"  [{etf_ticker}] removed {before - len(result)} duplicate rows")

    print(
        f"  [{etf_ticker}] {len(result)} holdings — "
        f"{result['shares'].notna().sum()} with shares"
    )
    print(
        f"  [{etf_ticker}] snapshot date: {as_of or TODAY}"
        + ("" if as_of else "  (no as-of date in file, using today)")
    )
    return result


def _read_holdings_bytes(content: bytes, etf: str):
    """
    Read an XLSX/CSV holdings file, locate the header row containing a ticker
    column, and return (table, as_of_date_or_None).
    """

    if content[:2] == b"PK":
        raw = pd.read_excel(BytesIO(content), header=None)
    elif b"<html" not in content[:500].lower():
        rows = list(csv.reader(StringIO(content.decode("utf-8-sig"))))
        width = max((len(r) for r in rows), default=0)
        raw = pd.DataFrame([r + [""] * (width - len(r)) for r in rows])
    else:
        raise ValueError(f"{etf}: HTML received instead of holdings file")

    for idx in range(min(len(raw), 40)):
        vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist()]
        if any(v in ("ticker", "symbol", "security ticker") for v in vals):
            body = raw.iloc[idx + 1:].copy()
            body.columns = raw.iloc[idx].tolist()
            return body, _find_asof_in_frame(raw.iloc[:idx])

    raise ValueError(f"{etf}: header row with ticker not found")


def _new_number(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace(r"[$,%]", "", regex=True)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def _normalize_extra_holdings(raw, etf, source_date=None):
    """Normalize issuer tables; shares are optional and never fabricated."""
    if raw is None or raw.empty:
        return None

    df = raw.copy()
    df.columns = [str(c).strip().lower().replace("\n", " ") for c in df.columns]

    aliases = {
        "ticker": ["ticker", "symbol", "security ticker"],
        "company": ["security name", "security description", "company",
                    "name", "holding", "description"],
        "weight": ["percent of net assets", "% of net assets", "% of assets",
                   "weight", "weight (%)", "portfolio weight", "percent of assets"],
        "shares": [
    "shares",
    "shares or principal amount",
    "shares/principal amount",
    "shares / principal amount",
    "shares/par",
    "shares / par",
    "par shares",
    "quantity",
    "number of shares",
    "shares held",
    "units",
    "units held",
    "market value shares"
],
    }

    mapping = {}
    for target, options in aliases.items():
        for option in options:
            if option in df.columns:
                mapping[target] = option
                break

    required = ("ticker", "company", "weight")
    missing = [key for key in required if key not in mapping]
    if missing:
        raise ValueError(
            f"{etf}: required columns missing {missing}; received {list(df.columns)}"
        )

    selected = [mapping[key] for key in required]
    if "shares" in mapping:
        selected.append(mapping["shares"])
    df = df[selected].copy()

    rename_map = {mapping[key]: key for key in required}
    if "shares" in mapping:
        rename_map[mapping["shares"]] = "shares"
    df = df.rename(columns=rename_map)
    if "shares" not in df.columns:
        df["shares"] = None

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip().map(_norm_ticker)
    df["company"] = df["company"].astype(str).str.strip()
    df["weight"] = _new_number(df["weight"])
    df["shares"] = _clean_shares(df["shares"])

    df = df[df["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", na=False)]
    df = df[~df["ticker"].isin(["CASH", "USD", "TOTAL", "NAN"])]
    df = df[df["weight"].notna() & (df["weight"] > 0)]
    df = df.sort_values("weight", ascending=False)
    df = df.drop_duplicates(subset=["ticker"], keep="first")

    if len(df) < 5 or df["weight"].sum() > 125:
        raise ValueError(
            f"{etf}: suspicious holdings: {len(df)} rows, "
            f"weight sum {df['weight'].sum():.2f}"
        )

    df["etf"] = etf
    df["date"] = source_date or TODAY
    print(
        f"  [{etf}] {len(df)} holdings, {df['shares'].notna().sum()} with shares, "
        f"snapshot date: {df['date'].iloc[0]}"
        + ("" if source_date else "  (no as-of date in file, using today)")
    )
    return df[["etf", "ticker", "company", "weight", "shares", "date"]]


# ─────────────────────────────────────────────────────────────────────────────
# SNAPSHOT STORAGE / CHANGE DETECTION
# ─────────────────────────────────────────────────────────────────────────────


def _load_snapshot(etf: str, snap_date: str) -> dict:
    """Return {ticker: {weight, shares}} for one stored snapshot."""
    res = (
        supabase.table("holdings")
        .select("ticker,weight,shares")
        .eq("etf", etf)
        .eq("date", snap_date)
        .execute()
    )
    out = {}
    for row in res.data or []:
        ticker = _norm_ticker(row["ticker"])
        weight = float(row["weight"]) if row.get("weight") is not None else None
        shares = float(row["shares"]) if row.get("shares") is not None else None
        # Keep the row with the largest weight if a source unexpectedly duplicates.
        if ticker not in out or (weight or 0) > (out[ticker]["weight"] or 0):
            out[ticker] = {"weight": weight, "shares": shares}
    return out


def _load_prev_snapshot(etf: str, snap_date: str):
    latest = (
        supabase.table("holdings")
        .select("date")
        .eq("etf", etf)
        .lt("date", snap_date)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return None, {}
    prev_date = latest.data[0]["date"]
    return prev_date, _load_snapshot(etf, prev_date)


def _same_snapshot(a: dict, b: dict) -> bool:
    """Compare ticker membership, weights and shares (including NULL availability)."""
    if a.keys() != b.keys():
        return False

    def same_number(x, y, tolerance):
        if x is None or y is None:
            return x is None and y is None
        return abs(float(x) - float(y)) < tolerance

    for ticker in a:
        if not same_number(a[ticker].get("weight"), b[ticker].get("weight"), 1e-4):
            return False
        if not same_number(a[ticker].get("shares"), b[ticker].get("shares"), 1e-8):
            return False
    return True


def _diff_snapshots(etf: str, old: dict, new: dict,
                    previous_date: str | None, current_date: str) -> list:
    """Create weight and shares changes independently for two complete snapshots."""
    if not old:
        return []

    out = []
    for ticker, current in new.items():
        previous = old.get(ticker)
        current_weight = current.get("weight")
        current_shares = current.get("shares")

        if previous is None:
            out.append({
                "etf": etf,
                "ticker": ticker,
                "change_type": "new_position",
                "delta": round(current_weight, 8) if current_weight is not None else None,
                "previous_weight": None,
                "current_weight": current_weight,
                "shares_delta": None,
                "previous_shares": None,
                "current_shares": current_shares,
                "shares_change_type": None,
                "previous_snapshot_date": previous_date,
                "current_snapshot_date": current_date,
                "description": f"{etf} added {ticker} to reported holdings",
            })
            continue

        previous_weight = previous.get("weight")
        previous_shares = previous.get("shares")
        weight_delta = (
            current_weight - previous_weight
            if current_weight is not None and previous_weight is not None else None
        )
        shares_delta = (
            current_shares - previous_shares
            if current_shares is not None and previous_shares is not None else None
        )

        # Keep the existing weight threshold: > 0.3 percentage points.
        weight_changed = weight_delta is not None and abs(weight_delta) > 0.3
        shares_changed = shares_delta is not None and abs(shares_delta) > 1e-8
        if not weight_changed and not shares_changed:
            continue

        if weight_changed:
            change_type = "accumulation" if weight_delta > 0 else "reduction"
        else:
            change_type = "shares_change"

        shares_change_type = None
        if shares_changed:
            shares_change_type = "increase" if shares_delta > 0 else "decrease"

        description_parts = []
        if weight_delta is not None:
            description_parts.append(f"weight {weight_delta:+.4f} percentage points")
        if shares_delta is not None:
            description_parts.append(f"reported shares {shares_delta:+,.4f}")

        out.append({
            "etf": etf,
            "ticker": ticker,
            "change_type": change_type,
            "delta": round(weight_delta, 8) if weight_delta is not None else None,
            "previous_weight": previous_weight,
            "current_weight": current_weight,
            "shares_delta": round(shares_delta, 8) if shares_delta is not None else None,
            "previous_shares": previous_shares,
            "current_shares": current_shares,
            "shares_change_type": shares_change_type,
            "previous_snapshot_date": previous_date,
            "current_snapshot_date": current_date,
            "description": (
                f"{etf} {ticker}: " + "; ".join(description_parts)
                + " (reported holdings change, not verified trades)"
            ),
        })

    # Preserve the existing 'removed' event. Absence from a file is not proof of a sale.
    for ticker in old.keys() - new.keys():
        previous = old[ticker]
        out.append({
            "etf": etf,
            "ticker": ticker,
            "change_type": "removed",
            "delta": 0.0,
            "previous_weight": previous.get("weight"),
            "current_weight": None,
            "shares_delta": None,
            "previous_shares": previous.get("shares"),
            "current_shares": None,
            "shares_change_type": None,
            "previous_snapshot_date": previous_date,
            "current_snapshot_date": current_date,
            "description": f"{etf} no longer reports {ticker}; absence is not proof of a sale",
        })
    return out


def save_etf(ticker: str, df) -> str:
    """Save holdings and changes. Returns saved, unchanged or failed."""
    if df is None or df.empty:
        return "failed"

    required = {"etf", "ticker", "company", "weight", "date"}
    missing = required - set(df.columns)
    if missing:
        print(f"  [{ticker}] missing normalized columns: {sorted(missing)}")
        return "failed"
    if "shares" not in df.columns:
        df = df.copy()
        df["shares"] = None

    snap_date = str(df["date"].iloc[0])
    new = {}
    for row in df.to_dict("records"):
        t = _norm_ticker(row["ticker"])
        new[t] = {
            "weight": float(row["weight"]) if pd.notna(row["weight"]) else None,
            "shares": float(row["shares"]) if pd.notna(row["shares"]) else None,
        }

    current_snapshot = _load_snapshot(ticker, snap_date)
    prev_date, old = _load_prev_snapshot(ticker, snap_date)

    if current_snapshot and _same_snapshot(current_snapshot, new):
        print(f"  = {snap_date} already stored, weight/shares identical")
        return "unchanged"

    if old and _same_snapshot(old, new):
        print(f"  = identical to previous snapshot {prev_date}; skipping stale file")
        return "unchanged"

    changes = _diff_snapshots(ticker, old, new, prev_date, snap_date)

    # If replacing this ETF's same-date snapshot, remove only changes generated
    # for this exact snapshot date. Never delete other ETFs' or dates' records.
    if current_snapshot:
        print(f"  ~ {snap_date} exists but differs — replacing snapshot")
        supabase.table("holdings").delete().eq("etf", ticker).eq("date", snap_date).execute()
        (
            supabase.table("holding_changes").delete()
            .eq("etf", ticker)
            .eq("current_snapshot_date", snap_date)
            .execute()
        )

    records_df = df[["etf", "ticker", "company", "weight", "shares", "date"]].copy()
    records = []
    for row in records_df.to_dict("records"):
        clean_row = {}
        for key, value in row.items():
            clean_row[key] = None if pd.isna(value) else value
        records.append(clean_row)
    for i in range(0, len(records), 100):
        supabase.table("holdings").upsert(records[i:i + 100]).execute()

    if changes:
        for i in range(0, len(changes), 100):
            supabase.table("holding_changes").insert(changes[i:i + 100]).execute()

    with_shares = sum(1 for item in new.values() if item["shares"] is not None)
    print(
        f"  ✓ saved {snap_date}: {len(new)} holdings, {with_shares} with shares, "
        f"{len(changes)} changes vs {prev_date or 'no earlier snapshot'}"
    )
    return "saved"


# ─────────────────────────────────────────────────────────────────────────────
# ARK
# ─────────────────────────────────────────────────────────────────────────────


def _parse_ark_text(text: str, etf_ticker: str):
    """ARK CSV: no header row, fixed 8-column format.
    The date column is the NEXT trading day (per ARK's help center)."""

    df = pd.read_csv(StringIO(text), header=None, names=ARK_COLS)

    df = df[df["ticker"].notna()]
    df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]

    as_of = _asof_from_series(df["date"])

    return _clean_and_dedup(
        df[["ticker", "company", "weight", "shares"]].copy(), etf_ticker, as_of
    )


def fetch_ark(etf_ticker: str, url: str):

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return _parse_ark_text(resp.text, etf_ticker)

    except Exception as e:
        print(f"  [{etf_ticker}] ✗ {e}")
        return None


def fetch_ark_with_fallback(etf_ticker: str, urls: list):
    """Try multiple ARK URLs."""

    for i, url in enumerate(urls):

        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)

            if resp.status_code == 200:
                print(f"  [{etf_ticker}] variant {i + 1} OK")
                return _parse_ark_text(resp.text, etf_ticker)

            print(f"  [{etf_ticker}] variant {i + 1} → HTTP {resp.status_code}")

        except Exception as e:
            print(f"  [{etf_ticker}] variant {i + 1} ✗ {e}")

    print(f"  [{etf_ticker}] all variants failed — skipping")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# TEMA
# ─────────────────────────────────────────────────────────────────────────────


def fetch_tema(etf_ticker: str, url: str):
    """
    Tema CSV columns: holdings_date, ticker, cusip, proper_name, shares,
    market_value, percent_of_nav, is_cash, country, sector
    """

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()

        df = pd.read_csv(StringIO(resp.text))
        df.columns = [c.strip().lower() for c in df.columns]

        ticker_col = next((c for c in df.columns if "ticker" in c), None)

        name_col = next(
            (
                c for c in df.columns
                if c == "proper_name" or "name" in c or "company" in c
            ),
            None,
        )

        weight_col = next(
            (
                c for c in df.columns
                if c == "percent_of_nav"
                or "weight" in c or "percent" in c or "nav" in c
            ),
            None,
        )

        date_col = next(
            (c for c in df.columns if c == "holdings_date" or "date" in c),
            None,
        )

        if not all([ticker_col, name_col, weight_col]):
            print(
                f"  [{etf_ticker}] ✗ unexpected columns: {list(df.columns)}"
            )
            return None

        as_of = _asof_from_series(df[date_col]) if date_col else None
        shares_col = next(
            (c for c in df.columns if c in {"shares", "quantity", "units"}), None
        )

        selected = [ticker_col, name_col, weight_col]
        if shares_col:
            selected.append(shares_col)
        df = df[selected].copy()
        rename_map = {ticker_col: "ticker", name_col: "company", weight_col: "weight"}
        if shares_col:
            rename_map[shares_col] = "shares"
        df = df.rename(columns=rename_map)
        if "shares" not in df.columns:
            df["shares"] = None

        df = df.dropna(subset=["ticker"])
        df = df[
            ~df["ticker"].astype(str).str.strip().str.lower()
            .isin(["ticker", "nan", "", "-", "cash", "usd"])
        ]

        return _clean_and_dedup(df, etf_ticker, as_of)

    except Exception as e:
        print(f"  [{etf_ticker}] ✗ {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# iSHARES
# ─────────────────────────────────────────────────────────────────────────────


def fetch_ishares(etf_ticker: str, product_id: str):
    """
    iShares holdings downloader.
    1. Direct latest-holdings.csv URL.
    2. Fallback: legacy .ajax endpoint with dated lookback.
    The 'Fund Holdings as of' line above the table is used as snapshot date.
    """

    latest_csv_url = (
        f"https://www.ishares.com/us/products/"
        f"{product_id}/holdings/latest-holdings.csv"
    )
    legacy_endpoint = (
        f"https://www.ishares.com/us/products/"
        f"{product_id}/holdings/1467271812596.ajax"
    )
    product_page = f"https://www.ishares.com/us/products/{product_id}/holdings"

    session = requests.Session()
    session.headers.update({
        "User-Agent": HEADERS["User-Agent"],
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/csv,text/plain,application/octet-stream,*/*",
        "Connection": "keep-alive",
    })

    def row_cells(line):
        try:
            return [v.strip() for v in next(csv.reader([line]))]
        except Exception:
            return None

    def parse_ishares_csv(body: str, source_url: str):

        if not body or len(body) < 100:
            print(f"  [{etf_ticker}] CSV too short from {source_url}")
            return None

        sample = body[:5000].lower()
        if "<!doctype html" in sample or "<html" in sample or "<head" in sample:
            print(f"  [{etf_ticker}] source returned HTML instead of CSV")
            return None

        lines = body.splitlines()
        header_idx = None

        for idx, line in enumerate(lines):
            cells = row_cells(line)
            if cells is None:
                continue
            values = [c.lower() for c in cells]
            if "ticker" in values and (
                "name" in values or "security name" in values
            ):
                header_idx = idx
                break

        if header_idx is None:
            for idx, line in enumerate(lines):
                cells = row_cells(line)
                if cells is not None and "ticker" in [c.lower() for c in cells]:
                    header_idx = idx
                    break

        if header_idx is None:
            print(f"  [{etf_ticker}] could not find CSV header from {source_url}")
            print(f"  [{etf_ticker}] first 500 chars: {body[:500]!r}")
            return None

        # "Fund Holdings as of","Nov 11, 2026"
        as_of = None
        for line in lines[:header_idx]:
            cells = row_cells(line)
            if cells and len(cells) > 1 and "as of" in cells[0].lower():
                as_of = _parse_date(cells[1])
                break

        try:
            df = pd.read_csv(
                StringIO(body),
                skiprows=header_idx,
                dtype=str,
                on_bad_lines="skip",
                engine="python",
            )
        except Exception as e:
            print(f"  [{etf_ticker}] CSV parsing failed: {e}")
            return None

        df.columns = [str(c).strip() for c in df.columns]
        print(f"  [{etf_ticker}] CSV columns: {list(df.columns)}")

        ticker_col = next(
            (c for c in df.columns if c.lower() == "ticker"), None
        )
        name_col = next(
            (c for c in df.columns if c.lower() in {"name", "security name"}),
            None,
        )
        weight_col = next(
            (c for c in df.columns if c.lower() in {"weight (%)", "weight"}),
            None,
        )
        if weight_col is None:
            weight_col = next(
                (c for c in df.columns if "weight" in c.lower()), None
            )

        for label, col in (
            ("Ticker", ticker_col),
            ("Name", name_col),
            ("Weight", weight_col),
        ):
            if col is None:
                print(f"  [{etf_ticker}] {label} column not found")
                return None

        shares_col = next(
            (c for c in df.columns
             if c.strip().lower() in {"quantity", "shares", "number of shares"}),
            None,
        )
        selected = [ticker_col, name_col, weight_col]
        if shares_col:
            selected.append(shares_col)
        df = df[selected].copy()
        rename_map = {ticker_col: "ticker", name_col: "company", weight_col: "weight"}
        if shares_col:
            rename_map[shares_col] = "shares"
        df = df.rename(columns=rename_map)
        if "shares" not in df.columns:
            df["shares"] = None

        df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
        df = df[
            ~df["ticker"].isin(["", "NAN", "TICKER", "CASH", "USD", "TOTAL"])
        ]

        df["weight"] = (
            df["weight"].astype(str)
            .str.replace("%", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip()
        )
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
        df = df[df["weight"].notna() & (df["weight"] > 0)]

        if df.empty:
            print(
                f"  [{etf_ticker}] CSV parsed but no positive-weight holdings"
            )
            return None

        print(f"  [{etf_ticker}] parsed {len(df)} raw holdings")

        return _clean_and_dedup(
            df[["ticker", "company", "weight", "shares"]].copy(), etf_ticker, as_of
        )

    # ATTEMPT 1: direct latest-holdings.csv
    print(f"  [{etf_ticker}] trying direct latest-holdings.csv...")

    try:
        resp = session.get(
            latest_csv_url,
            headers={"Referer": product_page},
            timeout=30,
        )

        content_type = resp.headers.get("Content-Type", "").lower()

        print(
            f"  [{etf_ticker}] latest CSV → HTTP {resp.status_code}, "
            f"content-type={content_type}, {len(resp.content)} bytes"
        )

        if resp.status_code == 200:
            result = parse_ishares_csv(resp.text, latest_csv_url)
            if result is not None and not result.empty:
                print(f"  [{etf_ticker}] ✓ direct latest CSV worked")
                return result

    except Exception as e:
        print(f"  [{etf_ticker}] direct CSV request failed: {e}")

    # ATTEMPT 2: legacy endpoint with dates
    print(f"  [{etf_ticker}] trying legacy iShares endpoint...")

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
                legacy_endpoint,
                params=params,
                headers={"Referer": product_page},
                timeout=30,
            )

            body = resp.text
            sample = body[:5000].lower()

            if "<!doctype html" in sample or "<html" in sample or "<head" in sample:
                print(
                    f"  [{etf_ticker}] {candidate.isoformat()} → "
                    f"HTTP {resp.status_code}, HTML ({len(resp.content)} bytes)"
                )
                continue

            if resp.status_code != 200:
                print(
                    f"  [{etf_ticker}] {candidate.isoformat()} → "
                    f"HTTP {resp.status_code}"
                )
                continue

            result = parse_ishares_csv(body, legacy_endpoint)

            if result is not None and not result.empty:
                print(
                    f"  [{etf_ticker}] ✓ legacy endpoint worked for "
                    f"{candidate.isoformat()}"
                )
                return result

        except Exception as e:
            print(f"  [{etf_ticker}] legacy {candidate.isoformat()} failed: {e}")

    print(f"  [{etf_ticker}] all iShares attempts failed — skipping")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CAPITAL GROUP / AVANTIS / JPMORGAN
# ─────────────────────────────────────────────────────────────────────────────


def fetch_capital(etf):
    """Official Capital Group XLSX daily holdings endpoint (needs openpyxl)."""

    url = (
        "https://www.capitalgroup.com/api/investments/"
        f"investment-service/v1/etfs/{etf}/download/daily-holdings"
        "?audience=advisor"
    )

    r = requests.get(url, headers=HEADERS, timeout=35)
    r.raise_for_status()

    if not r.content.startswith(b"PK"):
        raise ValueError(
            f"{etf}: expected XLSX, got {r.headers.get('Content-Type')}"
        )

    sheets = pd.read_excel(BytesIO(r.content), sheet_name=None, header=None)

    for sheet in sheets.values():
        for idx in range(min(len(sheet), 30)):
            headers = [str(v).strip().lower() for v in sheet.iloc[idx].tolist()]
            if "ticker" in headers and (
                "percent of net assets" in headers or "weight" in headers
            ):
                as_of = _find_asof_in_frame(sheet.iloc[:idx])
                body = sheet.iloc[idx + 1:].copy()
                body.columns = sheet.iloc[idx].tolist()
                try:
                    return _normalize_extra_holdings(body, etf, as_of)
                except ValueError:
                    continue

    raise ValueError(f"{etf}: no valid holdings table found in XLSX")


def fetch_avantis(etf):
    """
    1) Use ALPHARADAR_<ETF>_HOLDINGS_URL if set (find it via browser DevTools).
    2) Otherwise scrape the official fund page for a holdings download link.
    """

    override = os.getenv(f"ALPHARADAR_{etf}_HOLDINGS_URL", "")

    if override.startswith("https://"):
        r = requests.get(override, headers=HEADERS, timeout=30)
        r.raise_for_status()
        body, as_of = _read_holdings_bytes(r.content, etf)
        return _normalize_extra_holdings(body, etf, as_of)

    from bs4 import BeautifulSoup

    slug = AVANTIS_SLUGS[etf]
    page = (
        "https://www.avantisinvestors.com/avantis-investments/en-us/"
        f"{slug}/{etf}/"
    )

    r = requests.get(page, headers=HEADERS, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    candidates = []

    for a in soup.find_all("a", href=True):
        href = urljoin(page, a["href"])
        label = a.get_text(" ", strip=True).lower()
        if (
            ("csv" in href.lower() or "download" in href.lower())
            and "holding" in (href + label).lower()
        ):
            host = urlparse(href).hostname or ""
            if host.endswith("avantisinvestors.com"):
                candidates.append(href)

    for url in dict.fromkeys(candidates):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            body, as_of = _read_holdings_bytes(resp.content, etf)
            return _normalize_extra_holdings(body, etf, as_of)
        except Exception as exc:
            print(f"  [{etf}] candidate rejected: {exc}")

    raise RuntimeError(
        f"{etf}: no verified holdings link found on official page; "
        f"set ALPHARADAR_{etf}_HOLDINGS_URL (find it via browser DevTools)"
    )


def fetch_jpmorgan(etf):
    """Fail closed until a validated official JPMorgan holdings URL is configured."""

    url = os.getenv(f"ALPHARADAR_{etf}_HOLDINGS_URL", "")

    if not url or not url.startswith("https://"):
        raise RuntimeError(
            f"{etf}: set ALPHARADAR_{etf}_HOLDINGS_URL to a VERIFIED "
            f"official holdings download URL"
        )

    host = urlparse(url).hostname or ""
    if not (
        host == "jpmorgan.com" or host.endswith(".jpmorgan.com")
        or host == "jpmorganfunds.com" or host.endswith(".jpmorganfunds.com")
    ):
        raise ValueError(f"{etf}: URL must be hosted by JPMorgan")

    r = requests.get(url, headers=HEADERS, timeout=35)
    r.raise_for_status()

    body, as_of = _read_holdings_bytes(r.content, etf)
    return _normalize_extra_holdings(body, etf, as_of)


def fetch_additional(etf, issuer):
    try:
        return {
            "capital": fetch_capital,
            "avantis": fetch_avantis,
            "jpmorgan": fetch_jpmorgan,
        }[issuer](etf)
    except Exception as exc:
        print(f"  [{etf}] SKIPPED: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CROSS-ETF SIGNALS
# ─────────────────────────────────────────────────────────────────────────────


def generate_multi_etf_signals():
    """Rebuild today's cross-ETF signals from weight-based accumulations."""
    (
        supabase.table("holding_changes").delete()
        .eq("etf", "MULTI").gte("created_at", TODAY).execute()
    )

    result = (
        supabase.table("holding_changes")
        .select("ticker,etf,change_type,current_snapshot_date")
        .eq("change_type", "accumulation")
        .neq("etf", "MULTI")
        .gte("created_at", TODAY)
        .execute()
    )

    ticker_etfs = defaultdict(set)
    ticker_dates = defaultdict(list)
    for row in result.data or []:
        ticker = row["ticker"]
        ticker_etfs[ticker].add(row["etf"])
        if row.get("current_snapshot_date"):
            ticker_dates[ticker].append(row["current_snapshot_date"])

    signals = []
    for ticker, etfs in ticker_etfs.items():
        if len(etfs) < 3:
            continue
        dates = ticker_dates[ticker]
        signals.append({
            "etf": "MULTI",
            "ticker": ticker,
            "change_type": "multi_etf_buy",
            "delta": float(len(etfs)),
            "current_snapshot_date": max(dates) if dates else TODAY,
            "description": (
                f"{len(etfs)} ETFs simultaneously showing increased portfolio "
                f"weight in {ticker}: {', '.join(sorted(etfs))}"
            ),
        })

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

    results = {}   # ticker -> saved | unchanged | failed | skipped
    core = []      # ETFs whose failure should fail the whole job

    # ARK
    for ticker, url in ARK_ETFS.items():
        print(f"\nFetching {ticker} (ARK)...")
        core.append(ticker)
        results[ticker] = save_etf(ticker, fetch_ark(ticker, url))
        time.sleep(1)

    # ARKQ
    print("\nFetching ARKQ (ARK, multi-URL fallback)...")
    core.append("ARKQ")
    results["ARKQ"] = save_etf("ARKQ", fetch_ark_with_fallback("ARKQ", ARKQ_URLS))
    time.sleep(1)

    # Tema
    for ticker, url in TEMA_ETFS.items():
        print(f"\nFetching {ticker} (Tema)...")
        core.append(ticker)
        results[ticker] = save_etf(ticker, fetch_tema(ticker, url))
        time.sleep(1)

    # iShares
    for ticker, config in ISHARES_ETFS.items():
        print(f"\nFetching {ticker} (iShares Active)...")
        core.append(ticker)
        results[ticker] = save_etf(
            ticker, fetch_ishares(ticker, config["product_id"])
        )
        time.sleep(1)

    # Capital Group / Avantis / JPMorgan (optional: skips don't fail the job)
    for ticker, issuer in ADDITIONAL_ETFS.items():
        print(f"\nFetching {ticker} ({issuer})...")
        df = fetch_additional(ticker, issuer)
        results[ticker] = save_etf(ticker, df) if df is not None else "skipped"
        time.sleep(1)

    print("\nGenerating cross-ETF signals...")
    generate_multi_etf_signals()

    saved = [t for t, s in results.items() if s == "saved"]
    unchanged = [t for t, s in results.items() if s == "unchanged"]
    skipped = [t for t, s in results.items() if s == "skipped"]
    failed = [t for t, s in results.items() if s == "failed"]

    print(f"\n{'=' * 55}")
    print(
        f"Done: {len(saved)} new snapshots, {len(unchanged)} unchanged, "
        f"{len(skipped)} skipped, {len(failed)} failed (of {len(results)})"
    )
    if saved:
        print(f"  new:       {', '.join(saved)}")
    if unchanged:
        print(f"  unchanged: {', '.join(unchanged)}")
    if skipped:
        print(f"  skipped:   {', '.join(skipped)}")
    if failed:
        print(f"  failed:    {', '.join(failed)}")

    core_failed = [t for t in core if results.get(t) == "failed"]
    if core_failed:
        print(f"\nCore ETFs failed: {', '.join(core_failed)}")
        sys.exit(1)


if __name__ == "__main__":
    run()
