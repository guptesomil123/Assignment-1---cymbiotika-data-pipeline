# =============================================================================
#
#   CYMBIOTIKA MOCK API SERVER — DEEPLY EXPLAINED VERSION
#   Every single line explained in plain English.
#
# =============================================================================
#
# WHAT IS THIS FILE?
# ------------------
# This is a FAKE web server written in Python.
# It pretends to be a real company's API so that developers can test their
# code without needing access to real company data or systems.
#
# Think of it like a "flight simulator" — pilots practice in a simulator
# before flying real planes. This server lets developers practice pulling
# data before connecting to the real thing.
#
# WHAT DOES IT DO?
# ----------------
# Once you run it, it starts listening for requests on your computer.
# Other programs (like your data pipeline) can ask it:
#   "Give me all the ad spend data for January 2024"
#   "Give me all the customer orders for last month"
# ...and it makes up realistic fake data and sends it back.
#
# HOW TO RUN IT:
# --------------
#   Step 1: pip install flask      (installs the web server library)
#   Step 2: python mock_server.py  (starts the server)
#
# After that, it runs at http://localhost:5000
#   "localhost" = this very computer (not the internet, just your machine)
#   "5000"      = the port number (like a door number on a building)
#
# =============================================================================


# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
# Before we can use any tools, we have to "import" them.
# Think of imports like getting ingredients out of the pantry before cooking.
# Python has thousands of built-in and downloadable tools (called libraries).
# We only bring in what we need.
# =============================================================================


import base64
# -----------------------------------------------------------------------------
# WHAT IS base64?
# base64 is a way to encode (scramble) data into a safe string of characters.
# It only uses letters (A-Z, a-z), numbers (0-9), and +, /, = symbols.
# This is useful because some systems don't handle special characters well.
#
# WHY DO WE NEED IT HERE?
# We use base64 to encode our "cursor" (page bookmark).
# A cursor tells the API "start from row 100" or "start from row 200".
# Instead of sending that as a plain number, we disguise it as a scrambled
# string so it looks like a proper API token.
#
# EXAMPLE:
#   The number/dict {"offset": 100}
#   becomes the string "eyJvZmZzZXQiOiAxMDB9"
# This is the same data, just encoded. We can always decode it back.
# -----------------------------------------------------------------------------


import json
# -----------------------------------------------------------------------------
# WHAT IS json?
# JSON stands for JavaScript Object Notation. It's a standard format for
# sending structured data between programs over the internet.
# It looks like a Python dictionary: {"key": "value", "number": 42}
#
# WHY IS IT IMPORTANT?
# APIs communicate using JSON. When your pipeline asks "give me orders",
# the server sends back a JSON response like:
#   {
#     "results": [...list of orders...],
#     "pagination": {"next": "abc123", "more": true}
#   }
# The json library helps us:
#   - json.dumps()  : convert a Python dict INTO a JSON string
#   - json.loads()  : convert a JSON string BACK into a Python dict
# -----------------------------------------------------------------------------


import random
# -----------------------------------------------------------------------------
# WHAT IS random?
# The random library generates random (unpredictable) numbers.
#
# WHY DO WE NEED IT?
# Since this is a fake server with no real database, we use random numbers
# to invent realistic-looking data:
#   - random ad spend amounts ($150 to $4500)
#   - random number of orders per day (60 to 90)
#   - random order values ($35 to $220)
#
# We ALSO use it to randomly break the server on purpose (to test your
# pipeline's ability to recover from errors). More on that later.
#
# KEY FUNCTIONS WE USE:
#   random.seed(42)        -- makes random numbers predictable (explained below)
#   random.uniform(a, b)   -- random decimal between a and b
#   random.randint(a, b)   -- random whole number between a and b
#   random.random()        -- random decimal between 0.0 and 1.0
#   random.choice(list)    -- pick one random item from a list
# -----------------------------------------------------------------------------


from datetime import datetime, timedelta
# -----------------------------------------------------------------------------
# WHAT IS datetime?
# The datetime module helps Python work with dates and times.
# Without it, a "date" is just a string like "2024-01-15" with no meaning.
# With it, Python understands dates and can do math on them.
#
# WE IMPORT TWO THINGS FROM IT:
#
# 1. datetime -- a class that represents a specific moment in time.
#    Example: datetime(2024, 1, 15, 14, 30, 0) = Jan 15 2024 at 2:30 PM
#    It also has useful methods like:
#      .strftime("%Y-%m-%d")   -- format a date as a string "2024-01-15"
#      .strptime("2024-01-15") -- parse a string into a real date object
#
# 2. timedelta -- represents a DURATION of time (a gap between two moments).
#    Example: timedelta(days=1) = "one day"
#    We use it to move forward one day at a time in our loops:
#      d = start_date
#      d += timedelta(days=1)   # move to next day
# -----------------------------------------------------------------------------


from flask import Flask, jsonify, request, make_response
# -----------------------------------------------------------------------------
# WHAT IS flask?
# Flask is a Python library for building web servers (APIs).
# It's like a toolkit that handles all the boring networking stuff
# so you can focus on writing your actual logic.
#
# WE IMPORT FOUR THINGS FROM FLASK:
#
# 1. Flask
#    The main class. You create one instance of it and it becomes your server.
#    app = Flask(__name__)   <-- this creates the server
#
# 2. jsonify
#    A helper that converts a Python dictionary into a proper HTTP JSON response.
#    Without jsonify, you'd have to manually set headers and encode the data.
#    With jsonify, you just do: return jsonify({"key": "value"})
#    Flask automatically sets the Content-Type to "application/json".
#
# 3. request
#    This object gives you access to what the CALLER sent.
#    When someone calls:
#      GET /api/orders?start_date=2024-01-01&end_date=2024-01-31&limit=100
#    You can read those parameters with:
#      request.args.get("start_date")  --> "2024-01-01"
#      request.args.get("limit")       --> "100"
#
# 4. make_response
#    Lets you build a response with a custom HTTP status code and headers.
#    We use it when we want to return errors like 429 or 500,
#    and also attach extra information like the "Retry-After" header.
# -----------------------------------------------------------------------------


# =============================================================================
# SECTION 2: CREATE THE SERVER APPLICATION
# =============================================================================

