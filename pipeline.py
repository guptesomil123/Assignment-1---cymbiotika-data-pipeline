"""
=============================================================================
CYMBIOTIKA PIPELINE — FULLY EXPLAINED VERSION
=============================================================================

WHAT DOES THIS FILE DO?
------------------------
This is the DATA PIPELINE. Its job is to:
  1. Ask the mock API for marketing spend data (ad costs)
  2. Ask the mock API for orders data (customer purchases)
  3. Clean and standardise both datasets
  4. Join them together at the campaign x week level
  5. Write the result to a CSV file

Think of it like a factory assembly line:
  Raw API data --> Clean --> Join --> CSV output

HOW IT RELATES TO mock_server.py:
----------------------------------
mock_server.py  = the API (the kitchen that makes the food)
pipeline.py     = the client (the waiter that fetches and serves it)

They run as two separate programs at the same time.
pipeline.py sends requests TO mock_server.py and gets data back.
"""


# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
# Bringing in all the tools we need before we start.
# =============================================================================

import argparse
# argparse lets us accept command-line arguments when running the script.
# Example: python3.11 pipeline.py --start 2025-03-01 --end 2025-03-31
# Without argparse, we'd have to hardcode dates inside the script.

import logging
# logging is Python's built-in system for printing status messages.
# Better than print() because it automatically adds timestamps and labels.
# Example output: "21:02:16  INFO      Fetching marketing spend 2025-04-01"
# The levels are: DEBUG < INFO < WARNING < ERROR < CRITICAL
# We use INFO for normal progress, WARNING for retries/errors.

import time
# time gives us time.sleep(n) which pauses the program for n seconds.
# We use this when the API tells us to slow down (429 rate limit).

from datetime import date, timedelta
# date      = a Python object representing a calendar date (year, month, day)
# timedelta = a duration of time, like "7 days" or "1 day"
# We use timedelta to calculate week_start (the Monday of each week).

from pathlib import Path
# Path makes it easy to work with file and folder locations.
# Example: Path("output") / "myfile.csv" = "output/myfile.csv"
# Works on both Mac and Windows without worrying about / vs \.

from typing import Iterator
# Iterator is a type hint — it's just documentation saying
# "this function yields items one at a time instead of returning a full list."
# Python doesn't enforce this at runtime; it's for human readers.

import pandas as pd
# pandas is the main data analysis library in Python.
# It gives us DataFrames — think of them like spreadsheets in memory.
# We use it to aggregate, join, and write data.
# "pd" is the standard shorthand alias the whole Python world uses.

import requests
# requests is the most popular Python library for making HTTP calls.
# Without it, talking to an API would require a lot of low-level networking code.
# With it: response = requests.get("http://localhost:5001/api/orders")
# That one line sends the request and gives us back the response.


# =============================================================================
# SECTION 2: SETUP
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
# Configure what log messages look like.
# level=logging.INFO means show INFO and above (INFO, WARNING, ERROR).
#   DEBUG messages (very detailed) are hidden.
# format=... defines the layout of each line:
#   %(asctime)s   = the current time (e.g. "21:02:16")
#   %(levelname)s = the level label (e.g. "INFO    " or "WARNING ")
#   %(message)s   = the actual message we wrote
# datefmt="%H:%M:%S" means show time as hours:minutes:seconds only.

log = logging.getLogger("pipeline")
# Create a logger named "pipeline".
# We use log.info(), log.warning() etc. throughout the code.
# Naming it "pipeline" means if this file is imported by another script,
# the logs are clearly labelled as coming from "pipeline".

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
# Define where we'll save our output files.
# Path("output") = a folder called "output" in the current directory.
# .mkdir(exist_ok=True) creates the folder if it doesn't exist yet.
#   exist_ok=True means don't crash if the folder already exists.


# =============================================================================
# SECTION 3: RETRY CONFIGURATION
# =============================================================================
# These numbers control how the pipeline handles errors.
# Defined as constants (ALL_CAPS) at the top so they're easy to change.
# =============================================================================

