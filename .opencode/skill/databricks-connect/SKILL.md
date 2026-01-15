---
name: databricks-connect
description: Runbook for authenticating, deploying bundles, inspecting Unity Catalog, and using Databricks Connect in this repo.
---

# SKILL: Databricks CLI + Bundles + Databricks Connect (for this repo)

This skill is a **runbook** for any fresh agent session working in this repo.

It documents how to:
- authenticate to the Databricks workspace,
- navigate Jobs/Repos/Deployments,
- inspect Unity Catalog tables,
- deploy/run Databricks Asset Bundles,
- and (optionally) use Databricks Connect for local iteration.

It assumes the repo follows the Superwind pattern: pipelines are **YAML assets** executed via `superwind.cli.exec_superwind` as Databricks `python_wheel_task`s.

---

## 0) Read-first documents in this repo

Before changing anything, read:
- `docs/PROJECT_STATE.md`
- `docs/PIPELINE_EQUITIES_TASK_MAP.md`
- `docs/DCF_PIPELINE_PLAN.md`
- `docs/SUPERWIND_DESIGN.md`

These capture the current workspace topology and how `pipeline_equities` and `superwind` are deployed.

---

## 1) Authentication (required)

### 1.1 What the agent must tell the user
If Databricks CLI commands fail with auth errors, **ask the user to login**.

Typical options (depends on CLI version and org policy):
- `databricks auth login --host <DATABRICKS_HOST>`
- or `databricks configure`

Do not ask the user for tokens in chat. Let the user handle authentication locally.

### 1.2 Verify auth works
Use these commands:
- `databricks auth profiles`
- `databricks current-user me -p DEFAULT -o json`

If `databricks current-user me` fails, authentication is not set up (or wrong profile).

### 1.3 Profile gotcha: multiple profiles match host
This workspace often has **multiple profiles pointing at the same host**, which causes errors like:
- `Multiple profiles matched …`

**Mitigation**
- Always pass `-p DEFAULT` (or whichever profile the user wants).
- Optionally export: `export DATABRICKS_CONFIG_PROFILE=DEFAULT`

---

## 2) Workspace navigation (CLI primitives)

### 2.1 List workspace objects
- `databricks workspace list /Workspace -p DEFAULT -o json`
- `databricks workspace list /Workspace/Users -p DEFAULT -o json`
- `databricks workspace list /Workspace/Repos -p DEFAULT -o json`
- `databricks workspace list /Workspace/Deployments -p DEFAULT -o json`

### 2.2 Export a workspace file/notebook to local disk
Use `databricks workspace export`:
- `databricks workspace export <WORKSPACE_PATH> -p DEFAULT --format AUTO --file /tmp/outfile`
- For notebooks as source: `--format SOURCE`

This is the safest way to inspect what is deployed without editing in-place.

---

## 3) Unity Catalog inspection (tables, schemas)

### 3.1 Discover catalogs and schemas
- `databricks catalogs list -p DEFAULT -o json`
- `databricks schemas list <CATALOG> -p DEFAULT -o json`

### 3.2 List tables in a schema
- `databricks tables list <CATALOG> <SCHEMA> -p DEFAULT -o json --max-results 0`

### 3.3 Inspect table schema
- `databricks tables get <CATALOG>.<SCHEMA>.<TABLE> -p DEFAULT -o json`

This is useful for confirming what columns exist before writing transforms.

---

## 4) Jobs (Workflows) inspection

### 4.1 List jobs
- `databricks jobs list -p DEFAULT -o json > /tmp/jobs.json`

### 4.2 Get a job definition
- `databricks jobs get -p DEFAULT -o json <JOB_ID> > /tmp/job.json`

### 4.3 Runs and debugging (optional)
If you need to check a run status/logs:
- `databricks jobs list-runs -p DEFAULT -o json --job-id <JOB_ID>`
- `databricks jobs get-run -p DEFAULT -o json <RUN_ID>`

---

## 5) Databricks Asset Bundles (deploy/run)

