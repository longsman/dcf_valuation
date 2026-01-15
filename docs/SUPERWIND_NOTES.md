# Superwind Polygon Pipeline — Investigation Notes

Date: 2025-11-11
Workspace paths:
- Repo: /Users/datsando@outlook.com/superwind
- Notebooks: /Users/datsando@outlook.com/superwind/notebooks/exec-superwind
- YAML (polygon): /Users/datsando@outlook.com/superwind/pipelines/polygon

## Summary
- Root cause of job failures: The target table `bronze.polygon.snapshot_all_tickers` did not contain the key column `ticker` (and related payload columns) expected by the pipeline’s MERGE logic. The MERGE match condition uses `[ticker, snapshot_date]`, so Spark/Delta failed to resolve `tab.ticker`.
- A second blocker: the job’s run-as principal lacks `MODIFY` on the original table, causing write failures even after schema was corrected.

## Evidence
- Failing job: `superwind` (job_id: 413747026668475).
  - Latest failing run previously observed: run_id 1108041584533723.
  - Failing task: `bronze-polygon-snapshot_all_tickers` (e.g., task run_id 260683236539825).
  - Error excerpt: `[DELTA_MERGE_UNRESOLVED_EXPRESSION] Cannot resolve tab.ticker ...`
  - Run URL example: https://dbc-51f1a5f2-687a.cloud.databricks.com/?o=683875129393773#job/413747026668475/run/1108041584533723

- Original table schema prior to fix (DESCRIBE TABLE):
  - Columns: `_id, snapshot_date, access_ts, headers, content, _footprint` (no `ticker`).
  - Row count at time of check: 0 rows (so safe to recreate if permissions allow).

- Pipeline definitions:
  - `bronze.polygon.snapshot_all_tickers.yaml` defines REST producer with fields: `ticker, todaysChangePerc, todaysChange, updated, day, lastQuote, lastTrade, min, prevDay`, adds `snapshot_date`, and merges to `bronze.polygon.snapshot_all_tickers` with keys `[ticker, snapshot_date]`.
  - `silver.polygon.snapshot_all_tickers.yaml` reads bronze via CDF, casts/parses JSON-string columns, and merges into silver.

## Temp-table validation (to prove pipeline correctness)
- Created temp YAML targeting `bronze.polygon.snapshot_all_tickers_tmp` and executed bronze-only run.
- Run succeeded: run_id 391901395893851
  - URL: https://dbc-51f1a5f2-687a.cloud.databricks.com/?o=683875129393773#job/755337860017627/run/391901395893851
- Temp table results:
  - Schema includes expected columns: `ticker, todayschangeperc, todayschange, updated, day, lastquote, lasttrade, min, prevday, snapshot_date`, plus `_id` and `_footprint`.
  - Row count example: 11,945 rows for snapshot_date=2025-11-11.

Note on dependencies: the superwind Python package imports `finance.py` (which imports `feedparser`) at package import time, so even polygon-only runs need `feedparser` (and friends) available. I included: `feedparser, pydantic, ratelimit, pyyaml, keyring` in the run libraries.

## Attempted remediation on the original table
- ALTER TABLE to add missing columns to `bronze.polygon.snapshot_all_tickers` succeeded, and DESCRIBE now shows:
  - Added: `ticker, todayschangeperc, todayschange, updated, day, lastquote, lasttrade, min, prevday`.
- Re-ran the full `superwind` job via Run Now.
  - Bronze polygon task failed with permissions at write time:
    - Error: `PERMISSION_DENIED: User does not have MODIFY on Table 'bronze.polygon.snapshot_all_tickers'`.
  - Silver polygon task was skipped (upstream failed).

## Permissions findings
- Table-level privileges observed:
  - `la.long.n@outlook.com`: SELECT, MODIFY, APPLY_TAG on `bronze.polygon.snapshot_all_tickers`.
  - `datsando@outlook.com` (job run-as): no explicit table-level privileges found; the error stack confirms lack of `MODIFY` at write-time.
- Conclusion: The job’s run-as principal needs `MODIFY` (and required USAGE on catalog/schema) to write to the bronze table.

## Conclusions
1) Primary failure cause: target table schema mismatch (missing `ticker`, etc.) with the Merge keys; fixed by adding columns (or dropping/recreating table via pipeline).
2) Secondary blocker: insufficient privileges for the job’s run-as principal to perform writes to the bronze table.

