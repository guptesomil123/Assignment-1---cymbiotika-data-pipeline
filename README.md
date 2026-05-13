# Cymbiotika — API Pipeline

## How to run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the mock server (leave this running)
python mock_server.py

# 3. Run the pipeline (separate terminal)
python pipeline.py
```

Output lands in `output/campaign_weekly_performance.csv`.

Optional flags:

```bash
python pipeline.py --start 2025-03-01 --end 2025-03-31
python pipeline.py --base-url http://localhost:5000
```

---

## Architecture choices

**One paginator per endpoint, not a generic one.**
Both endpoints use cursor-based pagination but with different envelope shapes (`next_cursor` / `has_more` vs `pagination.next` / `pagination.more`). A generic paginator would need to guess which key to read — instead each endpoint gets its own explicit function. More code, far easier to audit when the API changes.

**Retry logic separated from pagination logic.**
`_get_with_retry()` handles all HTTP concerns (429 back-off, 500 exponential back-off, network errors). The paginators call it as a black box and never see status codes. This keeps failure handling in one place and keeps the paginators readable.

**429 and 500 have different retry strategies.**
429 means "wait exactly as long as the server asks" — we read `Retry-After` and sleep that many seconds without advancing our own back-off counter. 500 means "server had a bad moment" — we use exponential back-off (1 s, 2 s, 4 s… capped at 30 s) since we don't know how long the server needs.

**Normalisation at ingestion, not at join time.**
Both endpoints are normalised to snake_case and typed immediately after fetching. Downstream code (aggregation, join, output) only ever sees one schema. This also gives us clean raw CSVs for debugging if the join looks wrong.

**Unattributed orders are flagged, not dropped.**
About 2% of orders have no `attributedCampaignId`. Dropping them silently would understate total order volume. Instead they get an `is_unattributed` flag and are excluded only from the campaign join — the count is logged so the discrepancy is visible.

**Week grain computed from the date, not assumed.**
`week_start = date - timedelta(days=date.weekday())` gives the ISO Monday for any date. This handles months that start mid-week correctly (April 1 2025 is a Tuesday → week_start = March 31).

**Left join, not inner join.**
We join spend onto orders. Campaigns with zero attributed orders in a week still appear in the output (spend happened, we just have no revenue to show for it). An inner join would silently hide that spend.

**ROAS is None when spend is zero, not 0 or inf.**
A row with `spend = 0` and `revenue = 0` is not a 0× ROAS situation — it's a data absence. `None` (blank in CSV) is the honest representation. `inf` would break any downstream chart; `0` would make a good campaign look terrible.

---

## How I'd productionise this

**Scheduling:** Airflow or Prefect DAG running nightly. Each run covers the previous full day (`start_date = yesterday`, `end_date = yesterday`) — incremental, not full-reload.

**Idempotency:** Each run writes to a date-partitioned table (`partition_date = run_date`). Re-running the same date overwrites the partition cleanly (Snowflake `MERGE` or BigQuery `WRITE_TRUNCATE`). Never appends blindly.

**Landing zone:** Raw JSON pages written to S3/GCS before transformation. If the pipeline crashes mid-run, we can replay from the raw files without re-hitting the API.

**Target storage:** Snowflake or BigQuery fact table. `campaign_weekly_performance` becomes a view on top of a daily grain table — weekly rollup is a query, not a baked output. Easier to change the grain later.

**Monitoring and alerting:**
- Row count check: if `len(weekly) < expected_min`, fire a PagerDuty alert.
- Spend delta check: if total spend deviates > 20% from the 7-day average, Slack alert for human review.
- Retry exhaustion: if `_get_with_retry` raises after MAX_RETRIES, the DAG task fails visibly rather than swallowing the error.

**Schema change detection:** On every run, compare the incoming field list against a stored schema manifest. If a new field appears or an existing one disappears, log a warning and route the raw payload to a quarantine table instead of the main one.

**Secrets:** API keys in AWS Secrets Manager / GCP Secret Manager, not in environment files.

---

## What breaks at 100× volume

| Problem | What changes |
|---|---|
| `_generate_spend` / `_generate_orders` load ALL rows into memory, then slice | At 100× (30M+ rows per run), this OOMs. Fix: database-side pagination with `LIMIT`/`OFFSET` pushed into the query, or server-side streaming. |
| Single-threaded page fetching | At 100× the sequential loop takes hours. Fix: `asyncio` + `httpx.AsyncClient` to fetch pages concurrently, with a semaphore to respect rate limits. |
| Pandas in-memory join | Fine for <10M rows; brittle above that. Fix: load raw CSVs into Snowflake staging tables and do the join in SQL, or use DuckDB for local processing. |
| One retry budget for all pages | A transient outage during page 4,000 of 40,000 shouldn't start over. Fix: checkpoint the cursor to a state store (Redis or a file) so a restart resumes from the last successful page. |
| CSV output | CSV doesn't support schema enforcement, partitioning, or efficient filtering. Fix: Parquet on object storage, then COPY INTO the warehouse. |