app = Flask(__name__)
# -----------------------------------------------------------------------------
# This single line creates the entire web server application.
#
# Flask(__name__) creates a new Flask "app" object.
# __name__ is a special Python variable that holds the name of the current file.
# Flask uses it to know where to look for templates and static files.
# In most simple cases like this, it doesn't matter much -- it's just a
# required convention.
#
# After this line, "app" is our server. We'll attach all our endpoints to it
# using the @app.route() decorator (explained later).
# -----------------------------------------------------------------------------


# =============================================================================
# SECTION 3: SEED THE RANDOM NUMBER GENERATOR
# =============================================================================

random.seed(42)
# -----------------------------------------------------------------------------
# WHAT DOES "SEEDING" MEAN?
# Random number generators aren't truly random -- they follow a mathematical
# formula. But the formula needs a starting number, called a "seed."
#
# SAME SEED = SAME SEQUENCE OF NUMBERS, EVERY SINGLE TIME.
# DIFFERENT SEED = COMPLETELY DIFFERENT SEQUENCE.
#
# WHY DO WE USE seed(42)?
# By seeding with 42, we make the fake data REPRODUCIBLE.
# Every time you start the server and ask for "January 2024 data",
# you'll get the EXACT SAME spend amounts and orders as last time.
# This is helpful because it means data comparisons are consistent.
#
# THE NUMBER 42 HAS NO SPECIAL MEANING.
# It's a pop culture reference to "The Hitchhiker's Guide to the Galaxy"
# where 42 is "the answer to life, the universe, and everything."
# Developers use it as a joke. Any number would work.
#
# IMPORTANT: THE FAILURE INJECTION IS NOT SEEDED.
# The _maybe_fail() function (which randomly causes 429/500 errors) calls
# random.random() AFTER the seed sequence has moved forward unpredictably.
# This means errors are genuinely random -- you can't predict when they'll hit.
# That's intentional, to force your pipeline to handle REAL unpredictability.
# -----------------------------------------------------------------------------


# =============================================================================
# SECTION 4: CONSTANT DATA (things that never change)
# =============================================================================

CHANNELS = ["meta", "google", "tiktok"]
# -----------------------------------------------------------------------------
# A simple list of the three advertising platforms (channels) this fake
# company uses. Written in ALL_CAPS because it's a constant -- a value
# that never changes while the program runs.
#
# These are real ad platforms:
#   meta   = Facebook & Instagram ads
#   google = Google Search, YouTube, Display ads
#   tiktok = TikTok short-video ads
#
# NOTE: This list isn't actually used directly in the main logic.
# The channel info is baked into each CAMPAIGN tuple below.
# It's defined here for clarity and potential future use.
# -----------------------------------------------------------------------------


CAMPAIGNS = [
    ("cmp_8821", "PLTV_Prospecting_US",    "meta"),
    ("cmp_8822", "Retargeting_Subscribers", "meta"),
    ("cmp_8823", "Lookalike_LTV90",         "meta"),
    ("cmp_9001", "Brand_Search_Exact",      "google"),
    ("cmp_9002", "NonBrand_Wellness",       "google"),
    ("cmp_9003", "PMax_DTC",               "google"),
    ("cmp_7701", "TT_Spark_UGC",           "tiktok"),
    ("cmp_7702", "TT_Prospecting",         "tiktok"),
]
# -----------------------------------------------------------------------------
# A list of 8 fake advertising campaigns. This is the master list that all
# generated data references.
#
# WHAT IS A "CAMPAIGN"?
# In digital advertising, a campaign is a set of ads grouped together
# with a specific goal, budget, and target audience.
# Example: "Retargeting_Subscribers" = show ads to people who already
# signed up but haven't bought recently, trying to win them back.
#
# STRUCTURE:
# Each entry is a "tuple" -- a fixed group of 3 values in parentheses:
#   (campaign_id, campaign_name, channel)
#
#   campaign_id   -- a short unique code like "cmp_8821"
#                    (like a product SKU or employee ID)
#   campaign_name -- a human-readable name describing the campaign's strategy
#   channel       -- which platform this campaign runs on
#
# CAMPAIGN NAME MEANINGS (for context):
#   PLTV_Prospecting_US     = "Predicted Lifetime Value" -- targeting new users
#                              likely to become high-value customers
#   Retargeting_Subscribers = showing ads to people who already subscribed
#                              but may have lapsed
#   Lookalike_LTV90         = targeting people who "look like" the top 90%
#                              of existing customers by spending behavior
#   Brand_Search_Exact      = Google ads shown when someone searches
#                              exactly "Cymbiotika"
#   NonBrand_Wellness       = Google ads shown for general wellness keywords
#                              like "best supplements" (not brand name searches)
#   PMax_DTC                = "Performance Max Direct to Consumer" -- Google's
#                              automated campaign type across all Google channels
#   TT_Spark_UGC            = TikTok "Spark Ads" using User Generated Content
#                              (real customer videos boosted as ads)
#   TT_Prospecting          = TikTok ads targeting new potential customers
#
# THIS LIST IS USED IN TWO PLACES:
#   1. _generate_spend()  -- every campaign gets a spend row for every day
#   2. _generate_orders() -- each order is randomly attributed to one campaign
# -----------------------------------------------------------------------------


# =============================================================================
# SECTION 5: DATA GENERATION FUNCTIONS
# =============================================================================
# These functions don't read from any database.
# They INVENT fake but realistic data using random numbers and the campaign list.
# =============================================================================