MAX_RETRIES = 8
# How many times we'll try a request before giving up completely.
# 8 attempts gives us plenty of chances to get past random 429/500 errors.

BASE_BACKOFF = 1.0
# How many seconds to wait before the first retry after a 500 error.
# This doubles each time: 1s, 2s, 4s, 8s, 16s, 30s (capped), 30s, 30s...

MAX_BACKOFF = 30.0
# The maximum we'll ever wait between retries.
# Without this cap, backoff could grow to 128s, 256s etc. which is too long.


# =============================================================================
# SECTION 4: HTTP FETCHING WITH RETRY LOGIC
# =============================================================================
# This is the most important function in the file.
# Everything else builds on top of it.
# =============================================================================

def _get_with_retry(session: requests.Session, url: str, params: dict) -> dict:
    """
    Fetches ONE page from the API. Handles failures automatically.

    PARAMETERS:
      session -- a requests.Session object (like a persistent browser tab)
      url     -- the full endpoint URL (e.g. "http://127.0.0.1:5001/api/orders")
      params  -- a dictionary of URL parameters (e.g. {"start_date": "2025-04-01"})

    RETURNS:
      A Python dictionary containing the parsed JSON response.

    RAISES:
      RuntimeError if all retries are exhausted.
    """

    backoff = BASE_BACKOFF
    # Start the backoff timer at 1 second.
    # This variable increases after each 500 error.

    for attempt in range(1, MAX_RETRIES + 1):
        # Loop up to MAX_RETRIES times.
        # range(1, 9) gives us: 1, 2, 3, 4, 5, 6, 7, 8
        # We start at 1 (not 0) so "attempt 1" reads naturally in log messages.

        try:
            resp = session.get(url, params=params, timeout=10)
            # Send the GET request.
            # params=params automatically formats the dict as URL parameters:
            #   {"start_date": "2025-04-01", "limit": 500}
            #   becomes: ?start_date=2025-04-01&limit=500
            # timeout=10 means: if the server doesn't respond in 10 seconds,
            #   raise an exception instead of waiting forever.

        except requests.RequestException as exc:
            # ---------------------------------------------------------------
            # NETWORK ERROR (e.g. server is down, timeout, DNS failure)
            # requests.RequestException is the parent class of all network errors.
            # We catch it here so a network hiccup doesn't crash the whole pipeline.
            # ---------------------------------------------------------------
            log.warning("Network error attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Network error after {MAX_RETRIES} attempts: {exc}") from exc
            # If we've used all our attempts, give up and crash with a clear message.
            # Otherwise, wait and try again.
            time.sleep(min(backoff, MAX_BACKOFF))
            backoff *= 2
            # backoff *= 2 means: backoff = backoff * 2
            # So: 1s → 2s → 4s → 8s → 16s → 30s (capped) → 30s → 30s
            continue
            # "continue" skips the rest of the loop body and goes back to the top.

        # -----------------------------------------------------------------------
        # If we reach here, we got a response (no network error).
        # Now check the HTTP status code.
        # -----------------------------------------------------------------------

        if resp.status_code == 200:
            return resp.json()
            # 200 = "OK" -- success!
            # resp.json() parses the JSON response body into a Python dictionary.
            # We return it immediately and exit the function.

        if resp.status_code == 429:
            # -------------------------------------------------------------------
            # 429 = "Too Many Requests" -- we're being rate limited.
            # The server is saying: "You're asking too fast. Wait a bit."
            #
            # STRATEGY: Read the Retry-After header and wait EXACTLY that long.
            # We do NOT use our own backoff here -- the server tells us how long.
            # We also do NOT advance our backoff counter -- 429 has its own timer.
            # -------------------------------------------------------------------
            wait = float(resp.headers.get("Retry-After", 2))
            # resp.headers is a dictionary of response headers.
            # "Retry-After" header tells us how many seconds to wait.
            # .get("Retry-After", 2) means: if the header is missing, default to 2.
            # float() converts the string "2" into the number 2.0.

            log.warning("429 rate-limited — waiting %.1f s (attempt %d/%d)", wait, attempt, MAX_RETRIES)
            time.sleep(wait)
            # Sleep for exactly as long as the server asked.
            continue
            # Try again after sleeping.

        if resp.status_code == 500:
            # -------------------------------------------------------------------
            # 500 = "Internal Server Error" -- the server had a bad moment.
            # This is the server's fault, not ours.
            # STRATEGY: Use exponential backoff (wait, then wait longer each time).
            # -------------------------------------------------------------------
            log.warning("500 server error — back-off %.1f s (attempt %d/%d)", backoff, attempt, MAX_RETRIES)
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"500 after {MAX_RETRIES} attempts: {url} params={params}")
            # If we've run out of retries, crash with a clear message.
            time.sleep(min(backoff, MAX_BACKOFF))
            # min(backoff, MAX_BACKOFF) ensures we never wait more than 30 seconds.
            backoff *= 2
            # Double the wait time for next time.
            continue

        # -----------------------------------------------------------------------
        # Any other status code (403, 404, etc.) -- unexpected, crash immediately.
        # We don't retry these because they're not transient errors.
        # -----------------------------------------------------------------------
        raise RuntimeError(f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}")
        # resp.text[:200] shows the first 200 characters of the response body
        # which usually explains what went wrong.

    raise RuntimeError(f"Exhausted {MAX_RETRIES} retries for {url}")
    # This line only runs if somehow the loop finishes without returning or raising.
    # It's a safety net that should never be reached in practice.