## Recommended next actions
- Choose one of:
  - Grant privileges to the job’s run-as user `datsando@outlook.com`:
    - `GRANT USAGE ON CATALOG bronze TO `datsando@outlook.com``
    - `GRANT USAGE ON SCHEMA bronze.polygon TO `datsando@outlook.com``
    - `GRANT MODIFY ON TABLE bronze.polygon.snapshot_all_tickers TO `datsando@outlook.com``
  - Or, change the job’s Run as user to `la.long.n@outlook.com` (who already has `MODIFY`).
- Optional clean-up: if permitted, DROP and let the bronze pipeline recreate the table to avoid lingering legacy columns or properties.
- Minor check (optional): Verify unit for `updated` in the silver YAML (`cast(updated/1000000000 as timestamp)`). If Polygon `updated` is in milliseconds, use `/1000` instead of `/1e9`.

## Useful links
- Latest failing run (example): https://dbc-51f1a5f2-687a.cloud.databricks.com/?o=683875129393773#job/413747026668475/run/1108041584533723
- Recent job re-run (failed at bronze polygon): https://dbc-51f1a5f2-687a.cloud.databricks.com/?o=683875129393773#job/413747026668475/run/104646920611635
- Temp bronze run (success): https://dbc-51f1a5f2-687a.cloud.databricks.com/?o=683875129393773#job/755337860017627/run/391901395893851
 
## EDGAR Filings (silver) — schema and sample

Table: `silver.edgar.filings_rss`

Columns (SHOW COLUMNS):
- `_id` (string) — superwind meta id (uuid)
- `filing_id` (string) — derived from `id` in bronze (the SEC Atom ID urn)
- `accession_number` (string) — extracted via regex from `id` (e.g., `0001104659-25-109315`)
- `cik` (string) — CIK left‑padded to 10 digits
- `link` (string) — index URL to the filing on SEC EDGAR
- `filed_date` (date) — extracted from summary, cast to date
- `form_type` (string) — extracted from title (e.g., `10-Q`, `10-K`, `10-K/A`, ...)
- `title` (string) — SEC feed title for the item
- `updated` (timestamp) — feed timestamp
- `_footprint` (struct<upstream_id:string, create_ts:timestamp, modify_ts:timestamp>) — superwind meta

Row stats:
- count: 40,160
- filed_date min/max: 2024‑07‑11 → 2025‑11‑10
- top form types (counts): `10‑Q` (18,540), `10‑D` (13,499), `10‑K` (6,349), `10‑K/A` (825), `10‑Q/A` (458), `10‑12G/A` (161), `10‑D/A` (149), `10‑12G` (105), `10‑12B/A` (35), `10‑KT` (16)

Recent sample (10 rows, ordered by filed_date desc, updated desc):
- Columns order: `_id | filing_id | accession_number | cik | link | filed_date | form_type | title | updated | _footprint`
- Example:
  - `... | 0001104659-25-109315 | 0002073653 | https://www.sec.gov/Archives/.../0001104659-25-109315-index.htm | 2025-11-10 | 10-Q | 10-Q - FBRED-C Feeder REIT Trust (0002073653) (Filer) | 2025-11-10T22:30:05Z | {...}`

Silver YAML notes (workspace path `/Users/datsando@outlook.com/superwind/pipelines/edgar/silver.edgar.filings_rss.yaml`):
- Producer: `ReadTable` from `bronze.edgar.filings_rss` with CDF (streaming, `available_now`).
- Operators: `Filter _change_type='insert'`, `RegexpExtract` to derive `accession_number`, `cik`, `filed_date`, `form_type`; `Select` to build the output; `updated` cast to timestamp.
- Consumer: `MergeTable` keyed on `[filing_id, title]` → `silver.edgar.filings_rss`.
- The `_id` from bronze is intentionally kept so `_footprint.upstream_id` references the source record after meta augmentation in the consumer.

Ideas for next transformations/calculations
- Normalize identifiers and linkages
  - Ensure `cik` is numeric (10‑digit string) and joinable to company reference tables (e.g., `bronze.edgar.company_tickers` or a curated dimension).
  - Consider adding a canonical key `(cik, accession_number)` in addition to the merge key used today.
- Form type taxonomy
  - Standardize `form_type` (strip `/A`, split base vs amendment, add boolean `is_amendment`).
  - Derive higher‑level categories (10‑K/10‑Q/10‑D/10‑12*).
