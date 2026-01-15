# Job Run Remaining Issues Report

**Job ID:** 259919585799043  
**Run ID:** 909350286597450  
**Run Name:** [dev la_long_n] pipeline_equities  
**Report Date:** 2026-01-14T18:15:00Z  
**Workspace:** https://dbc-51f1a5f2-687a.cloud.databricks.com

---

## Current Status

| Metric | Count |
|--------|-------|
| **Successful Tasks** | 23 |
| **Failed Tasks** | 2 |
| **Skipped Tasks** | 2 |
| **Total Tasks** | 27 |

**Run URL:** https://dbc-51f1a5f2-687a.cloud.databricks.com/?o=683875129393773#job/259919585799043/run/909350286597450

---

## Resolved Issues (This Session)

### 1. `gold.financials.statement_lines` Table Not Created

**Root Cause:** Two issues combined:
1. SQL query used `__THIS__` placeholder, but the `ExecSQL` operator in `superwind` creates a temp view named `data`
2. CDF `startingVersion: 2313` referenced vacuumed files (VACUUM ran at version 2577-2578 on 2026-01-13)

**Fix Applied:**
- Changed `__THIS__` to `data` in SQL query at line 55
- Set `startingVersion: 2579` for one-time backfill (post-VACUUM version)
- Reverted to `startingVersion: latest` for incremental mode
- Reset checkpoint to `_v4` path

**File:** `pipeline_equities/src/pipeline_equities/assets/gold/financials.statement_lines/pipeline.yaml`

**Result:** Table created, all downstream financials tasks now succeed:
- `gold-financials-flow_quarterly`
- `gold-financials-balance_quarterly`
- `gold-financials-flow_ttm`
- `gold-financials-working_capital`

---

## Remaining Issues

### Issue 1: `gold-market-prices_daily` - CDF Files Vacuumed

**Status:** FAILED  
**Task Run ID:** 545757381231659 (from run 706525325416564)

**Error:**
```
[DELTA_CHANGE_DATA_FILE_NOT_FOUND] File s3://datsando-prod/catalogs/silver/__unitystorage/.../part-00000-56cac099-899a-4894-9b3b-b82295737d3a.c000.zstd.parquet 
referenced in the transaction log cannot be found. This can occur when the change data file 
is out of the retention period and has been deleted by the VACUUM statement.
```

**Root Cause:**
- Source table: `silver.massive.snapshot_all_tickers`
- Table has versions 0-120 in history
- CDF files for all versions have been vacuumed
- Even `startingVersion: 0` fails because underlying CDF parquet files are deleted

**Impact:**
- `gold.market.prices_daily` table not populated
- Downstream valuation tasks cannot run:
  - `gold-valuation-dcf_inputs` (depends on prices)
  - `gold-valuation-dcf_cashflows` (skipped)
  - `gold-valuation-dcf_results` (skipped)

**Current Configuration:**
```yaml
# File: gold/market.prices_daily/pipeline.yaml
config:
  mode: streaming
  checkpoint_path: s3://datsando-prod/pipeline_equities/checkpoints/gold/market/prices_daily_v4

producer:
  variant: ReadTable
  parameters:
    table: silver.massive.snapshot_all_tickers
    options:
      readChangeFeed: True
      startingVersion: $ENV{CDF_STARTING_VERSION:latest}
```

**Resolution Options:**

#### Option A: Batch Backfill (Recommended)
Create a one-time batch pipeline to load historical data without CDF:

```yaml
# New file: gold/market.prices_daily/backfill_pipeline.yaml
config:
  mode: batch

producer:
  variant: ReadTable
  parameters:
    table: silver.massive.snapshot_all_tickers
    # No CDF options - read full table

# ... same operators as streaming pipeline ...

consumer:
  variant: WriteTable  # or MergeTable
  parameters:
    table: gold.market.prices_daily
    mode: overwrite  # for initial load
```

Run once manually, then switch back to streaming for incremental updates.

#### Option B: Extend VACUUM Retention
Modify the source table's Delta properties to retain CDF files longer:

```sql
ALTER TABLE silver.massive.snapshot_all_tickers 
SET TBLPROPERTIES (
  'delta.deletedFileRetentionDuration' = 'interval 30 days',
  'delta.logRetentionDuration' = 'interval 30 days'
);
```

This prevents future VACUUM from deleting CDF files too aggressively.

#### Option C: Rebuild Source Table
If the source table needs historical CDF data:
1. Disable CDF temporarily
2. Reload all data
3. Re-enable CDF
4. Run streaming pipeline with `startingVersion: 0`