# =============================================================================
# SECTION 5: PAGINATORS
# =============================================================================
# These functions handle fetching ALL pages from each endpoint.
# They use _get_with_retry() for each individual page request.
#
# WHY TWO SEPARATE FUNCTIONS?
# Both endpoints use cursors for pagination, but their response shapes differ:
#   /api/marketing-spend  uses: "next_cursor" and "has_more"
#   /api/orders           uses: "pagination.next" and "pagination.more"
# Separate functions make this explicit and easy to debug.
# =============================================================================

def _paginate_spend(
    session: requests.Session,
    base_url: str,
    start_date: str,
    end_date: str,
    page_size: int = 500,
) -> Iterator[dict]:
    """
    Fetches ALL pages from /api/marketing-spend one page at a time.
    Yields individual rows as it goes (doesn't wait to collect all pages first).

    Response envelope shape:
        {
          "data": [...rows...],
          "next_cursor": "eyJvZmZz...",
          "has_more": true
        }
    """

    url = f"{base_url}/api/marketing-spend"
    # f"..." is an f-string -- {base_url} gets replaced with the actual value.
    # e.g. "http://127.0.0.1:5001/api/marketing-spend"

    params: dict = {"start_date": start_date, "end_date": end_date, "limit": page_size}
    # Build the initial parameters dictionary.
    # limit=500 means "give me 500 rows per page" (the maximum the API allows).
    # We'll add "cursor" to this dict for subsequent pages.

    page = 0
    # Counter just for logging purposes (so we can see "page 1, page 2..." in the logs).

    while True:
        # Loop forever -- we break out of it when has_more is False.

        page += 1
        log.info("  spend  page %d  cursor=%s", page, params.get("cursor", "(start)"))
        # Log which page we're fetching.
        # params.get("cursor", "(start)") shows the cursor if we have one,
        # or "(start)" if it's the first page (no cursor yet).

        body = _get_with_retry(session, url, params)
        # Fetch this page, with automatic retry on 429/500.
        # body is a Python dictionary like:
        #   {"data": [...], "next_cursor": "eyJ...", "has_more": true}

        yield from body.get("data", [])
        # "yield from" is like a for loop that yields each item one at a time.
        # body.get("data", []) gets the list of rows, defaulting to [] if missing.
        # This means the caller gets rows as they arrive, page by page,
        # rather than waiting for ALL pages to finish.

        if not body.get("has_more"):
            break
        # If has_more is False (or missing), we have all the data. Stop looping.

        cursor = body.get("next_cursor")
        if not cursor:
            break
        # Double-check: if there's no cursor to use for the next page, stop.
        # This guards against a malformed response.

        params["cursor"] = cursor
        # Add the cursor to our params dict so the next request starts
        # from where this page left off.
        # Example: params becomes {"start_date": "...", "limit": 500, "cursor": "eyJ..."}


