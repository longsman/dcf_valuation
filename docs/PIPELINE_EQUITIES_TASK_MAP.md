# `pipeline_equities` Task → YAML → Delta Table Map

Date: 2026-01-13

This is a **companion note** to `docs/PROJECT_STATE.md`.

Goal: map each `pipeline_equities` job task to:
- the **YAML asset file** it runs,
- the **inputs** it reads (external APIs and/or UC tables),
- the **UC Delta tables** it produces (and the key columns / schema shape).

## How `pipeline_equities` runs pipelines

The deployed scheduled job is `pipeline_equities` (job_id `542379385267532`). It runs pipelines as **Python wheel tasks**:
- `package_name: superwind`
- `entry_point: exec_superwind`
- `named_parameters` include:
  - `from_package: pipeline_equities.assets`
  - `yaml_file: <relative path inside package assets>`

So the YAML that each task runs lives inside the `pipeline_equities` wheel as package data (`assets/**/*`).

Where to inspect deployed assets in the workspace:
- Bundle deployment root: `/Workspace/Deployments/pipeline_equities/prd`
- YAML asset root (deployed files view): `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets`
- Job resource YAML: `/Workspace/Deployments/pipeline_equities/prd/files/resources/pipeline_equities.job.yaml`

---

## Task Summary

| Task Key | Mode | YAML (`yaml_file`) | Primary Output Table | Key Columns |
|---|---|---|---|---|
| `bronze-edgar-form10_filings_rss` | batch | `bronze/edgar.form10_filings_rss/pipeline.yaml` | `bronze.edgar.form10_filings_rss` | `[id, title]` |
| `silver-edgar-form10_filings_rss` | streaming (`available_now`) | `silver/edgar.form10_filings_rss/pipeline.yaml` | `silver.edgar.form10_filings_rss` | `[filing_id, title]` |
| `bronze-edgar-company_facts` | streaming (`available_now`) | `bronze/edgar.company_facts/pipeline.yaml` | `bronze.edgar.company_facts` | `[cik, accession_number]` |
| `silver-edgar-company_facts` | streaming (`available_now`) | `silver/edgar.company_facts/pipeline.yaml` | `silver.edgar.company_facts` | `[cik, taxonomy, tag, unit_of_measure, accn, start, end, fy, fp]` |
| `bronze-fred-series_observations` | streaming (`available_now`) | `bronze/fred.series_observations/pipeline.yaml` | `bronze.fred.series_observations` | append |
| `silver-fred-market_yield_10yr` | streaming (`available_now`) | `silver/fred.market_yield_10yr/pipeline.yaml` | `silver.fred.market_yield_10yr` | `[observation_date]` |
| `bronze-massive-snapshot_all_tickers` | batch | `bronze/massive.snapshot_all_tickers/pipeline.yaml` | `bronze.massive.snapshot_all_tickers` | `[snapshot_date]` |
| `silver-massive-snapshot_all_tickers` | streaming (`available_now`) | `silver/massive.snapshot_all_tickers/pipeline.yaml` | `silver.massive.snapshot_all_tickers` | `[ticker, snapshot_date]` |

Notes:
- Every pipeline uses Delta tables with `delta.enableChangeDataFeed=true` in its DDL.
- The silver pipelines generally read bronze via **Change Data Feed** (`readChangeFeed: True`).

---

## Task Details

### 1) `bronze-edgar-form10_filings_rss`

YAML asset:
- `yaml_file`: `bronze/edgar.form10_filings_rss/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/edgar.form10_filings_rss/pipeline.yaml`

Execution:
- `config.mode: batch`

Inputs:
- SEC “current filings” Atom feed via `https://www.sec.gov/cgi-bin/browse-edgar` with params:
  - `type: 10-`, `count: 500`, `output: atom`
- Uses `User-Agent: 'Datsando datsando@outlook.com'`

Pipeline components:
- Producer: `RESTProducer` (GET)
- Operators:
  - `ParseRSSFeed` (parses Atom into JSON strings)
  - `CastJSONString` (casts each entry into a typed struct)
  - `Select` (projects `content.*`)
- Consumer: `MergeTable`
  - `table: bronze.edgar.form10_filings_rss`
  - `key_columns: [id, title]`

Output table schema (from DDL and UC):
- `_id`, `_footprint`, plus Atom fields like `id`, `link`, `summary`, `title`, `updated`, `updated_parsed`, etc.
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/edgar.form10_filings_rss/ddl.sql`

---

### 2) `silver-edgar-form10_filings_rss`

YAML asset:
- `yaml_file`: `silver/edgar.form10_filings_rss/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/edgar.form10_filings_rss/pipeline.yaml`

Execution:
- `config.mode: streaming`
- Trigger: `available_now`
- Checkpoint: `s3://datsando-prod/pipeline_equities/checkpoints/silver/edgar/filings_rss`