def _generate_spend(start_date, end_date):
    # -------------------------------------------------------------------------
    # FUNCTION NAME: _generate_spend
    # The underscore at the start (_) is a Python convention meaning
    # "this is a private/internal function." It's not meant to be called
    # from outside this file -- only used internally.
    #
    # PURPOSE:
    # Creates a list of fake daily ad spend records.
    # For EVERY day in the date range, and for EVERY campaign,
    # it creates one row of spend data.
    #
    # So if you ask for 30 days of data:
    #   30 days x 8 campaigns = 240 rows total
    #
    # PARAMETERS:
    #   start_date -- a Python date object for the first day (e.g. Jan 1 2024)
    #   end_date   -- a Python date object for the last day  (e.g. Jan 31 2024)
    #
    # RETURNS:
    #   A list of dictionaries. Each dictionary is one row of spend data.
    # -------------------------------------------------------------------------

    rows = []
    # Start with an empty list. We'll add one dictionary per row as we go.
    # Think of this like starting with an empty spreadsheet.

    d = start_date
    # d = "current date we're processing"
    # We start at start_date and move forward one day at a time.

    while d <= end_date:
        # -----------------------------------------------------------------------
        # OUTER LOOP: runs once per day
        # "While today's date (d) hasn't passed the end date, keep going."
        # So if start=Jan 1, end=Jan 3, this loop runs 3 times:
        #   d = Jan 1, then Jan 2, then Jan 3, then Jan 4 > Jan 3 so STOP.
        # -----------------------------------------------------------------------

        for campaign_id, campaign_name, channel in CAMPAIGNS:
            # -------------------------------------------------------------------
            # INNER LOOP: runs once per campaign (8 campaigns total)
            # For each day, we loop through all 8 campaigns.
            # "for X in CAMPAIGNS" unpacks each tuple automatically:
            #   campaign_id   = "cmp_8821"
            #   campaign_name = "PLTV_Prospecting_US"
            #   channel       = "meta"
            # -------------------------------------------------------------------

            spend = round(random.uniform(150, 4500), 2)
            # -------------------------------------------------------------------
            # GENERATING FAKE SPEND AMOUNT:
            # random.uniform(150, 4500) picks a random decimal number
            # anywhere between 150.0 and 4500.0.
            # Examples it might return: 347.82, 2913.56, 891.44
            #
            # round(..., 2) rounds to 2 decimal places so it looks like money.
            # Example: 347.826314 --> 347.83
            # -------------------------------------------------------------------

            impressions = int(spend * random.uniform(200, 400))
            # -------------------------------------------------------------------
            # GENERATING FAKE IMPRESSIONS (how many people SAW the ad):
            #
            # In real advertising, more money spent = more people reached.
            # We simulate this by multiplying spend by a random number (200-400).
            # This means: for every $1 spent, roughly 200-400 people see the ad.
            #
            # Example: spend=$500, multiplier=300 --> impressions=150,000
            #
            # int(...) removes the decimal part since you can't have
            # half an impression. 150284.7 --> 150284
            # -------------------------------------------------------------------

            clicks = int(impressions * random.uniform(0.005, 0.025))
            # -------------------------------------------------------------------
            # GENERATING FAKE CLICKS (how many people CLICKED the ad):
            #
            # In real advertising, only a small fraction of people who see an ad
            # actually click it. This is called Click-Through Rate (CTR).
            # Typical CTR is 0.5% to 2.5%, which is 0.005 to 0.025 as a decimal.
            #
            # Example: impressions=150,000, CTR=0.01 (1%) --> clicks=1,500
            #
            # int(...) rounds down since you can't have half a click.
            # -------------------------------------------------------------------

            rows.append({
                # ---------------------------------------------------------------
                # .append() adds a new item to the end of the rows list.
                # We're adding a dictionary (a set of key-value pairs) that
                # represents one row of spend data -- like one row in a spreadsheet.
                # ---------------------------------------------------------------
                "date":          d.strftime("%Y-%m-%d"),
                # d.strftime("%Y-%m-%d") converts the date object into a string.
                # "%Y" = 4-digit year (2024), "%m" = 2-digit month (01), "%d" = 2-digit day (15)
                # Result: "2024-01-15"
                # APIs always send dates as strings, not Python date objects.

                "channel":       channel,
                # "meta", "google", or "tiktok" -- from the campaign tuple.

                "campaign_id":   campaign_id,
                # e.g. "cmp_8821" -- the unique identifier for this campaign.

                "campaign_name": campaign_name,
                # e.g. "PLTV_Prospecting_US" -- human-readable campaign name.

                "spend_usd":     spend,
                # The random dollar amount we generated above.

                "impressions":   impressions,
                # The random impression count we generated above.

                "clicks":        clicks,
                # The random click count we generated above.
            })
            # ---------------------------------------------------------------
            # NOTICE: spend data uses snake_case (words_separated_by_underscores)
            # for all key names: spend_usd, campaign_id, campaign_name.
            # But orders (in _generate_orders below) use camelCase (wordsJoined
            # with capital letters): netSales, orderId, attributedCampaignId.
            # THIS INCONSISTENCY IS INTENTIONAL.
            # Real company APIs are often inconsistent across endpoints.
            # Your pipeline needs to handle both naming styles.
            # ---------------------------------------------------------------

        d += timedelta(days=1)
        # -----------------------------------------------------------------------
        # MOVE TO THE NEXT DAY.
        # timedelta(days=1) represents a duration of exactly 1 day.
        # Adding it to the current date moves us forward by one day.
        # Example: d = Jan 1, 2024  -->  d = Jan 2, 2024
        # This is how we "walk" through the date range day by day.
        # -----------------------------------------------------------------------

    return rows
    # After all days and all campaigns have been processed, return the
    # complete list of spend rows. If you asked for 30 days, this list
    # will have 30 * 8 = 240 items.