def _paginate_orders(
    session: requests.Session,
    base_url: str,
    start_date: str,
    end_date: str,
    page_size: int = 500,
) -> Iterator[dict]:
    """
    Fetches ALL pages from /api/orders one page at a time.

    Response envelope shape -- NOTE: different from /api/marketing-spend!
        {
          "results": [...rows...],          <-- "results" not "data"
          "pagination": {
            "next": "eyJvZmZz...",          <-- nested inside "pagination"
            "more": true                    <-- "more" not "has_more"
          }
        }
    """

    url    = f"{base_url}/api/orders"
    params: dict = {"start_date": start_date, "end_date": end_date, "limit": page_size}
    page   = 0

    while True:
        page += 1
        log.info("  orders page %d  cursor=%s", page, params.get("cursor", "(start)"))
        body = _get_with_retry(session, url, params)

        yield from body.get("results", [])
        # NOTE: "results" here, not "data" like in spend.
        # This is the intentional inconsistency between the two endpoints.

        pagination = body.get("pagination", {})
        # The pagination info is nested inside a "pagination" object.
        # body.get("pagination", {}) gets it, defaulting to {} if missing.

        if not pagination.get("more"):
            break
        # "more" here, not "has_more" like in spend.

        cursor = pagination.get("next")
        if not cursor:
            break
        # "next" here, not "next_cursor" like in spend.

        params["cursor"] = cursor
        # Same pattern as spend -- add cursor to params for the next request.


# =============================================================================
# SECTION 6: FIELD NORMALISATION
# =============================================================================
# The two endpoints return data in different formats:
#   Spend  uses snake_case: campaign_id, spend_usd, campaign_name
#   Orders uses camelCase: attributedCampaignId, netSales, orderId
#
# These functions convert everything to a consistent snake_case format
# AND add the week_start column so downstream code doesn't have to.
# =============================================================================

def _normalise_spend(row: dict) -> dict:
    """
    Takes one raw spend row from the API and returns a clean, typed version.

    INPUT (from API):
        {
          "date": "2025-04-01",
          "channel": "meta",
          "campaign_id": "cmp_8821",
          "campaign_name": "PLTV_Prospecting_US",
          "spend_usd": 1284.55,
          "impressions": 412903,
          "clicks": 8821
        }

    OUTPUT (normalised):
        Same fields but with added week_start, and types guaranteed.
    """

    d = pd.to_datetime(row["date"]).date()
    # pd.to_datetime() converts the string "2025-04-01" into a real date object.
    # .date() strips the time part (pandas adds a midnight time by default).
    # Result: date(2025, 4, 1)

    week_start = d - timedelta(days=d.weekday())
    # Calculate the Monday of the week this date falls in.
    # d.weekday() returns: Monday=0, Tuesday=1, Wednesday=2, ... Sunday=6
    #
    # EXAMPLE:
    #   April 1 2025 is a Tuesday. d.weekday() = 1.
    #   week_start = April 1 - 1 day = March 31 (Monday). Correct!
    #
    #   April 7 2025 is a Monday. d.weekday() = 0.
    #   week_start = April 7 - 0 days = April 7 (Monday). Correct!
    #
    # This is the ISO standard way to find the start of a week.

    return {
        "date":          str(d),
        # str(d) converts date(2025, 4, 1) back to the string "2025-04-01".
        # We store it as a string because CSV files don't have date types.

        "week_start":    str(week_start),
        # The Monday of the week -- e.g. "2025-03-31" for the first week of April.
        # This is the key column we'll use to join spend and orders by week.

        "channel":       row["channel"],
        # "meta", "google", or "tiktok". Already clean, just pass it through.

        "campaign_id":   row["campaign_id"],
        # e.g. "cmp_8821". The unique campaign identifier. Used for joining.

        "campaign_name": row["campaign_name"],
        # e.g. "PLTV_Prospecting_US". Human-readable name.

        "spend_usd":     float(row["spend_usd"]),
        # float() ensures this is a decimal number, not a string.
        # The API sends JSON numbers, but we're explicit about the type.

        "impressions":   int(row["impressions"]),
        # int() ensures this is a whole number (no decimals).

        "clicks":        int(row["clicks"]),
        # Same -- clicks must be whole numbers.
    }