Inputs:
- `bronze.edgar.form10_filings_rss` via `ReadTable` with:
  - `readChangeFeed: True`
  - `startingVersion: 34` (hard-coded)

Pipeline components:
- Producer: `ReadTable`
- Operators:
  - Filter inserts from CDF (`_change_type = 'insert'`)
  - `RegexpExtract` to derive:
    - `accession_number` from `id`
    - `cik` from `title`
    - `filed_date` from HTML in `summary`
    - `form_type` from `title`
  - `Select` output columns (casts `filed_date` and `updated`)
  - `StripStrings`, `ConvertStringToNull`
- Consumer: `MergeTable`
  - `table: silver.edgar.form10_filings_rss`
  - `key_columns: [filing_id, title]`

Output table schema (from UC):
- `_id`, `_footprint`
- `filing_id`, `accession_number`, `cik`, `link`, `filed_date`, `form_type`, `title`, `updated`
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/edgar.form10_filings_rss/ddl.sql`

---

### 3) `bronze-edgar-company_facts`

YAML asset:
- `yaml_file`: `bronze/edgar.company_facts/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/edgar.company_facts/pipeline.yaml`

Execution:
- `config.mode: streaming`
- Trigger: `available_now`
- Checkpoint: `s3://datsando-prod/pipeline_equities/checkpoints/bronze/edgar/company_facts`
- `streaming_defer_operators: True`

Inputs:
- `silver.edgar.form10_filings_rss` via `ReadTable` with CDF:
  - `readChangeFeed: True`
  - `startingVersion: 6` (hard-coded)

Pipeline components:
- Producer: `ReadTable`
- Operators:
  - Filter: `_change_type = 'insert' and form_type in ('10-K', '10-Q', '10-QT')`
  - `RESTOperator`:
    - URL: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`
    - `param_location: path` and uses `cik` column to fill `{cik}`
    - `ignore_error_codes: [404]`
    - `User-Agent: "Datsando datsando@outlook.com"`
  - `Select`: `_id, cik, accession_number, content`
  - Filter: `content is not null`
- Consumer: `MergeTable`
  - `table: bronze.edgar.company_facts`
  - `key_columns: [cik, accession_number]`

Output table schema (from UC):
- `_id`, `_footprint`, `cik`, `accession_number`, `content` (raw JSON string)
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/edgar.company_facts/ddl.sql`

---

### 4) `silver-edgar-company_facts`

YAML asset:
- `yaml_file`: `silver/edgar.company_facts/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/edgar.company_facts/pipeline.yaml`

Execution:
- `config.mode: streaming`
- Trigger: `available_now`
- Checkpoint: `s3://datsando-prod/pipeline_equities/checkpoints/silver/edgar/company_facts`
- `streaming_defer_operators: True` (important for schema loading and perf)

Inputs:
- `bronze.edgar.company_facts` via `ReadTable` with CDF:
  - `readChangeFeed: True`
  - `startingVersion: 2` (hard-coded)

Pipeline components (high level):
- Producer: `ReadTable`
- Operators (high level flow):
  - Keep inserts + postimage updates
  - Remove meta columns except `_id`
  - Explode JSON to a normalized “facts” table:
    - `taxonomy` → `tag` → `unit_of_measure` → explode facts array
  - `CastJSONString` parses the SEC “units” array into typed structs
  - `KeepLatestRecord` de-dupes older versions using an ordering rule
  - `StripStrings`, `ConvertStringToNull`
- Consumer: `MergeTable`
  - `table: silver.edgar.company_facts`
  - `key_columns`:
    - `cik, taxonomy, tag, unit_of_measure, accn, start, end, fy, fp`

Output table schema (from UC):
- `_id`, `_footprint`
- Dimensions: `cik`, `taxonomy`, `tag`, `unit_of_measure`
- Fact grain fields: `val`, `accn`, `start`, `end`, `fy`, `fp`, `filed`, `form`, `frame`
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/edgar.company_facts/ddl.sql`

This table is the key “primitive” for downstream DCF work.

---

### 5) `bronze-fred-series_observations`

YAML asset:
- `yaml_file`: `bronze/fred.series_observations/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/fred.series_observations/pipeline.yaml`

Execution:
- `config.mode: streaming`
- Trigger: `available_now`
- Checkpoint: `s3://datsando-prod/pipeline_equities/checkpoints/bronze/fred/series_observations`