---

### Issue 2: `gold-valuation-dcf_inputs` - Upstream Dependency

**Status:** FAILED  
**Reason:** Depends on `gold.market.prices_daily` which doesn't exist

**Error:**
```
[TABLE_OR_VIEW_NOT_FOUND] The table or view `gold`.`market`.`prices_daily` cannot be found.
```

**Resolution:** Will auto-resolve once Issue 1 is fixed.

---

### Issue 3: Valuation Pipeline Chain Skipped

**Tasks Affected:**
- `gold-valuation-dcf_cashflows` (SKIPPED - upstream failed)
- `gold-valuation-dcf_results` (SKIPPED - upstream failed)

**Resolution:** Will auto-resolve once Issues 1 and 2 are fixed.

---

## Key File Locations

| Purpose | Path |
|---------|------|
| Statement Lines Pipeline | `pipeline_equities/src/pipeline_equities/assets/gold/financials.statement_lines/pipeline.yaml` |
| Market Prices Pipeline | `pipeline_equities/src/pipeline_equities/assets/gold/market.prices_daily/pipeline.yaml` |
| DCF Inputs Pipeline | `pipeline_equities/src/pipeline_equities/assets/gold/valuation.dcf_inputs/pipeline.yaml` |
| Package Version | `pipeline_equities/pyproject.toml` (currently `0.1.1`) |
| Deployed Wheel | `/Workspace/Users/la.long.n@outlook.com/.bundle/pipeline_equities/dev/artifacts/.internal/pipeline_equities-0.1.1-py3-none-any.whl` |

---

## Databricks CLI Commands Reference

```bash
# Check job status
databricks jobs get-run 909350286597450 -p DEFAULT -o json

# Get task error details
databricks jobs get-run-output <TASK_RUN_ID> -p DEFAULT -o json | jq -r '.error_trace'

# Check table existence
databricks tables get gold.market.prices_daily -p DEFAULT

# Check Delta history (find valid CDF versions)
databricks api post /api/2.0/sql/statements -p DEFAULT --json '{
  "warehouse_id": "63cd5138d461d093",
  "statement": "DESCRIBE HISTORY silver.massive.snapshot_all_tickers LIMIT 20",
  "wait_timeout": "50s"
}'

# Trigger new job run
databricks jobs run-now 259919585799043 -p DEFAULT --no-wait -o json

# Upload new wheel after changes
databricks workspace import "/Workspace/Users/la.long.n@outlook.com/.bundle/pipeline_equities/dev/artifacts/.internal/pipeline_equities-0.1.1-py3-none-any.whl" \
  --file dist/pipeline_equities-0.1.1-py3-none-any.whl \
  -p DEFAULT --format AUTO --overwrite
```

---

## Build & Deploy Workflow

```bash
# From pipeline_equities directory
cd /Users/longsman/Documents/sandbox_projects/dbricks/pipeline_equities

# Clean and rebuild
rm -rf dist build src/pipeline_equities.egg-info
uv build

# Upload to workspace
databricks workspace import \
  "/Workspace/Users/la.long.n@outlook.com/.bundle/pipeline_equities/dev/artifacts/.internal/pipeline_equities-0.1.1-py3-none-any.whl" \
  --file dist/pipeline_equities-0.1.1-py3-none-any.whl \
  -p DEFAULT --format AUTO --overwrite

# Trigger job
databricks jobs run-now 259919585799043 -p DEFAULT --no-wait -o json
```

**Note:** If changing wheel version, also update the job environment:
```bash
# Get current job config
databricks jobs get 259919585799043 -p DEFAULT -o json > /tmp/job_config.json

# Update dependencies array and apply
cat /tmp/job_config.json | jq '{job_id: .job_id, new_settings: .settings}' > /tmp/job_update.json
# Edit /tmp/job_update.json to change wheel version
databricks jobs update -p DEFAULT --json @/tmp/job_update.json
```

---

## Next Steps

1. **Immediate:** Implement batch backfill for `gold.market.prices_daily` (Option A above)
2. **Short-term:** Set appropriate VACUUM retention on source tables to prevent future CDF loss
3. **Verification:** Run full job and confirm all 27 tasks succeed

---

## Session Context

- **Skill Used:** `databricks-connect` (for CLI patterns and troubleshooting)
- **Key Discovery:** CDF files can exist in Delta history but be physically deleted by VACUUM
- **Framework Note:** `superwind` ExecSQL operator uses `data` as temp view name, not `__THIS__`
