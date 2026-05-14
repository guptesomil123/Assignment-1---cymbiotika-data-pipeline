"""
=============================================================================
CYMBIOTIKA PIPELINE
=============================================================================

Fetches marketing spend and order data from the mock API, normalises both
schemas, joins them at the campaign x week grain, and writes the output CSV.

Flow:  Raw API data  -->  Normalise  -->  Join  -->  CSV output
"""


# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================

import argparse
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests


# =============================================================================
# SECTION 2: SETUP
# =============================================================================

# Log format: timestamp  LEVEL  message (e.g. "21:02:16  INFO  Fetching spend...")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("pipeline")

# All output files (raw CSVs + final report) land in this folder
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# =============================================================================
# SECTION 3: RETRY CONFIGURATION
# =============================================================================

MAX_RETRIES  = 8    # total attempts before giving up on a page
BASE_BACKOFF = 1.0  # starting wait time (seconds) on a 500 error; doubles each retry
MAX_BACKOFF  = 30.0 # cap so we never wait longer than 30s between retries


# =============================================================================
# SECTION 4: HTTP FETCHING WITH RETRY LOGIC
# =============================================================================

def _get_with_retry(session: requests.Session, url: str, params: dict) -> dict:
    """
    Fetches one page from the API with automatic retry on 429/500/network errors.

    - 429: reads Retry-After header and waits that long before retrying.
    - 500: exponential backoff (1s, 2s, 4s ... capped at 30s).
    - Other non-200 codes: raises immediately (not transient).

    Raises RuntimeError if all retries are exhausted.
    """

    backoff = BASE_BACKOFF

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            resp = session.get(url, params=params, timeout=10)

        except requests.RequestException as exc:
            # Network-level failure (timeout, DNS, connection reset, etc.)
            log.warning("Network error attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Network error after {MAX_RETRIES} attempts: {exc}") from exc
            time.sleep(min(backoff, MAX_BACKOFF))
            backoff *= 2
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            # Rate limited — wait exactly as long as the server asks, then retry
            wait = float(resp.headers.get("Retry-After", 2))
            log.warning("429 rate-limited — waiting %.1f s (attempt %d/%d)", wait, attempt, MAX_RETRIES)
            time.sleep(wait)
            continue

        if resp.status_code == 500:
            # Server-side error — back off and retry; raise if we've run out of attempts
            log.warning("500 server error — back-off %.1f s (attempt %d/%d)", backoff, attempt, MAX_RETRIES)
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"500 after {MAX_RETRIES} attempts: {url} params={params}")
            time.sleep(min(backoff, MAX_BACKOFF))
            backoff *= 2
            continue

        # Anything else (403, 404, etc.) is unexpected — raise immediately
        raise RuntimeError(f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}")

    raise RuntimeError(f"Exhausted {MAX_RETRIES} retries for {url}")


# =============================================================================
# SECTION 5: PAGINATORS
# =============================================================================
# Two separate functions because the endpoints have different envelope shapes:
#   /api/marketing-spend  →  top-level "next_cursor" / "has_more"
#   /api/orders           →  nested "pagination.next" / "pagination.more"
# =============================================================================

def _paginate_spend(
    session: requests.Session,
    base_url: str,
    start_date: str,
    end_date: str,
    page_size: int = 500,
) -> Iterator[dict]:
    """
    Yields all rows from /api/marketing-spend, page by page.

    Envelope shape:
        { "data": [...], "next_cursor": "...", "has_more": true }
    """

    url    = f"{base_url}/api/marketing-spend"
    params: dict = {"start_date": start_date, "end_date": end_date, "limit": page_size}
    page   = 0

    while True:
        page += 1
        log.info("  spend  page %d  cursor=%s", page, params.get("cursor", "(start)"))

        body = _get_with_retry(session, url, params)
        yield from body.get("data", [])  # stream rows to caller as they arrive

        if not body.get("has_more"):
            break

        cursor = body.get("next_cursor")
        if not cursor:
            break  # guard against malformed response with no cursor

        params["cursor"] = cursor  # pass cursor into next request to get the next page