### 5.1 What bundles look like in the workspace
After `databricks bundle deploy`, Databricks writes to:
- `/Workspace/Deployments/<bundle-name>/<target>`

Inspect deployed files:
- `databricks workspace list /Workspace/Deployments/<bundle>/<target>/files -p DEFAULT -o json`

### 5.2 Local workflow (recommended)
From the bundle root directory (e.g. `pipeline_equities/` or `superwind/`):
- `databricks bundle validate --target dev`
- `databricks bundle deploy --target dev`
- `databricks bundle run --target dev <resource-name>`

Notes:
- `dev` targets typically deploy schedules as paused.
- `prd/prod` targets may be scheduled and should be handled carefully.

### 5.3 Using `uv` (preferred)
Use `uv` to keep dependencies project-scoped:
- `uv sync` (or `uv sync --dev`)
- `uv run python ...`
- `uv build` (for bundle artifacts if configured)

If a script fails under `uv run` due to missing deps, add deps to the relevant `pyproject.toml` instead of relying on system Python.

---

## 6) Superwind execution model (how YAML pipelines run)

### 6.1 Two execution styles exist
1) **Notebook runner**:
- a notebook (e.g. `exec-superwind`) reads a `yaml_file` parameter and calls `superwind.definition.yaml.YAMLPipelineDefinition.load(...).run()`.

2) **Python wheel task runner (preferred / production)**:
- Databricks job task uses:
  - `python_wheel_task`
  - `package_name: superwind`
  - `entry_point: exec_superwind`
  - `named_parameters`:
    - `from_package=<package-with-assets>`
    - `yaml_file=<path-within-assets>`

This is the pattern used by `pipeline_equities` today.

### 6.2 How to inspect what a task runs
- Export the job resource YAML from the deployment:
  - `/Workspace/Deployments/<bundle>/<target>/files/resources/*.yaml`
- Export the pipeline YAML from the deployment:
  - `/Workspace/Deployments/<bundle>/<target>/files/src/<package>/assets/.../pipeline.yaml`

---

## 7) Databricks Connect (optional, but useful)

Databricks Connect is used to run Spark code locally against a Databricks cluster.

### 7.1 Install
If the project defines a dev dependency group:
- `uv sync --dev`

### 7.2 Config requirements
Databricks Connect requires:
- workspace host
- auth (token or OAuth, depending on org)
- a target compute (cluster id)

Agents should NOT invent these values.
If missing, ask the user to provide or configure:
- `DATABRICKS_HOST`
- auth via CLI/OAuth
- a `DATABRICKS_CLUSTER_ID` (or instruct how to choose one)

### 7.3 How to find clusters (if needed)
- `databricks clusters list -p DEFAULT -o json`

The user should select a cluster compatible with the installed `databricks-connect` version.

---

## 8) Safety / operational conventions

- Prefer **export + inspect** over editing workspace files directly.
- Avoid destructive commands (`workspace delete`, `jobs delete`, etc.) unless explicitly requested.
- When CLI errors mention multiple profiles, always retry with `-p DEFAULT`.
- Keep valuation logic in **assets** (SQL/YAML) where possible, and use minimal custom operators.

---

## 9) Quick command cheat sheet

Identity + auth:
- `databricks auth profiles`
- `databricks current-user me -p DEFAULT -o json`

Deployments:
- `databricks workspace list /Workspace/Deployments -p DEFAULT -o json`

Jobs:
- `databricks jobs list -p DEFAULT -o json`
- `databricks jobs get -p DEFAULT -o json <JOB_ID>`

Unity Catalog:
- `databricks catalogs list -p DEFAULT -o json`
- `databricks schemas list <CATALOG> -p DEFAULT -o json`
- `databricks tables list <CATALOG> <SCHEMA> -p DEFAULT -o json --max-results 0`
- `databricks tables get <CATALOG>.<SCHEMA>.<TABLE> -p DEFAULT -o json`

---

## 10) CLI Command Syntax Gotchas