- Time aspects
  - Derive `filed_year`, `filed_quarter`, `filed_week` for aggregations.
  - Track `ingested_ts = _footprint.create_ts` and compare to `filed_date` for latency metrics.
- Quality checks
  - Not‑null checks for `filing_id`, `accession_number`, `cik`, `filed_date`, `form_type`.
  - Regex validation of `accession_number` pattern `^\d{10}-\d{2}-\d{6}$`.
  - URL validity check for `link`.
- Derived metrics and aggregations
  - Rolling counts per `form_type` by day/week.
  - Per‑CIK filing cadence; unusual spikes.
  - “Latest filing per CIK and form_type” view.
- Storage/layout considerations
  - Consider Z‑ordering or clustering by `filed_date` (and/or `form_type`) if query patterns are time‑based.
  - Maintain CDF on silver if downstream consumers need change‑aware processing.

## Databricks REST API — field guide (used in this investigation)

Setup (once per shell):
- Export env vars (avoid echoing secrets):
  - `export DATABRICKS_HOST="https://<your-workspace>"`
  - `export DATABRICKS_TOKEN="<personal-access-token>"`
- Use Authorization header on every call: `-H "Authorization: Bearer $DATABRICKS_TOKEN"`

Identity (verify access):
- Me (SCIM):
  - `GET $DATABRICKS_HOST/api/2.0/preview/scim/v2/Me`
  - Expect JSON with `userName`, groups, id.

Jobs and runs (inventory):
- List jobs (with tasks):
  - `GET $DATABRICKS_HOST/api/2.1/jobs/list?expand_tasks=true`
  - Returns `jobs[]` with `settings.tasks`, names, schedules, environments.
- List runs (active only):
  - `GET $DATABRICKS_HOST/api/2.1/jobs/runs/list?active_only=true&limit=26`
  - Note: limit cannot exceed 26 (gotcha).
- List runs for a specific job:
  - `GET $DATABRICKS_HOST/api/2.1/jobs/runs/list?job_id=<JOB_ID>&limit=1`

Run detail, output, and code export:
- Run details:
  - `GET $DATABRICKS_HOST/api/2.1/jobs/runs/get?run_id=<RUN_ID>`
  - Use this to discover per-task `tasks[].run_id`.
- Task output / error:
  - `GET $DATABRICKS_HOST/api/2.0/jobs/runs/get-output?run_id=<TASK_RUN_ID>`
  - Returns `error` string and `metadata` with task info.
- Export run code (HTML):
  - `GET $DATABRICKS_HOST/api/2.0/jobs/runs/export?run_id=<TASK_RUN_ID>&views_to_export=CODE`
  - Returns an HTML document (base64 content if not direct); good for auditing the executed notebook.

Triggering jobs:
- Run an existing job now:
  - `POST $DATABRICKS_HOST/api/2.1/jobs/run-now` with body `{ "job_id": <JOB_ID> }`
  - Poll with `GET /api/2.1/jobs/runs/get?run_id=<RUN_ID>` until `state.life_cycle_state` is terminal.
- Ad-hoc submit run (workspace notebook):
  - Endpoint: `POST /api/2.1/jobs/runs/submit`
  - Important:
    - Do NOT use `job_clusters` here (the API disallows shared job clusters for submit). Instead, define `new_cluster` under each `tasks[]` item.
    - Include Pypi libs as needed:
      - `"libraries": [{"pypi":{"package":"feedparser==6.0.11"}}, ...]`
    - Minimal body (single task):
      - `{"run_name":"...","tasks":[{"task_key":"t1","new_cluster":{...},"notebook_task":{"notebook_path":"/Users/.../exec-superwind","source":"WORKSPACE","base_parameters":{"yaml_file":"../pipelines/...yaml"}}}]}`

Workspace navigation and content:
- List directories/files:
  - `GET $DATABRICKS_HOST/api/2.0/workspace/list?path=/Users`
  - Drill into nested paths by changing the `path` parameter.
- Export a file/notebook:
  - `GET $DATABRICKS_HOST/api/2.0/workspace/export?path=/Users/...&format=AUTO`
  - Response contains `{ content: <base64> }`; decode to file.
  - For direct bytes (where supported): `&direct_download=true`.
- Import (create/overwrite) a file:
  - `POST $DATABRICKS_HOST/api/2.0/workspace/import` with JSON body:
    - `{ "path":"/Users/.../file.yaml", "overwrite":true, "format":"AUTO", "language":"AUTO", "content":"<base64>" }`

