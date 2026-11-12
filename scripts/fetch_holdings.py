import csv
import os
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
# Capital Group: daily XLSX endpoint (needs openpyxl).
# Avantis: env-var URL override first, else scrape official page (needs bs4).
# JPMorgan: requires env var ALPHARADAR_<ETF>_HOLDINGS_URL.

ADDITIONAL_ETFS = {
    "CGGR": "capital",
    "CGDV": "capital",
    "AVUV": "avantis",
    "AVLV": "avantis",
    "JGRO": "jpmorgan",
    "JAVA": "jpmorgan",
}

AVANTIS_SLUGS = {
    "AVUV": "avantis-us-small-cap-value-etf",
    "AVLV": "avantis-us-large-cap-value-etf",
}


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _clean_and_dedup(df, etf_ticker):
    """Clean weight column, tag etf/date, and deduplicate holdings."""

    df["weight"] = (
        df["weight"].astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["company"] = df["company"].astype(str).str.strip()

    df["etf"] = etf_ticker
    df["date"] = TODAY

    result = df[["etf", "ticker", "company", "weight", "date"]]
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
        f"  [{etf_ticker}] {len(result)} holdings — top: "
        f"{result['ticker'].head(3).tolist()}"
    )

    return result


def _read_holdings_bytes(content: bytes, etf: str):
    """
    Read an XLSX/CSV holdings file and automatically locate the header row
    containing a ticker column (issuer files often have fund info on top).
    """

    if content[:2] == b"PK":
        raw = pd.read_excel(BytesIO(content), header=None)
    elif b"<html" not in content[:500].lower():
        raw = pd.read_csv(
            StringIO(content.decode("utf-8-sig")),
            header=None,
            on_bad_lines="skip",
            engine="python",
        )
    else:
        raise ValueError(f"{etf}: HTML received instead of holdings file")

    for idx in range(min(len(raw), 40)):
        vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist()]
        if any(v in ("ticker", "symbol", "security ticker") for v in vals):
            body = raw.iloc[idx + 1:].copy()
            body.columns = raw.iloc[idx].tolist()
            return body

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
    """Convert issuer data to the existing Supabase schema without inventing data."""

    if raw is None or raw.empty:
        return None

    df = raw.copy()
    df.columns = [
        str(c).strip().lower().replace("\n", " ") for c in df.columns
    ]

    aliases = {
        "ticker": ["ticker", "symbol", "security ticker"],
        "company": [
            "security name", "security description", "company",
            "name", "holding", "description",
        ],
        "weight": [
            "percent of net assets", "% of net assets", "% of assets",
            "weight", "weight (%)", "portfolio weight", "percent of assets",
        ],
    }

    mapping = {}
    for target, options in aliases.items():
        for option in options:
            if option in df.columns:
                mapping[target] = option
                break

    if len(mapping) != 3:
        raise ValueError(
            f"{etf}: required columns missing; received {list(df.columns)}"
        )

    df = df[[mapping[x] for x in ("ticker", "company", "weight")]].copy()
    df.columns = ["ticker", "company", "weight"]

    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["company"] = df["company"].astype(str).str.strip()
    df["weight"] = _new_number(df["weight"])

    df = df[df["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", na=False)]
    df = df[~df["ticker"].isin(["CASH", "USD", "TOTAL", "NAN"])]
    df = df[df["weight"].notna() & (df["weight"] > 0)]
    df = df.drop_duplicates(subset=["ticker"], keep="first")

    if len(df) < 5 or df["weight"].sum() > 125:
        raise ValueError(
            f"{etf}: suspicious holdings: {len(df)} rows, "
            f"weight sum {df['weight'].sum():.2f}"
        )

    df["etf"] = etf
    df["date"] = source_date or TODAY

    return df[["etf", "ticker", "company", "weight", "date"]]


# ─────────────────────────────────────────────────────────────────────────────
# CHANGE DETECTION
# ─────────────────────────────────────────────────────────────────────────────


def detect_changes(etf: str, today_df) -> list:
    """Compare to the latest earlier available snapshot, not calendar yesterday."""

    latest = (
        supabase.table("holdings")
        .select("date")
        .eq("etf", etf)
        .lt("date", str(today_df["date"].iloc[0]))
        .order("date", desc=True)
        .limit(1)
        .execute()
    )

    if not latest.data:
        print(f"  [{etf}] first snapshot; no changes")
        return []

    prev_date = latest.data[0]["date"]

    prior = (
        supabase.table("holdings")
        .select("ticker,weight")
        .eq("etf", etf)
        .eq("date", prev_date)
        .execute()
    )

    old = {r["ticker"]: float(r["weight"]) for r in (prior.data or [])}
    new = dict(zip(today_df["ticker"], today_df["weight"].astype(float)))

    out = []

    for ticker, weight in new.items():
        if ticker not in old:
            out.append({
                "etf": etf,
                "ticker": ticker,
                "change_type": "new_position",
                "delta": round(weight, 4),
                "description": f"{etf} added {ticker} to reported holdings",
            })
        elif abs(weight - old[ticker]) > 0.3:
            delta = round(weight - old[ticker], 4)
            out.append({
                "etf": etf,
                "ticker": ticker,
                "change_type": "accumulation" if delta > 0 else "reduction",
                "delta": delta,
                "description": (
                    f"{etf} {ticker} portfolio weight changed "
                    f"{delta:+.2f} percentage points (not verified trades)"
                ),
            })

    for ticker in old.keys() - new.keys():
        out.append({
            "etf": etf,
            "ticker": ticker,
            "change_type": "removed",
            "delta": 0.0,
            "description": f"{etf} no longer reports {ticker}",
        })

    return out