### 10.1 Schema creation (argument order matters!)
```bash
# CORRECT: schema name FIRST, then catalog
databricks schemas create <SCHEMA_NAME> <CATALOG_NAME> -p DEFAULT

# WRONG: will error "Catalog 'schema_name' does not exist"
databricks schemas create <CATALOG_NAME> <SCHEMA_NAME> -p DEFAULT
```

### 10.2 Workspace import (use --file flag)
```bash
# CORRECT: single positional arg (target), --file for source
databricks workspace import <WORKSPACE_PATH> --file <LOCAL_FILE> -p DEFAULT --format AUTO --overwrite

# WRONG: two positional args
databricks workspace import <LOCAL_FILE> <WORKSPACE_PATH> -p DEFAULT
```

### 10.3 Tables delete (fully qualified name)
```bash
# CORRECT
databricks tables delete <CATALOG>.<SCHEMA>.<TABLE> -p DEFAULT

# Example
databricks tables delete gold.dim.cik_ticker -p DEFAULT
```

### 10.4 Job run-now (use --no-wait for long jobs)
```bash
# Synchronous (may timeout after 2 min)
databricks jobs run-now <JOB_ID> -p DEFAULT

# Asynchronous (returns immediately with run_id)
databricks jobs run-now <JOB_ID> -p DEFAULT --no-wait -o json
```

### 10.5 Get detailed task errors
```bash
# Get run overview
databricks jobs get-run <RUN_ID> -p DEFAULT -o json

# Get specific task output (includes error + error_trace)
databricks jobs get-run-output <TASK_RUN_ID> -p DEFAULT -o json

# Extract just the error
databricks jobs get-run-output <TASK_RUN_ID> -p DEFAULT -o json | jq -r '.error'
```

### 10.6 DBFS vs S3 paths
The CLI can only access `dbfs:/` paths, NOT `s3://` paths directly:
```bash
# WORKS
databricks fs ls dbfs:/FileStore/wheels -p DEFAULT
databricks fs cp local.whl dbfs:/FileStore/wheels/ -p DEFAULT

# FAILS: "invalid scheme: s3"
databricks fs ls s3://bucket/path -p DEFAULT
databricks fs rm s3://bucket/path -p DEFAULT
```

**Workaround for S3 checkpoints:** Change the `checkpoint_path` in pipeline YAML to a new path (e.g., append `_v2`) rather than trying to delete the old checkpoint.

### 10.7 No SQL subcommand in this CLI version
```bash
# This does NOT exist
databricks sql warehouses list  # ERROR: unknown command "sql"

# Use API directly if needed
databricks api post /api/2.0/sql/statements -p DEFAULT --json '{...}'
```

---

## 11) Bundle Deploy Workarounds

### 11.1 Bundle deploy timeouts
`databricks bundle deploy` can take 5-10+ minutes for large bundles. If it times out:

**Option A: Direct wheel upload**
```bash
# Build the wheel locally
cd pipeline_equities && uv build

# Upload directly to the workspace artifacts location
databricks workspace import \
  /Workspace/Users/<USER>/.bundle/<BUNDLE>/dev/artifacts/.internal/<WHEEL>.whl \
  --file dist/<WHEEL>.whl \
  -p DEFAULT --format AUTO --overwrite
```

**Option B: Check environment library path**
```bash
# Find where the job expects the wheel
databricks jobs get <JOB_ID> -p DEFAULT -o json | jq '.settings.environments[0].spec.dependencies'
```

### 11.2 Wheel caching in serverless
When updating a wheel, the Databricks environment may cache the old version. Options:
- Increment the wheel version in `pyproject.toml`
- Change artifact paths in `databricks.yaml`
- Wait for environment refresh (or trigger new compute)

---

## 12) Delta Lake / Streaming Pipeline Issues

### 12.1 CDF version errors
When streaming pipelines fail with:
```
VersionNotFoundException: Cannot time travel Delta table to version 0. Available versions: [X, Y]
```