def _normalise_order(row: dict) -> dict:
    """
    Takes one raw order row from the API and returns a clean, typed version.
    Also adds is_unattributed flag for orders missing a campaign_id.

    INPUT (from API -- note camelCase!):
        {
          "orderId": "ord_44102",
          "orderDate": "2025-04-15T18:22:00Z",
          "netSales": 89.50,
          "attributedCampaignId": "cmp_8821",   <-- can be null (~2% of orders)
          "attributedChannel": "Meta",
          "isSubscription": false,
          "discountCode": null
        }

    OUTPUT (normalised -- note snake_case!):
        All camelCase keys converted to snake_case.
        is_unattributed flag added.
    """

    d = pd.to_datetime(row["orderDate"]).date()
    # Same as spend -- convert the timestamp string to a date object.
    # "2025-04-15T18:22:00Z" --> date(2025, 4, 15)
    # The T and Z are part of the ISO 8601 timestamp format.
    # pd.to_datetime handles this automatically.

    week_start = d - timedelta(days=d.weekday())
    # Same week_start calculation as in _normalise_spend.

    campaign_id = row.get("attributedCampaignId")
    # row.get() is safer than row[] because it returns None if the key is missing,
    # instead of crashing with a KeyError.
    # About 2% of orders have null attributedCampaignId -- these are unattributed.

    return {
        "order_id":        row["orderId"],
        # camelCase "orderId" --> snake_case "order_id"

        "order_date":      str(d),
        # The date part of the order timestamp.

        "week_start":      str(week_start),
        # The Monday of the week this order happened in.

        "net_sales":       float(row["netSales"]),
        # camelCase "netSales" --> snake_case "net_sales"
        # This is the revenue from this order in dollars.

        "campaign_id":     campaign_id,
        # camelCase "attributedCampaignId" --> snake_case "campaign_id"
        # Will be None for ~2% of orders (unattributed).

        "channel":         row.get("attributedChannel"),
        # camelCase "attributedChannel" --> snake_case "channel"
        # Also None when unattributed.

        "is_subscription": bool(row.get("isSubscription", False)),
        # camelCase "isSubscription" --> snake_case "is_subscription"
        # bool() ensures it's True/False, not 1/0 or "true"/"false".
        # Default is False if the field is missing.

        "discount_code":   row.get("discountCode"),
        # camelCase "discountCode" --> snake_case "discount_code"
        # Will be None if no discount was used.

        "is_unattributed": campaign_id is None,
        # NEW FIELD we add ourselves -- not from the API.
        # True if campaign_id is None, False otherwise.
        # "campaign_id is None" evaluates to True or False.
        # This flag lets us filter unattributed orders without checking None repeatedly.
    }


# =============================================================================
# SECTION 7: FETCH FUNCTIONS
# =============================================================================
# These functions call the paginators and normalise every row.
# They return complete DataFrames ready for analysis.
# =============================================================================

def fetch_spend(session, base_url, start_date, end_date) -> pd.DataFrame:
    """
    Fetches all spend data and returns a clean DataFrame.
    """
    log.info("Fetching marketing spend %s → %s", start_date, end_date)

    rows = [_normalise_spend(r) for r in _paginate_spend(session, base_url, start_date, end_date)]
    # LIST COMPREHENSION -- a compact way to build a list.
    # For every row r yielded by _paginate_spend(), call _normalise_spend(r).
    # Collect all the results into a list called rows.
    # This is equivalent to:
    #   rows = []
    #   for r in _paginate_spend(session, base_url, start_date, end_date):
    #       rows.append(_normalise_spend(r))

    df = pd.DataFrame(rows)
    # pd.DataFrame(rows) converts a list of dictionaries into a DataFrame.
    # Each dictionary becomes one row.
    # The dictionary keys become the column names.
    # Think of it like creating a spreadsheet from a list of records.

    log.info("  → %d spend rows", len(df))
    # len(df) = number of rows in the DataFrame.
    return df