def _generate_orders(start_date, end_date):
    # -------------------------------------------------------------------------
    # FUNCTION NAME: _generate_orders
    # PURPOSE: Creates a list of fake customer order records.
    #
    # Unlike spend (which has exactly 1 row per campaign per day),
    # orders are more variable: 60 to 90 random orders per day,
    # each attributed to a randomly chosen campaign.
    #
    # PARAMETERS:
    #   start_date -- first day to generate orders for
    #   end_date   -- last day to generate orders for
    #
    # RETURNS:
    #   A list of order dictionaries.
    #   If you ask for 30 days: roughly 30 * 75 = ~2,250 orders.
    # -------------------------------------------------------------------------

    rows = []
    # Empty list, same as in _generate_spend.

    order_counter = 40000
    # We use a counter to give each order a unique ID.
    # Starting at 40000 makes the IDs look like real order numbers
    # (as if the company already processed 40,000 orders before this period).
    # First order = "ord_40000", second = "ord_40001", and so on.

    d = start_date
    while d <= end_date:
        # Loop through every day, same as in _generate_spend.

        n_orders = random.randint(60, 90)
        # Decide how many orders happened on this day.
        # random.randint(60, 90) picks a whole number between 60 and 90, inclusive.
        # So some days have 60 orders, some have 90 -- just like real e-commerce.

        for _ in range(n_orders):
            # -----------------------------------------------------------------------
            # Loop n_orders times to create that many order records.
            # The variable is named _ (underscore) because we don't actually use
            # the loop counter -- we just need to repeat the block n_orders times.
            # This is a Python convention: _ means "I don't care about this value."
            # -----------------------------------------------------------------------

            campaign_id, campaign_name, channel = random.choice(CAMPAIGNS)
            # -----------------------------------------------------------------------
            # ATTRIBUTION: Pick which campaign "gets credit" for this order.
            # random.choice(CAMPAIGNS) picks one random tuple from the CAMPAIGNS list.
            # Then we unpack it into three variables just like in _generate_spend.
            #
            # In real life, attribution tracking tries to figure out which ad
            # a customer saw before buying. Here we just pick one randomly.
            # -----------------------------------------------------------------------

            net_sales = round(random.uniform(35, 220), 2)
            # The dollar value of this order.
            # random.uniform(35, 220) gives a random decimal between $35 and $220.
            # round(..., 2) keeps it to 2 decimal places (like real currency).
            # Example: $89.47, $156.20, $42.99

            is_sub = random.random() < 0.42
            # -----------------------------------------------------------------------
            # SUBSCRIPTION CHECK: Is this a subscription order?
            # random.random() returns a decimal between 0.0 and 1.0.
            # If it's less than 0.42, is_sub = True. Otherwise False.
            # This gives us a 42% subscription rate.
            #
            # HOW THIS WORKS:
            # Imagine a random number line from 0.0 to 1.0.
            # The first 42% of that line (0.0 to 0.42) = True (subscription).
            # The remaining 58% (0.42 to 1.0) = False (one-time purchase).
            # -----------------------------------------------------------------------

            discount = random.choice([None, None, None, "SPRING20", "WELCOME10"])
            # -----------------------------------------------------------------------
            # DISCOUNT CODE: Did this order use a discount code?
            # random.choice picks one item from this list at random.
            # The list has 5 items: 3 are None, 1 is "SPRING20", 1 is "WELCOME10".
            # So the probabilities are:
            #   60% chance = no discount (None)
            #   20% chance = "SPRING20"
            #   20% chance = "WELCOME10"
            # This is a neat trick: repeat items in a list to weight probabilities.
            # -----------------------------------------------------------------------

            # -------------------------------------------------------------------
            # THE MOST IMPORTANT PART: INTENTIONAL MISSING DATA
            # -------------------------------------------------------------------
            attr_campaign = campaign_id if random.random() > 0.02 else None
            # -----------------------------------------------------------------------
            # This is where the 2% unattributed orders come from.
            #
            # random.random() > 0.02 means:
            #   98% of the time (when r > 0.02): attr_campaign = campaign_id
            #   2%  of the time (when r <= 0.02): attr_campaign = None
            #
            # When attr_campaign is None, we DON'T know which ad caused this purchase.
            # This is called an "unattributed" order.
            #
            # WHY DOES THIS HAPPEN IN REAL LIFE?
            # - The customer used an ad blocker that blocked tracking pixels.
            # - The customer saw an ad on one device but bought on a different one.
            # - The tracking cookie expired before the purchase.
            # - The customer typed the URL directly without clicking an ad.
            #
            # YOUR PIPELINE MUST HANDLE THIS:
            # You can't just ignore these orders or your revenue totals will be wrong.
            # The pipeline should flag them as "unattributed" and report on them.
            # -----------------------------------------------------------------------

            attr_channel = channel.title() if attr_campaign else None
            # -----------------------------------------------------------------------
            # If the order has an attributed campaign, also record the channel.
            # If the order is unattributed (attr_campaign is None), channel is also None.
            #
            # .title() capitalises the first letter of each word.
            # "meta"   --> "Meta"
            # "google" --> "Google"
            # "tiktok" --> "Tiktok"
            #
            # ANOTHER INCONSISTENCY:
            # Spend data stores channel in lowercase: "meta", "google"
            # Orders store it title-cased: "Meta", "Google"
            # Again, this mirrors real-world messiness.
            # -----------------------------------------------------------------------

            ts = datetime.combine(d, datetime.min.time()) + timedelta(
                hours=random.randint(0, 23), minutes=random.randint(0, 59)
            )
            # -----------------------------------------------------------------------
            # CREATE A FULL TIMESTAMP for the order (date + time).
            # Spend data only has a date. Orders have a precise time too.
            #
            # STEP BY STEP:
            # 1. datetime.min.time()
            #    This gives us midnight: time(0, 0, 0) = 00:00:00
            #
            # 2. datetime.combine(d, datetime.min.time())
            #    Combines a date (e.g. Jan 15 2024) with a time (midnight)
            #    to get a full datetime: 2024-01-15 00:00:00
            #
            # 3. + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
            #    Adds a random number of hours (0-23) and minutes (0-59).
            #    This spreads orders randomly across the full day.
            #    Result: could be 2024-01-15 14:37:00 or 2024-01-15 03:22:00 etc.
            # -----------------------------------------------------------------------

            rows.append({
                "orderId":              f"ord_{order_counter}",
                # f"ord_{order_counter}" is an f-string (formatted string).
                # The {order_counter} part gets replaced with the actual number.
                # If order_counter = 40000, this becomes "ord_40000".
                # Each order gets a unique ID this way.

                "orderDate":            ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                # Format the timestamp as an ISO 8601 string.
                # "%Y-%m-%dT%H:%M:%SZ" means:
                #   %Y  = 4-digit year   (2024)
                #   %m  = 2-digit month  (01)
                #   %d  = 2-digit day    (15)
                #   T   = literal "T" separator (standard in timestamps)
                #   %H  = 2-digit hour   (14)
                #   %M  = 2-digit minute (37)
                #   %S  = 2-digit second (00)
                #   Z   = literal "Z" meaning UTC timezone
                # Result: "2024-01-15T14:37:00Z"
                # This is the international standard format for API timestamps.

                "netSales":             net_sales,
                # The order dollar value. Key name is camelCase "netSales"
                # (NOT snake_case "net_sales" like you'd expect from Python convention).

                "attributedCampaignId": attr_campaign,
                # Which campaign gets credit for this order.
                # Will be a campaign ID like "cmp_8821" or None (unattributed).

                "attributedChannel":    attr_channel,
                # Which channel (platform) the campaign runs on.
                # e.g. "Meta", "Google", or None if unattributed.

                "isSubscription":       is_sub,
                # True or False: is this a subscription order?

                "discountCode":         discount,
                # "SPRING20", "WELCOME10", or None.
            })

            order_counter += 1
            # Increment the counter so the NEXT order gets a different ID.
            # += 1 is shorthand for: order_counter = order_counter + 1
            # 40000, 40001, 40002, 40003... and so on.

        d += timedelta(days=1)
        # Move to the next day. Same as in _generate_spend.

    return rows
    # Return the complete list of all orders across the entire date range.


