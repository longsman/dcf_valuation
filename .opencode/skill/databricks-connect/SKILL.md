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

```bash
databricks workspace list /Workspace/Deployments -p DEFAULT -o json
databricks workspace export <PATH> -p DEFAULT --format AUTO --file /tmp/out
```

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

```bash
databricks jobs list -p DEFAULT -o json
databricks jobs get <JOB_ID> -p DEFAULT -o json
databricks jobs get-run <RUN_ID> -p DEFAULT -o json
```

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

## 6) Superwind execution model

Production uses `python_wheel_task` with `entry_point: exec_superwind` and `named_parameters: {from_package, yaml_file}`.

To inspect deployed pipelines:
```bash
# Job resource YAML
databricks workspace export /Workspace/Deployments/<bundle>/<target>/files/resources/<job>.yaml -p DEFAULT --file /tmp/job.yaml
# Pipeline YAML
databricks workspace export /Workspace/Deployments/<bundle>/<target>/files/src/<pkg>/assets/.../pipeline.yaml -p DEFAULT --file /tmp/pipeline.yaml
```

---

## 7) Safety / operational conventions

- Prefer **export + inspect** over editing workspace files directly.
- Avoid destructive commands (`workspace delete`, `jobs delete`, etc.) unless explicitly requested.
- When CLI errors mention multiple profiles, always retry with `-p DEFAULT`.
- Keep valuation logic in **assets** (SQL/YAML) where possible, and use minimal custom operators.

---

## 8) CLI Command Syntax Gotchas

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

**To query tables without a SQL Warehouse, see Section 12 (Command Execution API).**

---

## 9) Bundle Deploy Workarounds

If `databricks bundle deploy` times out, upload wheel directly:
```bash
uv build && databricks workspace import /Workspace/Users/<USER>/.bundle/<BUNDLE>/dev/artifacts/.internal/<WHEEL>.whl --file dist/<WHEEL>.whl -p DEFAULT --format AUTO --overwrite
```

**Wheel caching**: If updates don't take effect, increment version in `pyproject.toml` or change artifact paths.

---

## 10) Delta Lake / Streaming Issues

| Error | Fix |
|-------|-----|
| `VersionNotFoundException: Cannot time travel to version 0` | Set `startingVersion` to valid version, or use `latest`, or reset `checkpoint_path` |
| `[DELTA_MERGE_ADD_VOID_COLUMN]` | Cast nulls: `cast(null as string) as col` |
| `[DELTA_MISSING_CHANGE_DATA]` | Enable CDF: `ALTER TABLE t SET TBLPROPERTIES (delta.enableChangeDataFeed = true)`, then set `startingVersion` to when CDF was enabled |

**Reset streaming state**: Change `checkpoint_path` (e.g., append `_v2`) since S3 paths can't be deleted via CLI.

---

## 11) Superwind ExecSQL: Use `data` not `__THIS__`

**CRITICAL**: The default temp view name is `data`, NOT `__THIS__`.

```yaml
# CORRECT
- variant: ExecSQL
  parameters:
    sql_query: select * from data d left join gold.dim.t on d.id = t.id

# WRONG - fails with TABLE_OR_VIEW_NOT_FOUND
- variant: ExecSQL
  parameters:
    sql_query: select * from __THIS__
```

To use a custom view name: add `query_name: my_view` to parameters.

---

## 12) Querying Tables via Interactive Cluster (Cost Savings)

**PREFER THIS** over SQL Warehouses for ad-hoc queries to avoid extra compute costs.

**Default cluster**: `0115-232555-7zt65dzl` (HTTP path: `/sql/protocolv1/o/683875129393773/0115-232555-7zt65dzl`)

```bash
# Check cluster is running
databricks clusters get 0115-232555-7zt65dzl -p DEFAULT -o json | jq '.state'
```

**Query process** (Command Execution API):

```bash
# 1. Create context
CTX=$(databricks api post /api/1.2/contexts/create -p DEFAULT -o json --json '{"clusterId":"0115-232555-7zt65dzl","language":"python"}' | jq -r '.id')

# 2. Execute query (use toPandas, NOT toJSON - Spark Connect doesn't support toJSON)
CMD=$(databricks api post /api/1.2/commands/execute -p DEFAULT -o json --json "{\"clusterId\":\"0115-232555-7zt65dzl\",\"contextId\":\"$CTX\",\"language\":\"python\",\"command\":\"print(spark.sql('SELECT * FROM gold.valuation.dcf_results LIMIT 20').toPandas().to_json(orient='records',indent=2))\"}" | jq -r '.id')

# 3. Poll for results
sleep 5 && databricks api get "/api/1.2/commands/status?clusterId=0115-232555-7zt65dzl&contextId=$CTX&commandId=$CMD" -p DEFAULT -o json | jq -r '.results.data'

# 4. Cleanup
databricks api post /api/1.2/contexts/destroy -p DEFAULT -o json --json "{\"clusterId\":\"0115-232555-7zt65dzl\",\"contextId\":\"$CTX\"}"
```

**Gotcha**: Use `toPandas()` not `toJSON()` — Spark Connect doesn't implement `toJSON()`.