Repos (to find your code):
- List repos under a prefix:
  - `GET $DATABRICKS_HOST/api/2.0/repos?path_prefix=/Users`
  - Fields include `id`, `path`, `url`.

Compute inventory:
- Clusters:
  - `GET $DATABRICKS_HOST/api/2.0/clusters/list`
  - Includes job clusters (TERMINATED) with details (node_type, spark_version).
- SQL Warehouses:
  - `GET $DATABRICKS_HOST/api/2.0/sql/warehouses`
  - Use `id` for SQL Statements API queries.

SQL Statements API (ad‑hoc SQL on a warehouse):
- Submit:
  - `POST $DATABRICKS_HOST/api/2.0/sql/statements` with body `{ "statement": "<SQL>", "warehouse_id": "<WH_ID>" }`
- Poll:
  - `GET $DATABRICKS_HOST/api/2.0/sql/statements/<statement_id>` until `status.state` is `SUCCEEDED` or `FAILED`.
- Read results:
  - In the poll response, read `result.data_array` for rows.
- Examples we used:
  - DESCRIBE TABLE / DETAIL / SHOW COLUMNS / SELECT sample: inspect schemas and data.
  - CREATE/DROP/ALTER TABLE: DDL operations (ensure JSON body is valid; prefer single‑line SQL or properly escaped newlines).
  - Permissions info:
    - `SHOW GRANTS ON TABLE <cat>.<schema>.<table>`
    - `SELECT grantee, privilege_type FROM system.information_schema.table_privileges WHERE table_catalog='...' AND table_schema='...' AND table_name='...'`

Unity Catalog catalogs (for context):
- `GET $DATABRICKS_HOST/api/2.1/unity-catalog/catalogs`
- Helpful to confirm catalog names and browse settings.

Gotchas and tips:
- Active runs limit: `/jobs/runs/list` enforces `limit <= 26`.
- runs/submit vs job clusters: submit runs do not support shared `job_clusters`. Use `new_cluster` per task instead.
- SQL statements body must be valid JSON: either single‑line SQL for `statement` or escape newlines. Malformed JSON returns `MALFORMED_REQUEST`.
- Workspace paths are case‑sensitive and must exist; always `workspace/list` first to confirm.
- Task output vs run output: to fetch errors, use `jobs/runs/get-output` with the task’s `run_id` (not the parent job run id).
- Permissions: run‑as user in a job may differ from your user; grant privileges accordingly or change Run‑As.

Example sequences

1) Inspect a failing job run and fetch the failing task error:
- List jobs; identify job_id
- `GET /api/2.1/jobs/runs/list?job_id=<ID>&limit=1`
- `GET /api/2.1/jobs/runs/get?run_id=<RUN_ID>` → pick the failing task’s `run_id`
- `GET /api/2.0/jobs/runs/get-output?run_id=<TASK_RUN_ID>` → `error`

2) Export a notebook and YAML from the repo workspace:
- `GET /api/2.0/workspace/list?path=/Users/<user>/superwind/notebooks`
- `GET /api/2.0/workspace/export?path=/Users/.../exec-superwind&format=SOURCE` (decode base64)
- `GET /api/2.0/workspace/export?path=/Users/.../pipelines/polygon/bronze....yaml&format=AUTO` (decode base64)

3) Run SQL to check a table:
- `POST /api/2.0/sql/statements` with `{ "statement": "DESCRIBE TABLE bronze.polygon.snapshot_all_tickers", "warehouse_id":"<WH>" }`
- Poll `/api/2.0/sql/statements/<id>` until `SUCCEEDED`; read `result.data_array`

4) Fix schema mismatch (if permitted):
- `POST /api/2.0/sql/statements` with `{ "statement": "ALTER TABLE bronze.polygon.snapshot_all_tickers ADD COLUMNS (ticker string, ...)" }`
- Re-run the job with `POST /api/2.1/jobs/run-now` and monitor with `GET /api/2.1/jobs/runs/get`

5) Submit an ad-hoc bronze polygon run to a temp table:
- `POST /api/2.0/workspace/import` with base64 of a modified YAML writing to `<cat>.<schema>.snapshot_all_tickers_tmp`
- `POST /api/2.1/jobs/runs/submit` with a single task using `new_cluster` and `notebook_task` pointing at the runner; include required Pypi libs
- Poll `GET /api/2.1/jobs/runs/get?run_id=<RUN_ID>` until terminal; verify with SQL (`SELECT count(*) FROM <tmp_table>`)