def fetch_orders(session, base_url, start_date, end_date) -> pd.DataFrame:
    """
    Fetches all orders data and returns a clean DataFrame.
    """
    log.info("Fetching orders %s → %s", start_date, end_date)

    rows = [_normalise_order(r) for r in _paginate_orders(session, base_url, start_date, end_date)]
    df   = pd.DataFrame(rows)

    log.info("  → %d order rows (%d unattributed)",
             len(df), df["is_unattributed"].sum())
    # df["is_unattributed"] is a column of True/False values.
    # .sum() counts the True values (Python treats True as 1 and False as 0).
    # So this tells us how many orders couldn't be attributed to a campaign.

    return df


# =============================================================================
# SECTION 8: THE JOIN — building the weekly performance table
# =============================================================================
# This is the core analytical step.
# We aggregate both datasets to the campaign x week grain, then join them.
#
# WHAT IS A "GRAIN"?
# The grain is the level of detail in a table -- what each row represents.
# campaign x week grain means: one row per campaign per week.
# So if there are 8 campaigns and 5 weeks, the output has 40 rows.
# =============================================================================

def build_weekly_performance(
    spend_df: pd.DataFrame,
    orders_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregates spend and orders to campaign x week grain, then joins them.

    Returns a DataFrame with these columns:
        week_start, channel, campaign_id, campaign_name,
        spend, revenue, orders, roas
    """

    # ── STEP 1: Aggregate spend to week level ──────────────────────────────
    spend_weekly = (
        spend_df
        .groupby(["week_start", "channel", "campaign_id", "campaign_name"], as_index=False)
        .agg(spend=("spend_usd", "sum"))
    )
    # .groupby([...]) groups rows that share the same week_start + channel + campaign.
    # Think of it like a pivot table -- collapsing many daily rows into weekly totals.
    #
    # as_index=False means the groupby columns stay as regular columns,
    # not as the DataFrame index. Easier to work with.
    #
    # .agg(spend=("spend_usd", "sum")) says:
    #   Create a new column called "spend"
    #   by taking the "spend_usd" column and summing it.
    #
    # BEFORE groupby (daily rows):
    #   week_start   campaign_id   spend_usd
    #   2025-03-31   cmp_8821      1284.55
    #   2025-04-01   cmp_8821      2100.30
    #   2025-04-02   cmp_8821       987.44
    #   ...
    #
    # AFTER groupby (weekly totals):
    #   week_start   campaign_id   spend
    #   2025-03-31   cmp_8821      8574.39   <-- sum of all days in that week

    spend_weekly["spend"] = spend_weekly["spend"].round(2)
    # Round the spend to 2 decimal places (like money should be).

    # ── STEP 2: Aggregate ATTRIBUTED orders to week level ──────────────────
    attributed = orders_df[~orders_df["is_unattributed"]]
    # orders_df[~orders_df["is_unattributed"]] filters to keep only rows where
    # is_unattributed is False (i.e. orders that DO have a campaign_id).
    # ~ is the "NOT" operator for pandas boolean columns.
    # Unattributed orders (~2%) are excluded from the join because they have
    # no campaign_id to join on -- but they're logged so we know they exist.

    orders_weekly = (
        attributed
        .groupby(["week_start", "campaign_id"], as_index=False)
        .agg(
            revenue=("net_sales", "sum"),
            # "revenue" column = sum of net_sales for each campaign x week.
            orders=("order_id",  "count"),
            # "orders" column = count of order_id rows (how many orders).
        )
    )
    orders_weekly["revenue"] = orders_weekly["revenue"].round(2)
    # Round revenue to 2 decimal places.

    # ── STEP 3: Join spend and orders ──────────────────────────────────────
    merged = spend_weekly.merge(
        orders_weekly,
        on=["week_start", "campaign_id"],
        how="left",
    )
    # .merge() is like SQL JOIN -- combines two DataFrames based on matching keys.
    #
    # on=["week_start", "campaign_id"] means:
    #   Match rows where BOTH week_start AND campaign_id are the same.
    #   This is the "campaign x week grain" join.
    #
    # how="left" means LEFT JOIN:
    #   Keep ALL rows from spend_weekly (left side).
    #   Fill in revenue/orders from orders_weekly where they match.
    #   If a campaign had spend but zero attributed orders that week,
    #   it still appears with revenue=0 and orders=0.
    #
    # WHY LEFT JOIN and not INNER JOIN?
    #   An inner join would DROP campaigns with no orders.
    #   But we want to see campaigns that spent money but made no sales --
    #   that's important information! Left join keeps them visible.

    merged["revenue"] = merged["revenue"].fillna(0.0)
    # .fillna(0.0) replaces NaN (missing) values with 0.
    # When a campaign had no attributed orders in a week, the left join
    # leaves revenue as NaN. We replace it with 0 to make the data clean.

    merged["orders"] = merged["orders"].fillna(0).astype(int)
    # Same for orders count. Also .astype(int) converts 0.0 to 0
    # because count should be a whole number, not a decimal.

    # ── STEP 4: Calculate ROAS ─────────────────────────────────────────────
    merged["roas"] = merged.apply(
        lambda r: round(r["revenue"] / r["spend"], 4) if r["spend"] > 0 else None,
        axis=1,
    )
    # ROAS = Return on Ad Spend = revenue / spend.
    # Tells you: for every $1 spent on ads, how much revenue did we get back?
    # ROAS of 2.0 means $2 revenue for every $1 spent (good).
    # ROAS of 0.5 means $0.50 revenue for every $1 spent (losing money).
    #
    # .apply(lambda r: ..., axis=1) runs a function on each row.
    # lambda r: ... is an anonymous (unnamed) function that takes a row r.
    #
    # "if r['spend'] > 0 else None" handles divide-by-zero:
    #   If spend is 0, we return None (blank in CSV) instead of crashing.
    #   We use None rather than 0 because a 0 ROAS would be misleading --
    #   it implies we made $0 back, but really we just have no data.
    #
    # round(..., 4) keeps 4 decimal places -- enough precision for ROAS.

    # ── STEP 5: Final column order and sorting ─────────────────────────────
    result = merged[[
        "week_start", "channel", "campaign_id", "campaign_name",
        "spend", "revenue", "orders", "roas",
    ]]
    # Select only the columns we want, in the exact order the spec requires.
    # Any extra columns (like "impressions" from spend) are dropped here.

    result = result.sort_values(["week_start", "channel", "campaign_id"])
    # Sort rows by week first, then channel, then campaign_id.
    # Makes the CSV easy to read chronologically.

    result = result.reset_index(drop=True)
    # Reset the row numbers to 0, 1, 2, 3... after sorting.
    # drop=True means don't save the old index as a column.

    return result


# =============================================================================
# SECTION 9: COMMAND LINE ARGUMENTS
# =============================================================================

def parse_args():
    """
    Defines and reads the command-line arguments for the script.
    Allows the user to customise dates and server URL without editing the code.
    """
    p = argparse.ArgumentParser(description="Cymbiotika API pipeline")
    # Create a parser that will read arguments from the command line.

    p.add_argument("--start", default="2025-04-01", help="Start date YYYY-MM-DD")
    # --start is an optional argument (starts with --).
    # default="2025-04-01" means if the user doesn't provide --start,
    # we use April 1 2025 automatically.
    # help= is the description shown when the user runs: python3.11 pipeline.py --help

    p.add_argument("--end", default="2025-04-30", help="End date YYYY-MM-DD")
    # Same for end date -- defaults to April 30 2025.

    p.add_argument("--base-url", default="http://localhost:5000", help="Mock API base URL")
    # The server address. Default is localhost:5000.
    # We override this with --base-url http://127.0.0.1:5001 when AirPlay
    # is blocking port 5000.

    return p.parse_args()
    # .parse_args() reads sys.argv (the actual command the user typed),
    # matches arguments to what we defined above, and returns an object.
    # Access values like: args.start, args.end, args.base_url


# =============================================================================
# SECTION 10: MAIN FUNCTION — orchestrates everything
# =============================================================================
# This is the "conductor" that calls all the other functions in order.
# =============================================================================

def main():
    args = parse_args()
    # Read the command-line arguments (dates, server URL).

    session = requests.Session()
    # Create a persistent HTTP session.
    # A Session reuses the same underlying TCP connection for multiple requests,
    # which is faster than creating a new connection for every page.
    # It also lets us set headers that apply to every request automatically.

    session.headers.update({"Accept": "application/json"})
    # Tell the server we want JSON responses.
    # "Accept: application/json" is a standard HTTP header that says
    # "I understand JSON, please send data in that format."

    # ── 1. Fetch both endpoints ────────────────────────────────────────────
    spend_df  = fetch_spend(session, args.base_url, args.start, args.end)
    orders_df = fetch_orders(session, args.base_url, args.start, args.end)
    # These two lines do all the heavy lifting:
    # - Paginate through every page
    # - Handle all 429/500 errors with retries
    # - Normalise all field names
    # - Return clean DataFrames

    # ── 2. Save raw data for debugging ────────────────────────────────────
    spend_df.to_csv(OUTPUT_DIR / "marketing_spend_raw.csv",  index=False)
    orders_df.to_csv(OUTPUT_DIR / "orders_raw.csv",          index=False)
    # .to_csv() writes a DataFrame to a CSV file.
    # index=False means don't write the row numbers (0, 1, 2...) as a column.
    # These raw files are useful if the final output looks wrong --
    # you can inspect the raw data to find where the problem is.
    log.info("Raw CSVs saved to output/")

    # ── 3. Build the weekly performance table ─────────────────────────────
    log.info("Joining spend + orders at campaign × week grain…")
    weekly = build_weekly_performance(spend_df, orders_df)
    # This is the core analytical step:
    # aggregate both datasets to campaign x week, then join them.

    # ── 4. Write the required output CSV ──────────────────────────────────
    out_path = OUTPUT_DIR / "campaign_weekly_performance.csv"
    weekly.to_csv(out_path, index=False)
    log.info("Written → %s  (%d rows)", out_path, len(weekly))
    # The main deliverable. Saved to output/campaign_weekly_performance.csv.

    # ── 5. Print a quick summary to the terminal ───────────────────────────
    print("\n── Preview (first 10 rows) ────────────────────────────────────")
    print(weekly.head(10).to_string(index=False))
    # .head(10) returns the first 10 rows.
    # .to_string(index=False) formats it as a readable table without row numbers.

    print(f"\nTotal rows : {len(weekly)}")
    print(f"Total spend: ${weekly['spend'].sum():,.2f}")
    # weekly['spend'].sum() adds up the entire spend column.
    # :,.2f formats the number with commas and 2 decimal places.
    # e.g. 533373.03 becomes "533,373.03"

    print(f"Total rev  : ${weekly['revenue'].sum():,.2f}")
    print(f"Overall ROAS: {weekly['revenue'].sum() / weekly['spend'].sum():.3f}x")
    # Overall ROAS = total revenue / total spend across all campaigns and weeks.
    # :.3f formats to 3 decimal places. e.g. 0.543


# =============================================================================
# SECTION 11: ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()
# This is the standard Python "entry point" pattern.
# __name__ == "__main__" is True when you run this file directly:
#   python3.11 pipeline.py
#
# It would be False if another file imported this file:
#   import pipeline
# In that case, main() would NOT run automatically.
#
# This pattern lets the file work both as a standalone script
# AND as a module that other scripts can import and reuse.
