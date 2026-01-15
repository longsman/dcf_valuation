# dbricks — Databricks DCF valuation pipelines (powered by Superwind)

This repo builds a Damodaran-style discounted cash flow (DCF) system on Databricks.

The core idea is intentionally simple:
- **Pipelines are YAML** (declarative producer → operators → consumer).
- **Jobs run YAML** by calling `superwind.cli.exec_superwind` as a Databricks `python_wheel_task`.
- **Outputs are Unity Catalog Delta tables** in `bronze`, `silver`, `gold`.

This `README.md` is intended to be the single “source of truth” for how the project works. The `docs/` folder contains historical notes that can be deleted once this README feels complete.

---

## Mental Model

Think of the system as two wheels + one job:

- `superwind/` = the execution engine (framework wheel)
- `dcf_valuation/` = the project (pipelines + seeds + job definitions)
- Databricks Job = calls Superwind to run each pipeline

```text
                      (Databricks Asset Bundles)

  superwind wheel                         dcf_valuation wheel
  (engine)                                (pipelines + seeds)
       |                                         |
       | dependency                               | from_package
       v                                         v
+-------------------------------------------------------------------+
|                         Databricks Workflow Job                    |
|                 tasks = python_wheel_task (superwind)              |
|                                                                    |
|  task: gold-valuation-dcf_inputs                                   |
|    package_name: superwind                                         |
|    entry_point: exec_superwind                                     |
|    named_parameters:                                               |
|      from_package: dcf_valuation.assets                            |
|      yaml_file: gold/valuation.dcf_inputs/pipeline.yaml            |
+-------------------------------------------------------------------+
                              |
                              v
                     Unity Catalog Delta tables
                   (bronze / silver / gold)
```

### What you edit most often
- Pipeline definitions: `dcf_valuation/src/dcf_valuation/assets/**/pipeline.yaml`
- Table contracts / properties: `dcf_valuation/src/dcf_valuation/assets/**/ddl.sql`
- Seed reference data: `dcf_valuation/src/dcf_valuation/assets/gold/seed/**`

---

## Repo Layout

```text
./
  dcf_valuation/              Databricks bundle + pipelines + seeds
    databricks.yaml           Bundle definition (dev/prd targets)
    resources/*.job.yaml      Databricks Workflow jobs (YAML)
    src/dcf_valuation/
      assets/                 Pipeline YAML + DDL + seed CSVs
      extensions/             Project-specific Superwind components

  superwind/                  Databricks bundle + framework wheel
    databricks.yml            Bundle definition (dev/prd targets)
    src/superwind/            Pipeline engine (registries, operators, consumers)

  scripts/                    Local exports (e.g., notebook runner)
  docs/                       Historical notes (superseded by this README)
  data/                       Investigation artifacts / older YAML copies
```

---

## How Superwind Pipelines Work (the 2-minute primer)

A pipeline YAML has three conceptual parts:

1) **Producer**: creates a Spark DataFrame (e.g., call an API, read a Delta table)
2) **Operators**: transform the DataFrame (SQL, casts, filters, reshaping)
3) **Consumer**: writes the DataFrame (usually Delta MERGE into a UC table)

Superwind loads YAML using `superwind.definition.yaml.YAMLPipelineDefinition.load(...)` and then resolves `variant:` strings through import-time registries.

### YAML features you’ll see
- `$ENV{NAME:default}`: inject an environment variable (with default)
- `$ASSET_PATH{package, path}`: resolve a file packaged inside a wheel
- `include:`: YAML “mixins” via deep merge

### Streaming vs batch (important nuance)
Many pipelines are `mode: streaming` but use `available_now: True`. That means:
- they run like an incremental batch (consume all available CDF changes, then stop)
- **state is tracked by checkpoints** (`checkpoint_path`)
- **schema evolution / backfills often require a checkpoint reset**

---

## Jobs (what gets created in Databricks)

There are two job definitions in `dcf_valuation/resources/`:

- `dcf_valuation/resources/dcf_valuation.job.yaml` — full bronze→silver→gold workflow (PRD-style)
- `dcf_valuation/resources/dcf_valuation_dev.job.yaml` — gold-only workflow (DEV-style; assumes PRD already populated silver)

Schedules (America/New_York):
- `dcf_valuation`: `0 0 9-21/3 ? * MON-FRI`
- `dcf_valuation_dev`: `0 40 9-21/3 ? * MON-FRI` (40 minutes after)