# =============================================================================
# SECTION 6: CURSOR (PAGINATION) HELPER FUNCTIONS
# =============================================================================
# WHAT IS PAGINATION?
# When an API has a LOT of data, it doesn't send it all at once.
# Imagine asking Google for every search result -- there could be millions.
# Instead, it sends 10 results at a time, and you can ask for "the next 10."
#
# This server works the same way. It sends up to 500 rows at a time.
# To get the NEXT batch, you send a "cursor" -- a bookmark.
# The cursor tells the server "I already have rows 0-499, give me 500-999."
#
# HOW THE CURSOR WORKS:
# Internally, the cursor is just an offset number (how many rows to skip).
# But we encode it as a base64 string so it looks like a proper API token.
#
# THE FULL FLOW:
#   Request 1: GET /api/orders?start_date=...&end_date=...
#   Response 1: { "results": [...500 rows...], "pagination": {"next": "eyJvZm...", "more": true} }
#
#   Request 2: GET /api/orders?start_date=...&end_date=...&cursor=eyJvZm...
#   Response 2: { "results": [...next 500 rows...], "pagination": {"next": "abc123", "more": true} }
#
#   ...keep going until "more" is false...
# =============================================================================


def _encode_cursor(offset):
    # -------------------------------------------------------------------------
    # PURPOSE: Turn a page position NUMBER into an encoded cursor STRING.
    # EXAMPLE: 500  -->  "eyJvZmZzZXQiOiA1MDB9"
    #
    # PARAMETER:
    #   offset -- an integer representing how many rows to skip.
    #             offset=0   means "start from the beginning"
    #             offset=500 means "skip the first 500 rows"
    #
    # RETURNS: A base64-encoded string.
    # -------------------------------------------------------------------------

    return base64.b64encode(json.dumps({"offset": offset}).encode()).decode()
    # -------------------------------------------------------------------------
    # THIS IS FOUR OPERATIONS CHAINED TOGETHER. Let's break it apart:
    #
    # STEP 1: json.dumps({"offset": offset})
    #   Converts the Python dictionary {"offset": 500}
    #   into a JSON string: '{"offset": 500}'
    #   (json.dumps = "dump to string")
    #
    # STEP 2: .encode()
    #   Converts the string '{"offset": 500}'
    #   into bytes: b'{"offset": 500}'
    #   (Computers need bytes for encoding operations, not text strings)
    #
    # STEP 3: base64.b64encode(...)
    #   Encodes the bytes using base64 algorithm.
    #   b'{"offset": 500}' --> b'eyJvZmZzZXQiOiA1MDB9'
    #   (Still bytes, but now base64-encoded bytes)
    #
    # STEP 4: .decode()
    #   Converts the base64 bytes back into a regular string.
    #   b'eyJvZmZzZXQiOiA1MDB9' --> 'eyJvZmZzZXQiOiA1MDB9'
    #   (Now it's a plain string we can include in a JSON response)
    # -------------------------------------------------------------------------


def _decode_cursor(cursor):
    # -------------------------------------------------------------------------
    # PURPOSE: Turn an encoded cursor STRING back into a page position NUMBER.
    # EXAMPLE: "eyJvZmZzZXQiOiA1MDB9"  -->  500
    #
    # This is the REVERSE of _encode_cursor.
    #
    # PARAMETER:
    #   cursor -- the cursor string from a request, or None if first page.
    #
    # RETURNS: An integer offset (number of rows to skip).
    # -------------------------------------------------------------------------

    if not cursor:
        return 0
    # -------------------------------------------------------------------------
    # HANDLE MISSING CURSOR (first page):
    # "if not cursor" is True when cursor is None, empty string, or not provided.
    # On the very first request, there's no cursor yet -- so we start at 0
    # (meaning: don't skip anything, start from the very beginning).
    # -------------------------------------------------------------------------

    try:
        return json.loads(base64.b64decode(cursor.encode()).decode())["offset"]
        # -----------------------------------------------------------------------
        # DECODE THE CURSOR -- exact reverse of _encode_cursor:
        #
        # STEP 1: cursor.encode()
        #   String --> bytes
        #   'eyJvZmZzZXQiOiA1MDB9' --> b'eyJvZmZzZXQiOiA1MDB9'
        #
        # STEP 2: base64.b64decode(...)
        #   Decode base64 bytes back to original bytes
        #   b'eyJvZmZzZXQiOiA1MDB9' --> b'{"offset": 500}'
        #
        # STEP 3: .decode()
        #   Bytes --> string
        #   b'{"offset": 500}' --> '{"offset": 500}'
        #
        # STEP 4: json.loads(...)
        #   JSON string --> Python dict
        #   '{"offset": 500}' --> {"offset": 500}
        #
        # STEP 5: ["offset"]
        #   Get the offset value from the dict
        #   {"offset": 500} --> 500
        # -----------------------------------------------------------------------

    except Exception:
        return 0
        # -----------------------------------------------------------------------
        # DEFENSIVE ERROR HANDLING:
        # If ANYTHING goes wrong while decoding the cursor (malformed string,
        # wrong format, unexpected input), we catch the error and return 0.
        # This means: "I couldn't understand this cursor, just start over."
        #
        # "except Exception" catches ALL types of errors at once.
        # Returning 0 instead of crashing is called "defensive programming" --
        # writing code that fails gracefully instead of blowing up.
        # -----------------------------------------------------------------------