Inputs:
- External FRED API via the `FREDSeriesObservations` producer.
  - `series_id: DGS10` (10-year treasury constant maturity)
  - API key from Databricks secrets: scope `pipeline_equities`, key `fred.api_key`

Pipeline components:
- Producer: `FREDSeriesObservations`
- Consumer: `SaveAsTable`
  - `mode: append`
  - `table: bronze.fred.series_observations`

Output table schema (from DDL):
- `_id`, `_footprint`
- `series_id`, `realtime_start`, `realtime_end`, `observation_date`, `value`
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/fred.series_observations/ddl.sql`

---

### 6) `silver-fred-market_yield_10yr`

YAML asset:
- `yaml_file`: `silver/fred.market_yield_10yr/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/fred.market_yield_10yr/pipeline.yaml`

Execution:
- `config.mode: streaming`
- Trigger: `available_now`
- Checkpoint: `s3://datsando-prod/pipeline_equities/checkpoints/silver/fred/market_yield_10yr`

Inputs:
- `bronze.fred.series_observations` (no explicit CDF options in YAML)

Pipeline components:
- Producer: `ReadTable`
- Operators:
  - Filter `value is not null`
  - Select `observation_date`, `value as percent`
- Consumer: `MergeTable`
  - `table: silver.fred.market_yield_10yr`
  - `key_columns: [observation_date]`

Output table schema (from UC):
- `_id`, `_footprint`, `observation_date`, `percent`
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/fred.market_yield_10yr/ddl.sql`

---

### 7) `bronze-massive-snapshot_all_tickers`

YAML asset:
- `yaml_file`: `bronze/massive.snapshot_all_tickers/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/massive.snapshot_all_tickers/pipeline.yaml`

Execution:
- `config.mode: batch`

Inputs:
- Massive API (Polygon-like snapshot endpoint):
  - `https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers`
  - Uses `api_key_secret: scope pipeline_equities, key massive.api_key`
  - Uses `next_page_key: next_url` for pagination

Pipeline components:
- Producer: `RESTProducer` (GET, includes headers + content bytes)
- Operators:
  - Extract and parse response header `Date` into `access_ts`
  - Assign `snapshot_date` (NY time)
  - Select output columns: `snapshot_date`, `access_ts`, `headers`, `content`
- Consumer: `MergeTable`
  - `table: bronze.massive.snapshot_all_tickers`
  - `key_columns: [snapshot_date]`

Output table schema (from UC):
- `_id`, `_footprint`, `snapshot_date`, `access_ts`, `headers`, `content`
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/bronze/massive.snapshot_all_tickers/ddl.sql`

Potential gotcha:
- The producer can emit **multiple rows per run** (pagination). With `key_columns: [snapshot_date]`, that can create multiple source rows for the same merge key if pagination returns >1 page.

---

### 8) `silver-massive-snapshot_all_tickers`

YAML asset:
- `yaml_file`: `silver/massive.snapshot_all_tickers/pipeline.yaml`
- Deployed path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/massive.snapshot_all_tickers/pipeline.yaml`

Execution:
- `config.mode: streaming`
- Trigger: `available_now`
- Checkpoint: `s3://datsando-prod/pipeline_equities/checkpoints/silver/massive/snapshot_all_tickers`

Inputs:
- `bronze.massive.snapshot_all_tickers` via `ReadTable` with CDF:
  - `readChangeFeed: True`
  - `startingVersion: 5` (hard-coded)

Pipeline components:
- Producer: `ReadTable`
- Operators (high level):
  - Filter inserts + postimage updates
  - Cast `content` to string and parse JSON
  - Explode `tickers[]` array into one row per ticker per snapshot_date
  - Build typed structs for day/quote/trade/min/previous_day
- Consumer: `MergeTable`
  - `table: silver.massive.snapshot_all_tickers`
  - `key_columns: [ticker, snapshot_date]`

Output table schema (from UC):
- `_id`, `_footprint`
- `ticker`, `snapshot_date`, `todays_change_percent`, `todays_change`, `updated_ts`
- Structs: `day`, `last_quote`, `last_trade`, `min`, `previous_day`
- DDL path: `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/silver/massive.snapshot_all_tickers/ddl.sql`

---

## Not in `pipeline_equities` job (but present elsewhere)

- Polygon pipelines exist (bronze/silver) under `superwind` repo and UC (`bronze.polygon.*`, `silver.polygon.*`), but the scheduled `pipeline_equities` job currently uses **massive** for snapshot tickers.
- Additional YAML assets exist under `/Workspace/Deployments/pipeline_equities/prd/files/src/pipeline_equities/assets/edgar` (including `bronze.edgar.filings_rss.yaml`), but the job uses the per-task `assets/{bronze,silver}/.../pipeline.yaml` layout.