Important repo nuance: `dcf_valuation/databricks.yaml` currently includes only the dev job resource:
- `dcf_valuation/resources/dcf_valuation_dev.job.yaml`
- `dcf_valuation/resources/dcf_valuation.job.yaml` is present but commented out in the bundle `include:` list.

---

## Data Products (tables this project builds)

### High-level lineage

```text
External APIs / Sources
  |-- SEC EDGAR (filings + companyfacts)
  |-- FRED (10Y yield)
  |-- Massive (ticker snapshots)

        | ingest
        v
BRONZE (raw)  --->  SILVER (normalized)  --->  GOLD (modeled + valuation)

        | CDF streaming / available_now
        v
Valuation is filing-triggered:
  gold.edgar.filing_events  ->  gold.valuation.dcf_inputs  ->  dcf_cashflows  ->  dcf_results
```

### Bronze tables
- `bronze.edgar.form10_filings_rss` — raw SEC Atom feed entries
- `bronze.edgar.company_facts` — raw SEC companyfacts JSON per `(cik, accession_number)`
- `bronze.fred.series_observations` — raw FRED observations for `DGS10`
- `bronze.massive.snapshot_all_tickers` — raw HTTP payload snapshots (bytes)

### Silver tables
- `silver.edgar.form10_filings_rss` — normalized filings feed (cik, accession, filed_date, form_type, link)
- `silver.edgar.company_facts` — exploded XBRL facts (normalized, queryable)
- `silver.fred.market_yield_10yr` — cleaned 10Y yield (`observation_date`, `percent`)
- `silver.massive.snapshot_all_tickers` — normalized per-ticker snapshot (last_trade, prev_day, etc.)

### Gold tables (reference + modeling + outputs)
Reference / seed-backed:
- `gold.damodaran.implied_erp`
- `gold.damodaran.industry_betas`
- `gold.damodaran.ratings_spreads`
- `gold.damodaran.synthetic_rating_bands`
- `gold.dim.sic_to_damodaran_industry`
- `gold.dim.cik_ticker` — CIK↔ticker mapping (seeded)
- `gold.financials.tag_map` — XBRL tag→line_item mapping (seeded)
- `gold.valuation.assumption_sets` — named assumption set presets

Computed:
- `gold.edgar.filing_events` — canonical “event queue” of new filings (from silver filings)
- `gold.dim.company` — company metadata + routing flags
- `gold.market.prices_daily` — canonical daily price per ticker (from Massive)
- `gold.financials.statement_lines` — best fact per `(cik, line_item, period_end, …)`
- `gold.financials.flow_quarterly` → `gold.financials.flow_ttm`
- `gold.financials.balance_quarterly` → `gold.financials.working_capital`

Valuation outputs:
- `gold.valuation.dcf_inputs` — assembled inputs per `(cik, valuation_date, assumption_set_id, source_accn, model_type)`
- `gold.valuation.dcf_cashflows` — year-by-year projections + PVs
- `gold.valuation.dcf_results` — final enterprise/equity value + per-share + upside/downside

---

## Quickstart (local dev → deploy → run)

### Prereqs
- Python `3.12` (repo root `.python-version`)
- `uv` installed
- Databricks CLI installed and authenticated

### 1) Set up Python env (recommended)

```bash
# Framework
cd superwind
uv sync --dev

# Pipelines package
cd ../dcf_valuation
uv sync --dev
```

### 2) Authenticate to Databricks

Tip: this workspace often has multiple CLI profiles pointing at the same host.
When in doubt, pass `-p DEFAULT`.

```bash
databricks auth profiles
databricks current-user me -p DEFAULT -o json
```

### 3) Deploy bundles

Deploy `superwind` first (engine), then `dcf_valuation` (pipelines/job).

```bash
cd superwind
databricks bundle validate --target dev
databricks bundle deploy --target dev

cd ../dcf_valuation
databricks bundle validate --target dev
databricks bundle deploy --target dev
```

### 4) Run the job

```bash
# Runs the dev job resource defined in dcf_valuation/resources/dcf_valuation_dev.job.yaml
cd dcf_valuation
databricks bundle run --target dev dcf_valuation_dev
```

---

## Databricks CLI field guide (things you’ll use a lot)

### Workspace navigation
```bash
databricks workspace list /Workspace/Deployments -p DEFAULT -o json
```

### Jobs
```bash
databricks jobs list -p DEFAULT -o json
# databricks jobs get -p DEFAULT -o json <JOB_ID>
# databricks jobs list-runs -p DEFAULT -o json --job-id <JOB_ID>
```