# =============================================================================
# SECTION 7: FAILURE INJECTION
# =============================================================================
# This is the most important section for understanding why the assessment
# is challenging.
#
# REAL APIS FAIL SOMETIMES. A production-quality data pipeline must handle:
#   429 Too Many Requests -- "You're asking too fast, slow down"
#   500 Internal Server Error -- "Something broke on our end, try again"
#
# This function is called at the START of every endpoint request.
# It randomly decides whether to pretend something went wrong.
# =============================================================================


def _maybe_fail():
    # -------------------------------------------------------------------------
    # PURPOSE: Randomly return an error response to simulate real API failures.
    #
    # RETURNS:
    #   A Flask error response (429 or 500) if we decide to fail.
    #   None if everything is fine (the normal case).
    #
    # The calling code checks: if _maybe_fail() returns something, return it.
    # If it returns None, proceed normally.
    # -------------------------------------------------------------------------

    r = random.random()
    # -------------------------------------------------------------------------
    # Generate ONE random decimal between 0.0 and 1.0.
    # We use this single number to decide what (if anything) fails.
    # The entire 0.0-1.0 range is divided into zones:
    #
    #   0.00 to 0.10  (10% of the range) --> 429 rate limit error
    #   0.10 to 0.15  (5%  of the range) --> 500 server error
    #   0.15 to 1.00  (85% of the range) --> success (no error)
    #
    # IMPORTANT: This random() call is NOT affected by our random.seed(42).
    # By the time requests start coming in, the random number sequence has
    # moved far from the seeded state, so failures are genuinely unpredictable.
    # -------------------------------------------------------------------------

    if r < 0.10:
        # -----------------------------------------------------------------------
        # 10% CHANCE: Return a 429 "Too Many Requests" error.
        #
        # WHAT IS A 429?
        # HTTP status code 429 means "Rate Limited."
        # The server is saying: "You're sending too many requests too quickly.
        # I'm not going to answer this one. Wait a bit and try again."
        #
        # Rate limiting is very common in real APIs. Companies do it to:
        # - Prevent abuse (one client hogging all the server resources)
        # - Keep the API stable for all users
        # - Charge more for higher request volumes (business model)
        #
        # WHAT SHOULD YOUR PIPELINE DO?
        # Read the "Retry-After" header (set below) and wait that many seconds
        # before retrying the SAME request. Don't just keep hammering the API.
        # -----------------------------------------------------------------------
        resp = make_response(jsonify({"error": "rate_limited"}), 429)
        # make_response() creates a custom HTTP response.
        # First argument:  jsonify({"error": "rate_limited"}) = the response body
        # Second argument: 429 = the HTTP status code

        resp.headers["Retry-After"] = "2"
        # -----------------------------------------------------------------------
        # Set the "Retry-After" HTTP header.
        # This is a standard API convention that tells the caller:
        # "Wait 2 seconds, then try again."
        #
        # A well-written pipeline reads this header like this:
        #   retry_after = float(response.headers.get("Retry-After", 2))
        #   time.sleep(retry_after)
        #
        # Headers are extra metadata attached to an HTTP response,
        # separate from the response body. Think of them like sticky notes
        # on the outside of an envelope, before you even open it.
        # -----------------------------------------------------------------------

        return resp
        # Send this error response back to whoever called the API.

    if r < 0.15:
        # -----------------------------------------------------------------------
        # ANOTHER 5% CHANCE (when r is between 0.10 and 0.15): Return a 500 error.
        #
        # WHAT IS A 500?
        # HTTP status code 500 means "Internal Server Error."
        # The server is saying: "Something unexpected broke on my end.
        # It's not your fault. You can try again."
        #
        # This happens in real life when:
        # - The server ran out of memory
        # - The database connection dropped
        # - There's a bug that only shows up occasionally
        # - The server is overloaded
        #
        # WHAT SHOULD YOUR PIPELINE DO?
        # Wait a bit and retry (using "exponential backoff" -- wait 1 second,
        # then 2, then 4, then 8... so you don't overwhelm a struggling server).
        # -----------------------------------------------------------------------
        return make_response(jsonify({"error": "internal_server_error"}), 500)
        # Notice: no Retry-After header here. With 500 errors, it's up to
        # the caller to decide how long to wait before retrying.

    return None
    # -------------------------------------------------------------------------
    # 85% of the time: don't fail at all. Return None.
    # The calling endpoint function checks: if _maybe_fail() returns None,
    # that means "all clear -- proceed normally."
    # -------------------------------------------------------------------------


# =============================================================================
# SECTION 8: DATE PARSING HELPER
# =============================================================================


def _parse_dates():
    # -------------------------------------------------------------------------
    # PURPOSE: Read and validate the start_date and end_date URL parameters.
    #
    # When someone calls GET /api/orders?start_date=2024-01-01&end_date=2024-01-31
    # this function reads those two values and converts them into Python date objects.
    #
    # RETURNS (three values):
    #   On success: (start_date, end_date, None)
    #               (two real date objects, no error)
    #   On failure: (None, None, error_response)
    #               (two Nones, plus a Flask error response to send back)
    # -------------------------------------------------------------------------

    try:
        start = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d").date()
        # -----------------------------------------------------------------------
        # STEP BY STEP:
        #
        # 1. request.args.get("start_date")
        #    Reads the "start_date" value from the URL query parameters.
        #    URL: /api/orders?start_date=2024-01-01
        #    Result: the string "2024-01-01"
        #    If the parameter is missing, returns None.
        #
        # 2. datetime.strptime("2024-01-01", "%Y-%m-%d")
        #    "strptime" = "string parse time" -- convert a string into a datetime.
        #    "%Y-%m-%d" tells Python what format to expect.
        #    Result: datetime(2024, 1, 1, 0, 0) -- a full datetime object.
        #
        # 3. .date()
        #    Strips the time part and keeps only the date.
        #    datetime(2024, 1, 1, 0, 0) --> date(2024, 1, 1)
        #    We only need the date for our date-range logic.
        # -----------------------------------------------------------------------

        end = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d").date()
        # Same process for end_date.

        return start, end, None
        # Return both dates successfully, and None for the error (meaning no error).

    except (TypeError, ValueError):
        # -----------------------------------------------------------------------
        # TWO TYPES OF ERRORS WE CATCH:
        #
        # TypeError:
        #   Happens when request.args.get() returns None (parameter not in URL).
        #   strptime(None, "%Y-%m-%d") raises TypeError because it expected a string.
        #   This means the caller forgot to include start_date or end_date.
        #
        # ValueError:
        #   Happens when the date string is in the wrong format.
        #   strptime("01/15/2024", "%Y-%m-%d") raises ValueError because
        #   the format doesn't match. The API expects "2024-01-15", not "01/15/2024".
        # -----------------------------------------------------------------------
        return None, None, make_response(
            jsonify({"error": "invalid or missing start_date/end_date"}), 400
        )
        # 400 = "Bad Request" -- the caller sent something we can't use.
        # We return two Nones (for start and end) plus an error response.
        # The calling endpoint will check for this error and return it immediately.