The source table was vacuumed and old versions are gone.

**Fixes:**
1. Set `startingVersion` to a valid version (e.g., the minimum available)
2. Use `startingVersion: latest` for new streaming pipelines (no backfill)
3. Change `checkpoint_path` to reset streaming state

### 12.2 VOID column type in MERGE
When a SQL query uses `null as column_name`, Delta Lake infers VOID type:
```
[DELTA_MERGE_ADD_VOID_COLUMN] Cannot add column `col` with type VOID
```

**Fix:** Always cast nulls to explicit types:
```sql
-- WRONG
null as cik

-- CORRECT
cast(null as string) as cik
cast(null as int) as sic
```

### 12.3 Resetting streaming checkpoints
Since S3 checkpoints can't be deleted via CLI, change the checkpoint path:
```yaml
# Before
checkpoint_path: s3://bucket/checkpoints/pipeline/v1

# After (forces fresh start)
checkpoint_path: s3://bucket/checkpoints/pipeline/v2
```

### 12.4 CDF not enabled from table creation
When streaming with CDF fails with:
```
[DELTA_MISSING_CHANGE_DATA] Error getting change data for range [0, N] as change data was not recorded for version [0].
```

The source table was created without CDF enabled, or CDF was enabled after version 0.

**Fixes:**
1. Enable CDF on the source table:
   ```sql
   ALTER TABLE catalog.schema.table SET TBLPROPERTIES (delta.enableChangeDataFeed = true)
   ```
2. Check when CDF was enabled: `DESCRIBE HISTORY catalog.schema.table`
3. Set `startingVersion` to the version when CDF was first enabled
4. Reset checkpoint path to avoid stale streaming state

---

## 13) Superwind ExecSQL Operator: Critical Pattern

### 13.1 The `__THIS__` vs `data` issue (COMMON FAILURE)

**This is a recurring issue that has caused multiple pipeline failures.**

When using the `ExecSQL` operator in superwind, SQL queries must reference the incoming DataFrame using the correct temp view name.

**The default temp view name is `data`, NOT `__THIS__`.**

```python
# From superwind/src/superwind/operators/transforms.py
class ExecSQL(BaseOperator):
    query_name: str = 'data'  # DEFAULT VIEW NAME
    
    def apply(self, df: DataFrame) -> DataFrame:
        df.createOrReplaceTempView(self.query_name)  # Creates view named 'data'
        return df.sparkSession.sql(self.query)
```

### 13.2 Correct SQL pattern

```yaml
# CORRECT: Reference 'data' in your SQL
operators:
  - variant: ExecSQL
    parameters:
      sql_query: |
        select
          d.cik,
          d.ticker,
          t.industry
        from data d  -- Use 'data', not '__THIS__'
        left join gold.dim.ticker_map t on d.ticker = t.ticker
```

```yaml
# WRONG: Will fail with TABLE_OR_VIEW_NOT_FOUND
operators:
  - variant: ExecSQL
    parameters:
      sql_query: |
        select * from __THIS__  -- FAILS: __THIS__ does not exist
```

### 13.3 When this error occurs

The `__THIS__` error is especially common when:
1. `streaming_defer_operators: True` is set (operators run inside foreachBatch)
2. SQL queries reference `__THIS__` instead of `data`
3. The pipeline was copied from another system that uses `__THIS__` convention

**Error message:**
```
[TABLE_OR_VIEW_NOT_FOUND] The table or view `__THIS__` cannot be found.
```

### 13.4 Custom view name (advanced)

If you need a different view name, specify it explicitly:
```yaml
operators:
  - variant: ExecSQL
    parameters:
      query_name: my_custom_view  # Override default 'data'
      sql_query: |
        select * from my_custom_view
```

### 13.5 Historical context

This issue has caused failures in:
- `gold.financials.statement_lines` (fixed 2026-01-14)
- `gold.valuation.dcf_inputs` (fixed 2026-01-14)

Both required changing `from __THIS__` to `from data` in the SQL query.
