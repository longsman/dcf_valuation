# Project State Notes (Databricks + Superwind + DCF Valuation)

Date: 2026-01-14

> **Note:** The application bundle was renamed from `pipeline_equities` to `dcf_valuation` on 2026-01-14.

This file is a “current state” snapshot of what exists in the repo *and* what exists in the live Databricks workspace. The goal is to ground future planning (a scalable Damodaran-style DCF pipeline) in reality: existing jobs, bundles, YAML pipelines, and Unity Catalog tables.

Companion note:

- `docs/DCF_VALUATION_TASK_MAP.md` (task → YAML asset → UC table/columns map)

## 1) Local Repo Layout (`dbricks/`)

Top-level highlights:

- `superwind`: the pipeline execution engine (not vendored here; consumed as a deployed wheel in the Databricks workspace).
- `docs/`: existing operational/design notes.
- `data/`: local copies of YAML pipelines and exported job/run JSON from past investigations.
- `scripts/nb_exec_superwind.py`: exported Databricks notebook runner (thin YAML runner).

Notable local pipeline configs (these appear to be *copies* of workspace YAML):

- `data/bronze.edgar.filings_rss.yaml`
- `data/silver.edgar.filings_rss.yaml`
- `data/bronze.polygon.snapshot_all_tickers.yaml`
- `data/silver.polygon.snapshot_all_tickers.yaml`

## 2) Databricks Workspace Identity

Host:

- `https://dbc-51f1a5f2-687a.cloud.databricks.com`

Databricks CLI:

- `Databricks CLI v0.278.0`
- Two valid CLI profiles exist for the same host: `DEFAULT` and `dbc-51f1a5f2-687a`.
  - Many CLI calls require `-p DEFAULT` to avoid “multiple profiles matched” errors.

Current user (this session):

- `la.long.n@outlook.com`

## 3) Workspace Object Inventory (high-level)

Key workspace roots:

- `/Workspace/Users/...` (user homes)
- `/Workspace/Repos/...` (Repos)
- `/Workspace/Deployments/...` (Databricks Asset Bundle deployments)

Users observed under `/Workspace/Users`:

- `/Workspace/Users/datsando@outlook.com`
- `/Workspace/Users/la.long.n@outlook.com`
- `/Workspace/Users/lee.nathan.sh@outlook.com`

Repos observed:

- `/Workspace/Users/datsando@outlook.com/superwind` (Databricks Repo)
  - Remote: `https://github.com/datsando/superwind` (branch `main`)
  - Contains `pipelines/{edgar,polygon,fred}` and notebook runner `notebooks/exec-superwind`.
- `/Workspace/Repos/la.long.n@outlook.com/scratchpad` (Databricks Repo)

## 4) Bundles / Deployments (the “productionized” system)

Two bundle deployments exist under `/Workspace/Deployments`:

### 4.1 `superwind` bundle

- Deployment path: `/Workspace/Deployments/superwind/prd`
- Deployed version (pyproject): `superwind==0.2.2`
- Provides:
  - `exec_superwind` python wheel entry point (Fire CLI)
  - YAML loading with `$ENV{}`, `$VAR{}`, `$ASSET_PATH{}`, and `include:`
  - Producers/operators/consumers registries
  - Delta table sinks (`MergeTable`, `SaveAsTable`) with `_id` + `_footprint` meta
  - **FRED** integration via a Spark DataSource named `fred_series_observations` (registered during pipeline execution)

### 4.2 `dcf_valuation` bundle (formerly `pipeline_equities`)

- Deployment path: `/Workspace/Deployments/dcf_valuation/prd`
- Uses `superwind==0.2.2` as a dependency.
- Bundle config (deployed `databricks.yaml`) indicates:
  - Artifacts built via `uv build`.
  - Job definitions in `resources/*.yaml`.
  - "from_package" default: `dcf_valuation.assets`.

The key design point:

- `dcf_valuation` runs pipelines as **Python wheel tasks**, not notebook tasks.
- Each task calls `superwind.cli.exec_superwind` and passes:
  - `from_package=dcf_valuation.assets`
  - `yaml_file=<relative path inside assets>`

This is the current "config-driven pipeline development" pattern at scale.

## 5) Jobs Inventory

There are 6 jobs in the workspace:

- `dcf_valuation` — scheduled UNPAUSED
- `[dev lee_nathan_sh] edgar` (job_id `668955146306050`) — scheduled PAUSED
- `[dev lee_nathan_sh] mtgjson-silver` (job_id `531478911629089`)
- `[dev lee_nathan_sh] mtgjson-bronze` (job_id `161819182351307`)
- `daily sp500 membership` (job_id `159380051435609`)
- `superwind` (job_id `413747026668475`) — scheduled PAUSED

### 5.1 `dcf_valuation` task graph

Defined in `/Workspace/Deployments/dcf_valuation/prd/files/resources/dcf_valuation.job.yaml`:

- `bronze-edgar-form10_filings_rss` → `silver-edgar-form10_filings_rss`
- `bronze-edgar-company_facts` (depends on silver form10)
- `silver-edgar-company_facts`
- `bronze-fred-series_observations` → `silver-fred-market_yield_10yr`
- `bronze-massive-snapshot_all_tickers` → `silver-massive-snapshot_all_tickers`

Each task is a `python_wheel_task`:

- `package_name: superwind`
- `entry_point: exec_superwind`
- `named_parameters:
  - from_package: dcf_valuation.assets
  - yaml_file: <...>/pipeline.yaml`

### 5.2 `superwind` job

- Uses a mix of:
  - Workspace notebooks under `/Workspace/Users/datsando@outlook.com/jobs/...`
  - Git-source notebooks: `notebooks/exec-superwind` with `yaml_file: ../pipelines/...`
- This looks like an older/experimental execution mode compared to `dcf_valuation`.

## 6) Unity Catalog: Catalogs, Schemas, Tables

Catalogs relevant to this project:

- `bronze` (managed)
- `silver` (managed)
- `gold` (managed, currently empty)

Schemas in `bronze`:

- `edgar`, `fred`, `massive`, `polygon` (plus others)

Schemas in `silver`:

- `edgar`, `fred`, `massive`, `polygon` (plus others)

### 6.1 Key tables (EDGAR)

Bronze EDGAR:

- `bronze.edgar.form10_filings_rss` (raw parsed feed entries)
- `bronze.edgar.company_facts` (raw companyfacts JSON per `(cik, accession_number)`)
- `bronze.edgar.filings_rss` (older pipeline variant)
- `bronze.edgar.backup_company_facts` (exists; purpose TBD)

Silver EDGAR:

- `silver.edgar.form10_filings_rss` (normalized feed: cik, accession_number, filed_date, etc)
- `silver.edgar.company_facts` (fully exploded XBRL facts table)
- `silver.edgar.filings_rss` (older pipeline variant)

The “facts” primitive for DCF work:

- `silver.edgar.company_facts` has columns like:
  - `cik`, `taxonomy`, `tag`, `unit_of_measure`, `val`, `accn`, `start`, `end`, `fy`, `fp`, `filed`, `form`, `frame`

### 6.2 Key tables (Risk-free rate)

- `bronze.fred.series_observations` (series_id `DGS10`, raw observation stream)
- `silver.fred.market_yield_10yr` (cleaned: `observation_date`, `percent`)

### 6.3 Key tables (Equity universe / tickers)

- `bronze.massive.snapshot_all_tickers` (raw bytes/json snapshots by date)
- `silver.massive.snapshot_all_tickers` (normalized per-ticker snapshot fields)

There are also legacy polygon tables:

- `bronze.polygon.snapshot_all_tickers`, `bronze.polygon.snapshot_all_tickers_tmp`, etc.
- `silver.polygon.snapshot_all_tickers`

## 7) Existing DCF-related prototypes in the workspace

In `/Workspace/Users/datsando@outlook.com/superwind`:

- Notebook `dcf-calcs`
  - Contains exploratory Spark code to compute implied ERP via numerical solve (bisect) and sketches for intrinsic valuation.
- Notebook `silver-edgar-company_facts-cleansing-analysis`
  - SQL exploration of `silver.edgar.company_facts` tags/frames and sanity checks.

These are valuable as references, but they are not yet production pipelines.

## 8) Observed gaps (useful for future planning)

- No DLT pipelines are defined (`databricks pipelines list-pipelines` returned empty), so "pipelines" currently means **jobs + YAML-driven superwind pipelines**.
- `gold` catalog exists but is empty — a natural home for scaled DCF outputs.
- There is no canonical "company dimension" table visible yet (e.g., `edgar.company_tickers` / CIK↔ticker mapping) even though some YAML placeholders exist.
- Company facts extraction exists and scales (streaming + CDF), but we still need:
  - Selection/standardization of the accounting primitives needed for DCF
  - A consistent way to translate XBRL tags into financial statement line items (Revenue, EBIT, Taxes, Debt, Cash, etc)
  - A valuation output schema (gold layer) that supports per-company DCF assumptions + versions + auditability

---

## 9) Known Issues and Pitfalls

### 9.1 ExecSQL: Use `data`, NOT `__THIS__`

**Severity: HIGH — This has caused multiple production failures.**

When using the `ExecSQL` operator in superwind pipeline YAML, SQL queries must reference the incoming DataFrame as `data` (the default temp view name), **not** `__THIS__`.

```yaml
# CORRECT
- variant: ExecSQL
  parameters:
    sql_query: |
      select * from data d
      left join other_table t on d.id = t.id

# WRONG — will fail with TABLE_OR_VIEW_NOT_FOUND
- variant: ExecSQL
  parameters:
    sql_query: |
      select * from __THIS__
```

The `__THIS__` pattern may be familiar from other frameworks (dbt, etc.), but superwind creates a temp view named `data` by default (see `superwind/operators/transforms.py` in the superwind repo).

**Historical failures (all fixed by changing `__THIS__` to `data`):**
- `gold.financials.statement_lines` — 2026-01-14
- `gold.valuation.dcf_inputs` — 2026-01-14

### 9.2 Delta CDF: Version and VACUUM issues

Streaming pipelines using Change Data Feed (CDF) can fail when:
1. `startingVersion: 0` is set but old versions were vacuumed
2. CDF wasn't enabled when the table was created

**Common errors:**
- `VersionNotFoundException: Cannot time travel Delta table to version 0`
- `DELTA_MISSING_CHANGE_DATA: Error getting change data for range [0, N]`
- `DELTA_CHANGE_DATA_FILE_NOT_FOUND: File ... cannot be found`

**Fixes:**
- Use `startingVersion: latest` for new pipelines (no backfill)
- Check `DESCRIBE HISTORY table` for valid versions
- Enable CDF: `ALTER TABLE ... SET TBLPROPERTIES (delta.enableChangeDataFeed = true)`
- Reset checkpoint by changing `checkpoint_path` (e.g., append `_v2`)

### 9.3 VOID column type in MERGE

SQL queries with `null as column_name` create VOID type columns that Delta can't merge.

```sql
-- WRONG: creates VOID type
select null as cik, ...

-- CORRECT: explicit type cast
select cast(null as string) as cik, ...
```

### 9.4 Pydantic parameter names

The `ExecSQL` operator requires `sql_query:` (not `sql:`). Check operator source code for exact parameter names if validation errors occur.

---

If you want, next I can add a companion note that maps each pipeline YAML → the exact UC tables it produces (and which columns are available for DCF primitives).