# =============================================================================
# SECTION 9: ENDPOINT 1 — /api/marketing-spend
# =============================================================================
# This is where the magic happens. This function is the actual API endpoint.
# When someone sends a GET request to /api/marketing-spend, this function runs.
# =============================================================================


@app.route("/api/marketing-spend")
# -----------------------------------------------------------------------------
# THIS IS A "DECORATOR" -- a special Python syntax starting with @.
# It modifies the function below it.
#
# @app.route("/api/marketing-spend") tells Flask:
# "Register the function below as the handler for GET requests to /api/marketing-spend."
#
# After this line runs, whenever someone visits http://localhost:5000/api/marketing-spend
# Flask automatically calls the marketing_spend() function and sends back whatever it returns.
# -----------------------------------------------------------------------------

def marketing_spend():
    # -------------------------------------------------------------------------
    # This function handles a single request to /api/marketing-spend.
    # It's called automatically by Flask whenever a request comes in.
    # -------------------------------------------------------------------------

    failure = _maybe_fail()
    if failure:
        return failure
    # -------------------------------------------------------------------------
    # FIRST THING: Check if we should randomly fail this request.
    # _maybe_fail() returns either an error response OR None.
    # If it returned an error response (not None), return it immediately.
    # The rest of this function won't run -- the caller gets the error.
    #
    # WHY FIRST?
    # Real servers can fail before doing ANY work (during auth checks, etc.)
    # This simulates that behavior.
    # -------------------------------------------------------------------------

    start, end, err = _parse_dates()
    if err:
        return err
    # -------------------------------------------------------------------------
    # SECOND: Try to read and validate the date parameters from the URL.
    # _parse_dates() returns three values -- we unpack them into start, end, err.
    #
    # If err is not None, it means the dates were missing or malformed.
    # Return the error response immediately.
    # -------------------------------------------------------------------------

    limit = min(int(request.args.get("limit", 100)), 500)
    # -------------------------------------------------------------------------
    # READ THE "limit" PARAMETER (how many rows to return per page):
    #
    # request.args.get("limit", 100)
    #   Reads the "limit" URL parameter.
    #   The second argument (100) is the DEFAULT if the parameter isn't in the URL.
    #   So if caller doesn't send limit, we default to 100 rows per page.
    #
    # int(...)
    #   Convert the string "100" (URL parameters are always strings) to integer 100.
    #   Without this, Python would treat "100" as text, not a number.
    #
    # min(..., 500)
    #   Enforce a maximum of 500 rows per page.
    #   Even if the caller asks for limit=9999, they get 500 at most.
    #   This protects the server from being asked to return millions of rows at once.
    # -------------------------------------------------------------------------

    offset = _decode_cursor(request.args.get("cursor"))
    # -------------------------------------------------------------------------
    # READ THE "cursor" PARAMETER (the page bookmark):
    #
    # request.args.get("cursor")
    #   Reads the cursor from the URL. Returns None if not present (first page).
    #
    # _decode_cursor(...)
    #   Decodes the cursor string back into an integer offset.
    #   If cursor is None (first request), returns 0 (start from beginning).
    #   If cursor is "eyJvZmZzZXQiOiA1MDB9", returns 500 (skip first 500 rows).
    # -------------------------------------------------------------------------

    all_rows = _generate_spend(start, end)
    # -------------------------------------------------------------------------
    # GENERATE ALL THE DATA for the requested date range.
    # This creates ALL rows for ALL days -- potentially thousands of rows.
    # We'll slice out just the current page's worth below.
    #
    # NOTE: In a real server, this would be a database query with LIMIT and OFFSET.
    # Since we have no database, we generate everything and slice it.
    # -------------------------------------------------------------------------

    page = all_rows[offset:offset + limit]
    # -------------------------------------------------------------------------
    # SLICE OUT THIS PAGE'S ROWS:
    # Python list slicing: list[start:end] gives elements from start up to (not including) end.
    #
    # Example: offset=100, limit=100
    #   all_rows[100:200] = rows at index 100, 101, 102, ... 199  (100 rows)
    #
    # First page (offset=0, limit=100):
    #   all_rows[0:100] = first 100 rows
    #
    # Second page (offset=100, limit=100):
    #   all_rows[100:200] = next 100 rows
    # -------------------------------------------------------------------------

    has_more = offset + limit < len(all_rows)
    # -------------------------------------------------------------------------
    # CHECK IF THERE ARE MORE PAGES AFTER THIS ONE:
    # len(all_rows) = total number of rows.
    # offset + limit = the position AFTER the last row we just returned.
    #
    # If that position is less than the total, there's more data waiting.
    #
    # Example: 250 total rows, offset=100, limit=100
    #   offset + limit = 200
    #   200 < 250 = True --> more pages exist
    #   Next cursor will encode offset=200.
    #
    # Example: 250 total rows, offset=200, limit=100
    #   offset + limit = 300
    #   300 < 250 = False --> this is the last page (even if it has fewer than 100 rows)
    # -------------------------------------------------------------------------

    return jsonify({
        "data": page,
        # The actual rows of data for this page.
        # This is a list of dictionaries, each with: date, channel, campaign_id,
        # campaign_name, spend_usd, impressions, clicks.

        "next_cursor": _encode_cursor(offset + limit) if has_more else None,
        # -----------------------------------------------------------------------
        # THE CURSOR FOR THE NEXT PAGE:
        # If there are more pages (has_more = True):
        #   Encode the next starting position (offset + limit) as a cursor string.
        #   The caller sends this cursor in their NEXT request.
        # If this is the last page (has_more = False):
        #   Return None. The caller knows they have all the data.
        # -----------------------------------------------------------------------

        "has_more": has_more,
        # True if there are more pages, False if this is the last one.
        # The caller can check this to know when to stop paginating.
    })