def _paginate_orders(
    session: requests.Session,
    base_url: str,
    start_date: str,
    end_date: str,
    page_size: int = 500,
) -> Iterator[dict]:
    """
    Yields all rows from /api/orders, page by page.

    Envelope shape (different from spend — pagination info is nested):
        { "results": [...], "pagination": { "next": "...", "more": true } }
    """

    url    = f"{base_url}/api/orders"
    params: dict = {"start_date": start_date, "end_date": end_date, "limit": page_size}
    page   = 0

    while True:
        page += 1
        log.info("  orders page %d  cursor=%s", page, params.get("cursor", "(start)"))

        body       = _get_with_retry(session, url, params)
        pagination = body.get("pagination", {})  # pagination info is nested here, unlike spend

        yield from body.get("results", [])  # note: "results" not "data" like spend

        if not pagination.get("more"):
            break

        cursor = pagination.get("next")
        if not cursor:
            break

        params["cursor"] = cursor


# =============================================================================
# SECTION 6: FIELD NORMALISATION
# =============================================================================
# Converts both API schemas to consistent snake_case and adds week_start.
# Spend uses snake_case; orders use camelCase — normalised here so downstream
# code only ever sees one schema.
# =============================================================================

def _normalise_spend(row: dict) -> dict:
    """
    Normalises one raw spend row.
    Adds week_start (ISO Monday of the row's date).
    """

    d          = pd.to_datetime(row["date"]).date()
    week_start = d - timedelta(days=d.weekday())  # roll back to Monday of that week

    return {
        "date":          str(d),
        "week_start":    str(week_start),  # used as the join key downstream
        "channel":       row["channel"],
        "campaign_id":   row["campaign_id"],
        "campaign_name": row["campaign_name"],
        "spend_usd":     float(row["spend_usd"]),
        "impressions":   int(row["impressions"]),
        "clicks":        int(row["clicks"]),
    }


def _normalise_order(row: dict) -> dict:
    """
    Normalises one raw order row (camelCase → snake_case).
    Adds week_start and is_unattributed flag.
    ~2% of orders have no attributedCampaignId — flagged rather than dropped.
    """

    d           = pd.to_datetime(row["orderDate"]).date()
    week_start  = d - timedelta(days=d.weekday())
    campaign_id = row.get("attributedCampaignId")  # will be None for ~2% of orders

    return {
        "order_id":        row["orderId"],
        "order_date":      str(d),
        "week_start":      str(week_start),
        "net_sales":       float(row["netSales"]),
        "campaign_id":     campaign_id,
        "channel":         row.get("attributedChannel"),
        "is_subscription": bool(row.get("isSubscription", False)),
        "discount_code":   row.get("discountCode"),
        "is_unattributed": campaign_id is None,  # True when order has no campaign attribution
    }


# =============================================================================
# SECTION 7: FETCH FUNCTIONS
# =============================================================================
# Orchestrate pagination + normalisation and return clean DataFrames.
# =============================================================================

def fetch_spend(session, base_url, start_date, end_date) -> pd.DataFrame:
    """Fetches all spend pages, normalises each row, and returns a clean DataFrame."""

    log.info("Fetching marketing spend %s → %s", start_date, end_date)
    rows = [_normalise_spend(r) for r in _paginate_spend(session, base_url, start_date, end_date)]
    df   = pd.DataFrame(rows)
    log.info("  → %d spend rows", len(df))
    return df


def fetch_orders(session, base_url, start_date, end_date) -> pd.DataFrame:
    """Fetches all order pages, normalises each row, and returns a clean DataFrame."""

    log.info("Fetching orders %s → %s", start_date, end_date)
    rows = [_normalise_order(r) for r in _paginate_orders(session, base_url, start_date, end_date)]
    df   = pd.DataFrame(rows)
    log.info("  → %d order rows (%d unattributed)", len(df), df["is_unattributed"].sum())
    return df


# =============================================================================
# SECTION 8: JOIN — build the weekly performance table
# =============================================================================
# Aggregates both datasets to campaign x week grain, then merges them.
# Left join so campaigns with spend but zero attributed orders still appear.
# ROAS = revenue / spend; None when spend is zero (not 0, which is misleading).
# =============================================================================