def save_etf(ticker: str, df) -> bool:

    if df is None or df.empty:
        return False

    records = df.to_dict("records")

    for i in range(0, len(records), 100):
        supabase.table("holdings").upsert(records[i:i + 100]).execute()

    changes = detect_changes(ticker, df)

    if changes:
        supabase.table("holding_changes").insert(changes).execute()

    print(f"  ✓ saved, {len(changes)} changes detected")

    return True


# ─────────────────────────────────────────────────────────────────────────────
# ARK
# ─────────────────────────────────────────────────────────────────────────────


def _parse_ark_text(text: str, etf_ticker: str):
    """ARK CSV: no header row, fixed 8-column format."""

    df = pd.read_csv(StringIO(text), header=None, names=ARK_COLS)

    df = df[df["ticker"].notna()]
    df = df[~df["ticker"].astype(str).str.lower().isin(["ticker", "nan", ""])]

    return _clean_and_dedup(
        df[["ticker", "company", "weight"]].copy(), etf_ticker
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

        if not all([ticker_col, name_col, weight_col]):
            print(
                f"  [{etf_ticker}] ✗ unexpected columns: {list(df.columns)}"
            )
            return None

        df = df[[ticker_col, name_col, weight_col]].copy()
        df.columns = ["ticker", "company", "weight"]

        df = df.dropna(subset=["ticker"])
        df = df[
            ~df["ticker"].astype(str).str.strip().str.lower()
            .isin(["ticker", "nan", "", "-", "cash", "usd"])
        ]

        return _clean_and_dedup(df, etf_ticker)

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
    HTML responses are detected and rejected before reaching pandas.
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

        def row_values(line):
            try:
                return [v.strip().lower() for v in next(csv.reader([line]))]
            except Exception:
                return None

        for idx, line in enumerate(lines):
            values = row_values(line)
            if values is None:
                continue
            if "ticker" in values and (
                "name" in values or "security name" in values
            ):
                header_idx = idx
                break

        if header_idx is None:
            for idx, line in enumerate(lines):
                values = row_values(line)
                if values is not None and "ticker" in values:
                    header_idx = idx
                    break

        if header_idx is None:
            print(f"  [{etf_ticker}] could not find CSV header from {source_url}")
            print(f"  [{etf_ticker}] first 500 chars: {body[:500]!r}")
            return None

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

        df = df[[ticker_col, name_col, weight_col]].copy()
        df.columns = ["ticker", "company", "weight"]

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
            df[["ticker", "company", "weight"]].copy(), etf_ticker
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
                body = sheet.iloc[idx + 1:].copy()
                body.columns = sheet.iloc[idx].tolist()
                try:
                    return _normalize_extra_holdings(body, etf)
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
        return _normalize_extra_holdings(_read_holdings_bytes(r.content, etf), etf)

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
            return _normalize_extra_holdings(
                _read_holdings_bytes(resp.content, etf), etf
            )
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

    return _normalize_extra_holdings(_read_holdings_bytes(r.content, etf), etf)


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

    result = (
        supabase.table("holding_changes")
        .select("ticker, etf, change_type")
        .eq("change_type", "accumulation")
        .gte("created_at", TODAY)
        .execute()
    )

    ticker_etfs = defaultdict(list)

    for row in result.data or []:
        ticker_etfs[row["ticker"]].append(row["etf"])

    signals = [
        {
            "etf": "MULTI",
            "ticker": tkr,
            "change_type": "multi_etf_buy",
            "delta": float(len(etfs)),
            "description": (
                f"{len(etfs)} ETFs simultaneously "
                f"buying {tkr}: {', '.join(etfs)}"
            ),
        }
        for tkr, etfs in ticker_etfs.items()
        if len(etfs) >= 3
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

    # ARK
    for ticker, url in ARK_ETFS.items():
        print(f"\nFetching {ticker} (ARK)...")
        if save_etf(ticker, fetch_ark(ticker, url)):
            success += 1
        time.sleep(1)

    # ARKQ
    print("\nFetching ARKQ (ARK, multi-URL fallback)...")
    if save_etf("ARKQ", fetch_ark_with_fallback("ARKQ", ARKQ_URLS)):
        success += 1
    time.sleep(1)

    # Tema
    for ticker, url in TEMA_ETFS.items():
        print(f"\nFetching {ticker} (Tema)...")
        if save_etf(ticker, fetch_tema(ticker, url)):
            success += 1
        time.sleep(1)

    # iShares
    for ticker, config in ISHARES_ETFS.items():
        print(f"\nFetching {ticker} (iShares Active)...")
        if save_etf(ticker, fetch_ishares(ticker, config["product_id"])):
            success += 1
        time.sleep(1)

    # Capital Group / Avantis / JPMorgan
    for ticker, issuer in ADDITIONAL_ETFS.items():
        print(f"\nFetching {ticker} ({issuer})...")
        df = fetch_additional(ticker, issuer)
        if df is not None and save_etf(ticker, df):
            success += 1
        time.sleep(1)

    total = (
        len(ARK_ETFS) + 1 + len(TEMA_ETFS)
        + len(ISHARES_ETFS) + len(ADDITIONAL_ETFS)
    )

    print("\nGenerating cross-ETF signals...")
    generate_multi_etf_signals()

    print(f"\n{'=' * 55}")
    print(f"Done: {success}/{total} ETFs updated")


if __name__ == "__main__":
    run()