# =============================================================================
# SECTION 10: ENDPOINT 2 — /api/orders
# =============================================================================
# Almost identical logic to /api/marketing-spend.
# The KEY DIFFERENCES are:
#   1. Uses _generate_orders() instead of _generate_spend()
#   2. Response envelope has DIFFERENT key names (see comments below)
# =============================================================================


@app.route("/api/orders")
# Same decorator pattern: register this function as the handler for /api/orders.

def orders():

    failure = _maybe_fail()
    if failure:
        return failure
    # Same random failure injection as in marketing_spend().

    start, end, err = _parse_dates()
    if err:
        return err
    # Same date validation.

    limit  = min(int(request.args.get("limit", 100)), 500)
    offset = _decode_cursor(request.args.get("cursor"))
    # Same pagination parameters.

    all_rows = _generate_orders(start, end)
    page     = all_rows[offset:offset + limit]
    has_more = offset + limit < len(all_rows)
    # Same pagination logic, but using order rows.

    return jsonify({
        "results": page,
        # -----------------------------------------------------------------------
        # DIFFERENCE #1: KEY NAME IS "results" NOT "data"
        # Spend endpoint uses "data" for the rows.
        # Orders endpoint uses "results" for the rows.
        # Same information, different key name.
        # Your pipeline must handle this difference explicitly --
        # you can't use the same code for both without checking which key to use.
        # -----------------------------------------------------------------------

        "pagination": {
            # -----------------------------------------------------------------------
            # DIFFERENCE #2: PAGINATION INFO IS NESTED INSIDE "pagination" OBJECT
            # In the spend endpoint, next_cursor and has_more are at the TOP LEVEL:
            #   { "data": [...], "next_cursor": "...", "has_more": true }
            #
            # In orders, they're NESTED inside a "pagination" object:
            #   { "results": [...], "pagination": { "next": "...", "more": true } }
            #
            # DIFFERENCE #3: KEY NAMES INSIDE PAGINATION ARE ALSO DIFFERENT
            # Spend:  "next_cursor" and "has_more"
            # Orders: "next"        and "more"  (both shorter names)
            #
            # To read the cursor from orders, your pipeline must do:
            #   response["pagination"]["next"]   (two levels deep)
            # Instead of:
            #   response["next_cursor"]           (one level deep, for spend)
            # -----------------------------------------------------------------------

            "next": _encode_cursor(offset + limit) if has_more else None,
            # The next page cursor (or None if last page). Same logic as spend.
            # Just stored at a different location in the response structure.

            "more": has_more,
            # True/False for whether more pages exist. Same as spend's "has_more".
        },
    })


# =============================================================================
# SECTION 11: ROOT ENDPOINT — / (the home page)
# =============================================================================


@app.route("/")
# Register this function as the handler for the root URL: http://localhost:5000/

def index():
    return jsonify({
        "service":   "Cymbiotika Mock API",
        # The name of this API service.

        "endpoints": ["/api/marketing-spend", "/api/orders"],
        # List of available endpoints. Useful as a quick reference.

        "note": "See assessment instructions for query params and pagination shapes.",
        # A hint message for anyone exploring the API.
    })
    # -------------------------------------------------------------------------
    # This is a simple "health check" endpoint.
    # If you visit http://localhost:5000 in your browser while the server is running,
    # you'll see this JSON message. It's a quick way to confirm the server is alive.
    # Many real APIs have a similar root endpoint or /health endpoint.
    # -------------------------------------------------------------------------


# =============================================================================
# SECTION 12: START THE SERVER
# =============================================================================


if __name__ == "__main__":
    # -------------------------------------------------------------------------
    # WHAT IS if __name__ == "__main__"?
    # Python files can be used in two ways:
    #   1. Run directly: python mock_server.py
    #   2. Imported by another file: import mock_server
    #
    # When run directly: __name__ equals "__main__"
    # When imported:     __name__ equals "mock_server" (the filename)
    #
    # So this if-block ONLY runs when you execute the file directly.
    # It does NOT run if another script imports this file.
    # This is a standard Python convention for "run this only as the main program."
    # -------------------------------------------------------------------------

    print("Mock API running on http://localhost:5000")
    print("Endpoints: /api/marketing-spend  |  /api/orders")
    # Simple status messages printed to the terminal so you know it started.

    app.run(host="0.0.0.0", port=5000, debug=False)
    # -------------------------------------------------------------------------
    # START THE FLASK WEB SERVER.
    # This line is blocking -- it runs forever (until you press Ctrl+C).
    # Flask starts listening for incoming requests.
    #
    # host="0.0.0.0"
    #   Accept connections from ANY network interface on this machine.
    #   "0.0.0.0" is a special address meaning "all available interfaces."
    #   If we used host="127.0.0.1" (localhost), only the same computer could reach it.
    #   With "0.0.0.0", other computers on the same network can also connect.
    #   For this assessment, it doesn't matter much -- we're running locally anyway.
    #
    # port=5000
    #   The "door number" the server listens on.
    #   When you visit http://localhost:5000, your browser sends traffic to port 5000.
    #   Port 5000 is a common choice for development servers (not a special number,
    #   just a convention). Port 80 is the default for websites, port 443 for HTTPS.
    #
    # debug=False
    #   Production-like mode: no detailed error pages shown to callers.
    #   If debug=True, Flask would show stack traces in the browser when errors occur,
    #   which is helpful for development but dangerous in production (leaks internal info).
    #   We use False here to simulate a real production API.
    # -------------------------------------------------------------------------