def build_weekly_performance(
    spend_df: pd.DataFrame,
    orders_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Joins spend and orders at the campaign x week grain.

    Output columns: week_start, channel, campaign_id, campaign_name,
                    spend, revenue, orders, roas
    """

    # ── STEP 1: Aggregate spend to week level ──────────────────────────────
    # Collapses daily spend rows into one total per campaign per week
    spend_weekly = (
        spend_df
        .groupby(["week_start", "channel", "campaign_id", "campaign_name"], as_index=False)
        .agg(spend=("spend_usd", "sum"))
    )
    spend_weekly["spend"] = spend_weekly["spend"].round(2)

    # ── STEP 2: Aggregate attributed orders to week level ──────────────────
    # Exclude unattributed orders — they have no campaign_id to join on
    attributed = orders_df[~orders_df["is_unattributed"]]

    orders_weekly = (
        attributed
        .groupby(["week_start", "campaign_id"], as_index=False)
        .agg(
            revenue=("net_sales", "sum"),   # total revenue per campaign per week
            orders=("order_id",  "count"),  # total order count per campaign per week
        )
    )
    orders_weekly["revenue"] = orders_weekly["revenue"].round(2)

    # ── STEP 3: Left join spend + orders ───────────────────────────────────
    # Left join keeps all spend rows — campaigns with no orders still show up with revenue=0
    merged = spend_weekly.merge(
        orders_weekly,
        on=["week_start", "campaign_id"],
        how="left",
    )
    merged["revenue"] = merged["revenue"].fillna(0.0)  # no matched orders → revenue 0
    merged["orders"]  = merged["orders"].fillna(0).astype(int)

    # ── STEP 4: Calculate ROAS ─────────────────────────────────────────────
    # ROAS = revenue / spend. None when spend is 0 to avoid divide-by-zero or misleading 0x
    merged["roas"] = merged.apply(
        lambda r: round(r["revenue"] / r["spend"], 4) if r["spend"] > 0 else None,
        axis=1,
    )

    # ── STEP 5: Final column order and sort ────────────────────────────────
    result = merged[[
        "week_start", "channel", "campaign_id", "campaign_name",
        "spend", "revenue", "orders", "roas",
    ]]
    result = result.sort_values(["week_start", "channel", "campaign_id"])
    result = result.reset_index(drop=True)

    return result


# =============================================================================
# SECTION 9: COMMAND LINE ARGUMENTS
# =============================================================================

def parse_args():
    """
    Parses --start, --end, and --base-url flags.
    Defaults to April 2025 against localhost:5000 if not provided.
    """

    p = argparse.ArgumentParser(description="Cymbiotika API pipeline")
    p.add_argument("--start",    default="2025-04-01",           help="Start date YYYY-MM-DD")
    p.add_argument("--end",      default="2025-04-30",           help="End date YYYY-MM-DD")
    p.add_argument("--base-url", default="http://localhost:5000", help="Mock API base URL")
    return p.parse_args()


# =============================================================================
# SECTION 10: MAIN — orchestrates everything
# =============================================================================

def main():
    args    = parse_args()
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})  # tell the API we want JSON back

    # ── 1. Fetch both endpoints ────────────────────────────────────────────
    spend_df  = fetch_spend(session, args.base_url, args.start, args.end)
    orders_df = fetch_orders(session, args.base_url, args.start, args.end)

    # ── 2. Save raw data for debugging ────────────────────────────────────
    # Useful if the final output looks wrong — check these first
    spend_df.to_csv(OUTPUT_DIR / "marketing_spend_raw.csv",  index=False)
    orders_df.to_csv(OUTPUT_DIR / "orders_raw.csv",          index=False)
    log.info("Raw CSVs saved to output/")

    # ── 3. Build the weekly performance table ─────────────────────────────
    log.info("Joining spend + orders at campaign × week grain…")
    weekly = build_weekly_performance(spend_df, orders_df)

    # ── 4. Write the required output CSV ──────────────────────────────────
    out_path = OUTPUT_DIR / "campaign_weekly_performance.csv"
    weekly.to_csv(out_path, index=False)
    log.info("Written → %s  (%d rows)", out_path, len(weekly))

    # ── 5. Print a quick summary ───────────────────────────────────────────
    print("\n── Preview (first 10 rows) ────────────────────────────────────")
    print(weekly.head(10).to_string(index=False))
    print(f"\nTotal rows : {len(weekly)}")
    print(f"Total spend: ${weekly['spend'].sum():,.2f}")
    print(f"Total rev  : ${weekly['revenue'].sum():,.2f}")
    print(f"Overall ROAS: {weekly['revenue'].sum() / weekly['spend'].sum():.3f}x")


# =============================================================================
# SECTION 11: ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()