### Unity Catalog inspection
```bash
databricks catalogs list -p DEFAULT -o json
# databricks schemas list <CATALOG> -p DEFAULT -o json
# databricks tables list <CATALOG> <SCHEMA> -p DEFAULT -o json --max-results 0
# databricks tables get gold.valuation.dcf_results -p DEFAULT -o json
```

### Inspect what a deployed task actually runs
For production deployments:
- Job YAMLs: `/Workspace/Deployments/<bundle>/<target>/files/resources/*.yaml`
- Pipeline YAMLs: `/Workspace/Deployments/<bundle>/<target>/files/src/<pkg>/assets/**/pipeline.yaml`

For development deployments (Databricks bundle default):
- `/Workspace/Users/<YOU>/.bundle/<bundle>/<target>/...`

---

## Operational “Sharp Edges” (read before debugging)

### 1) ExecSQL temp view name is `data` (NOT `__THIS__`)
Superwind’s `ExecSQL` operator does:
- `df.createOrReplaceTempView('data')`

So your SQL must reference `data`:

```yaml
- variant: ExecSQL
  parameters:
    sql_query: |
      select * from data
```

### 2) CDF + checkpoints: resets are done by changing `checkpoint_path`
When a streaming pipeline breaks due to VACUUM / version issues, the safe reset is usually:
- bump `checkpoint_path` (e.g., `_v1` → `_v2`)
- optionally adjust `startingVersion`

Current checkpoint paths (as configured in YAML):
- `s3://datsando-prod/dcf_valuation/checkpoints/bronze/edgar/company_facts_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/bronze/fred/series_observations_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/silver/edgar/filings_rss_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/silver/edgar/company_facts_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/silver/fred/market_yield_10yr_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/silver/massive/snapshot_all_tickers_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/gold/edgar/filing_events_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/gold/financials/statement_lines_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/gold/market/prices_daily_v1`
- `s3://datsando-prod/dcf_valuation/checkpoints/gold/valuation/dcf_inputs_v1`

### 3) Some pipelines use secret scope `pipeline_equities`
This is not a “rename” history of this repo.

`pipeline_equities` is an existing Databricks secret scope name (owned/managed elsewhere, e.g. a colleague’s job/deployment) that this repo currently depends on for API keys.

Required secrets (as referenced by current YAML):
- `pipeline_equities/fred.api_key` — used by `bronze.fred.series_observations`
- `pipeline_equities/massive.api_key` — used by `bronze.massive.snapshot_all_tickers`

If these pipelines fail with auth/secret errors, the fix is usually permissions (you/job run-as identity needs access to that scope), not code changes.

### 4) Databricks permissions matter (especially for MERGE)
The job’s **run-as identity** needs, at minimum:
- `USAGE` on catalog + schema
- `MODIFY` on target tables for `MergeTable`

### 5) Delta MERGE can fail if you introduce VOID columns
In SQL transforms, `null as some_col` can infer VOID type.
Prefer `cast(null as <type>) as some_col`.

---

## Dev vs PRD deployments (safety notes)

- `dcf_valuation/databricks.yaml` defines two targets: `dev` and `prd`.
- Only `prd` specifies `root_path: /Workspace/Deployments/...` and a `run_as` user.

Two important implications:
1) Dev vs prd deployments are different *workspace paths*, but the pipelines still write to the same UC tables (`bronze.*`, `silver.*`, `gold.*`).
2) Production runs may execute as a different identity than your dev runs (because `run_as` is set for `prd`).

If you need strict isolation, you’ll want separate catalogs (e.g., `bronze_dev`) or env-var-driven table names.

---

## Notes on Superwind vs dcf_valuation extensions

`dcf_valuation` registers extra Superwind components (so the YAML can stay mostly SQL/YAML-driven):
- `ReadCSV` producer (loads packaged seed CSVs)
- `ExecSQL` producer (run batch SQL and return a DataFrame)

See: `dcf_valuation/src/dcf_valuation/extensions/producers.py`

Superwind provides the general pipeline engine, registries, core operators, and Delta consumers. The Databricks-deployed Superwind wheel must also provide variants referenced by the pipelines (e.g., `ParseRSSFeed`, `RESTOperator`, `FREDSeriesObservations`). If you see runtime errors like `KeyError: 'FREDSeriesObservations'`, that’s a registry/variant mismatch between pipeline YAML and the installed Superwind wheel.

---

## Appendix: Notebook runner (legacy execution style)

This repo also has a thin notebook-style runner exported as Python:
- `scripts/nb_exec_superwind.py`

Production jobs here primarily use the wheel-task runner (`superwind.cli.exec_superwind`), but the notebook runner is useful for understanding the minimal runtime behavior.
