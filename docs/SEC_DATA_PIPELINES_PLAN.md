# Implementation Plan: SEC Company Data Pipelines

## Problem Statement

The `dcf_valuation` pipeline currently relies on static CSV seed files for critical reference data:

1. **`cik_ticker.csv`** (~10,300 rows) - Maps CIK numbers to stock tickers
   - Problem: Stale data, missing new IPOs, ticker changes not reflected
   - Impact: Companies without ticker mappings can't get market prices for upside/downside calculations

2. **`gold.dim.company`** hardcodes `SIC = NULL` for all companies
   - Problem: The `sic_to_damodaran_industry` join fails for 100% of companies
   - Impact: ALL companies fall back to "Total Market" industry beta instead of sector-specific betas

These issues compound to cause poor coverage in `gold.dcf_results`.

## Proposed Solution

Replace static CSV files with live SEC API data:

| Data Need | Current Source | New Source |
|-----------|---------------|------------|
| CIK-ticker mapping | `cik_ticker.csv` (static) | `https://www.sec.gov/files/company_tickers.json` |
| SIC codes | Hardcoded NULL | `https://data.sec.gov/submissions/CIK*.json` |

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Submissions fetch strategy | All CIKs from company_tickers.json | Comprehensive coverage (~13k companies) |
| Ticker handling | Explode `tickers[]` array | Support multi-ticker companies (e.g., BRK-A/BRK-B) |
| Checkpoint strategy | Only fetch CIKs not in table | Minimize API calls after initial load |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NEW BRONZE LAYER                                   │
│                                                                             │
│  ┌─────────────────────────────┐      ┌─────────────────────────────────┐  │
│  │ bronze.sec.company_tickers  │      │ bronze.sec.company_submissions  │  │
│  │                             │      │                                 │  │
│  │ Source: company_tickers.json│ ───► │ Source: submissions/CIK*.json   │  │
│  │ Mode: Batch (full refresh)  │      │ Mode: Batch (incremental)       │  │
│  │ ~13k rows                   │      │ Only fetches missing CIKs       │  │
│  └─────────────────────────────┘      └─────────────────────────────────┘  │
│              │                                     │                        │
└──────────────┼─────────────────────────────────────┼────────────────────────┘
               │                                     │
               ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MODIFIED GOLD LAYER                                │
│                                                                             │
│  ┌─────────────────────────────┐      ┌─────────────────────────────────┐  │
│  │ gold.dim.cik_ticker         │      │ gold.dim.company                │  │
│  │                             │      │                                 │  │
│  │ - Reads from bronze.sec.*   │      │ - Gets SIC from bronze.sec.*   │  │
│  │ - Explodes tickers[] array  │      │ - Enables industry beta lookup │  │
│  │ - Marks primary ticker      │      │ - Proper is_financial flag     │  │
│  └─────────────────────────────┘      └─────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Pipeline Specifications

### Pipeline 1: `bronze/sec.company_tickers/pipeline.yaml`

**Purpose:** Fetch all CIK-ticker mappings from SEC bulk file

| Attribute | Value |
|-----------|-------|
| Source | `https://www.sec.gov/files/company_tickers.json` |
| Mode | Batch (full refresh each run) |
| Output Table | `bronze.sec.company_tickers` |
| Estimated Rows | ~13,000 |

**SEC Response Structure:**
```json
{
  "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
  "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"}
}
```

**Pipeline Logic:**
1. Fetch JSON from SEC endpoint (requires User-Agent header)
2. Parse JSON object - each key maps to a company record
3. Extract `cik_str`, `ticker`, `title`
4. Zero-pad CIK to 10 digits (e.g., `320193` → `0000320193`)
5. Write to `bronze.sec.company_tickers` (overwrite mode)

**Output Schema:**
| Column | Type | Description |
|--------|------|-------------|
| `cik` | string | 10-digit zero-padded CIK |
| `ticker` | string | Stock ticker symbol |
| `company_name` | string | Company name |

**Implementation:**
```yaml
config:
  mode: batch

producer:
  variant: RESTProducer
  parameters:
    url: https://www.sec.gov/files/company_tickers.json
    method: GET
    headers:
      User-Agent: "Datsando datsando@outlook.com"

operators:
  - variant: WithColumns
    parameters:
      cols_map:
        content: cast(content as string)
        entries: from_json(content, 'map<string, struct<cik_str:long, ticker:string, title:string>>')
  
  - variant: Select
    parameters:
      cols:
        - explode(map_values(entries)) as entry
  
  - variant: Select
    parameters:
      cols:
        - lpad(cast(entry.cik_str as string), 10, '0') as cik
        - entry.ticker as ticker
        - entry.title as company_name

consumer:
  variant: WriteTable
  parameters:
    table: bronze.sec.company_tickers
    mode: overwrite
```

---

### Pipeline 2: `bronze/sec.company_submissions/pipeline.yaml`

**Purpose:** Fetch company metadata (SIC codes, all tickers, exchanges) per CIK

| Attribute | Value |
|-----------|-------|
| Source | `https://data.sec.gov/submissions/CIK{cik}.json` |
| Mode | Batch (incremental - only missing CIKs) |
| Output Table | `bronze.sec.company_submissions` |
| Initial Load | ~13,000 API calls |
| Subsequent Runs | Only new CIKs (typically 0-50) |

**SEC Response Structure (key fields):**
```json
{
  "cik": "0000320193",
  "sic": "3571",
  "sicDescription": "Electronic Computers",
  "name": "Apple Inc.",
  "tickers": ["AAPL"],
  "exchanges": ["Nasdaq"],
  "fiscalYearEnd": "0926",
  "stateOfIncorporation": "CA",
  "category": "Large accelerated filer"
}
```

**Pipeline Logic:**
1. Query `bronze.sec.company_tickers` for all CIKs
2. Left join to `bronze.sec.company_submissions` to find missing CIKs
3. For each missing CIK, fetch `submissions/CIK{cik}.json`
4. Parse metadata fields (sic, tickers array, exchanges array, etc.)
5. Merge into `bronze.sec.company_submissions`

**Output Schema:**
| Column | Type | Description |
|--------|------|-------------|
| `cik` | string | 10-digit zero-padded CIK |
| `sic` | string | 4-digit SIC code |
| `sic_description` | string | Industry description |
| `entity_name` | string | Company name |
| `entity_type` | string | "operating", "shell", etc. |
| `tickers` | array&lt;string&gt; | All ticker symbols for this CIK |
| `exchanges` | array&lt;string&gt; | Exchange for each ticker (parallel array) |
| `fiscal_year_end` | string | MMDD format |
| `state_of_incorporation` | string | State code |
| `category` | string | "Large accelerated filer", etc. |
| `ein` | string | Employer ID number |

**Implementation:**
```yaml
config:
  mode: batch

producer:
  variant: ExecSQL
  parameters:
    sql_query: |
      select ct.cik
      from bronze.sec.company_tickers ct
      left join bronze.sec.company_submissions cs on ct.cik = cs.cik
      where cs.cik is null

operators:
  - variant: RESTOperator
    parameters:
      url: https://data.sec.gov/submissions/CIK{cik}.json
      method: GET
      source_col: cik
      param_name_for_value: cik
      param_location: path
      ignore_error_codes: [404]
      headers:
        User-Agent: "Datsando datsando@outlook.com"

  - variant: Filter
    parameters:
      condition: content is not null

  - variant: WithColumns
    parameters:
      cols_map:
        sic: get_json_object(content, '$.sic')
        sic_description: get_json_object(content, '$.sicDescription')
        entity_name: get_json_object(content, '$.name')
        entity_type: get_json_object(content, '$.entityType')
        tickers_json: get_json_object(content, '$.tickers')
        exchanges_json: get_json_object(content, '$.exchanges')
        fiscal_year_end: get_json_object(content, '$.fiscalYearEnd')
        state_of_incorporation: get_json_object(content, '$.stateOfIncorporation')
        category: get_json_object(content, '$.category')
        ein: get_json_object(content, '$.ein')

  - variant: WithColumns
    parameters:
      cols_map:
        tickers: from_json(tickers_json, 'array<string>')
        exchanges: from_json(exchanges_json, 'array<string>')

  - variant: Select
    parameters:
      cols:
        - cik
        - sic
        - sic_description
        - entity_name
        - entity_type
        - tickers
        - exchanges
        - fiscal_year_end
        - state_of_incorporation
        - category
        - ein

consumer:
  variant: MergeTable
  parameters:
    table: bronze.sec.company_submissions
    key_columns: [cik]
```

---

### Pipeline 3: `gold/dim.cik_ticker/pipeline.yaml` (Modified)

**Purpose:** Create CIK-ticker mapping by exploding `tickers[]` array from submissions

**Current Implementation:** Reads from static `cik_ticker.csv`

**New Implementation:**
```yaml
config:
  mode: batch

producer:
  variant: ExecSQL
  parameters:
    sql_query: |
      with exploded as (
        select
          cik,
          posexplode(tickers) as (ticker_idx, ticker),
          exchanges
        from bronze.sec.company_submissions
        where tickers is not null and size(tickers) > 0
      ),
      with_exchange as (
        select
          cik,
          ticker,
          ticker_idx,
          case 
            when exchanges is not null and size(exchanges) > ticker_idx 
            then exchanges[ticker_idx]
            else null
          end as exchange
        from exploded
      )
      select
        cik,
        ticker,
        exchange,
        ticker_idx = 0 as is_primary
      from with_exchange

consumer:
  variant: MergeTable
  parameters:
    table: gold.dim.cik_ticker
    key_columns: [cik, ticker]
```

**Schema Change:**
| Column | Old | New |
|--------|-----|-----|
| `cik` | string | string (unchanged) |
| `ticker` | string | string (unchanged) |
| `is_primary` | boolean | boolean (unchanged) |
| `exchange` | N/A | string (NEW) |

---

### Pipeline 4: `gold/dim.company/pipeline.yaml` (Modified)

**Purpose:** Populate SIC codes from SEC submissions instead of hardcoding NULL

**Current Implementation:** `cast(null as int) as sic`

**New Implementation:**
```yaml
config:
  mode: batch

producer:
  variant: ExecSQL
  parameters:
    sql_query: |
      with latest_facts as (
        select cik, max(filed) as latest_filed
        from silver.edgar.company_facts
        where taxonomy = 'dei' and tag = 'EntityRegistrantName'
        group by cik
      ),
      entity_names as (
        select cf.cik, first(cf.val) as entity_name
        from silver.edgar.company_facts cf
        inner join latest_facts lf on cf.cik = lf.cik and cf.filed = lf.latest_filed
        where cf.taxonomy = 'dei' and cf.tag = 'EntityRegistrantName'
        group by cf.cik
      ),
      sic_data as (
        select
          cik,
          cast(sic as int) as sic,
          sic_description,
          fiscal_year_end,
          state_of_incorporation,
          category
        from bronze.sec.company_submissions
      )
      select
        en.cik,
        coalesce(sd.entity_name, en.entity_name) as entity_name,
        sd.sic,
        sd.sic_description,
        case 
          when sd.sic >= 6000 and sd.sic < 7000 then true
          else false
        end as is_financial,
        case
          when sd.sic >= 6000 and sd.sic < 6100 then 'depository'
          when sd.sic >= 6100 and sd.sic < 6200 then 'nondepository_credit'
          when sd.sic >= 6200 and sd.sic < 6300 then 'securities_commodities'
          when sd.sic >= 6300 and sd.sic < 6400 then 'insurance_carriers'
          when sd.sic >= 6400 and sd.sic < 6500 then 'insurance_agents'
          when sd.sic >= 6500 and sd.sic < 6600 then 'real_estate'
          when sd.sic >= 6700 and sd.sic < 7000 then 'holding_investment'
          else null
        end as financial_class,
        sd.fiscal_year_end,
        sd.state_of_incorporation,
        sd.category
      from entity_names en
      left join sic_data sd on en.cik = sd.cik

consumer:
  variant: MergeTable
  parameters:
    table: gold.dim.company
    key_columns: [cik]
```

**Schema Changes:**
| Column | Old | New |
|--------|-----|-----|
| `sic` | Always NULL | Populated from SEC |
| `sic_description` | N/A | NEW |
| `fiscal_year_end` | N/A | NEW |
| `state_of_incorporation` | N/A | NEW |
| `category` | N/A | NEW |

---

## Job DAG Updates

### New Tasks for `dcf_valuation_dev.job.yaml`

```yaml
# ===========================================
# Bronze layer: SEC reference data (NEW)
# ===========================================
- <<: *task_defaults
  task_key: bronze-sec-company_tickers
  python_wheel_task:
    <<: *python_wheel_task_defaults
    named_parameters:
      from_package: ${var.from_package}
      yaml_file: bronze/sec.company_tickers/pipeline.yaml

- <<: *task_defaults
  task_key: bronze-sec-company_submissions
  depends_on:
    - task_key: bronze-sec-company_tickers
  python_wheel_task:
    <<: *python_wheel_task_defaults
    named_parameters:
      from_package: ${var.from_package}
      yaml_file: bronze/sec.company_submissions/pipeline.yaml
```

### Modified Task Dependencies

```yaml
# gold-dim-cik_ticker: Change from CSV to SEC data
- <<: *task_defaults
  task_key: gold-dim-cik_ticker
  depends_on:
    - task_key: bronze-sec-company_submissions  # CHANGED from silver-massive-snapshot_all_tickers
  python_wheel_task:
    ...

# gold-dim-company: Add SEC submissions dependency
- <<: *task_defaults
  task_key: gold-dim-company
  depends_on:
    - task_key: bronze-sec-company_submissions  # NEW
  python_wheel_task:
    ...
```

### Updated DAG Flow

```
                    bronze-sec-company_tickers (batch, ~13k rows)
                                │
                                ▼
                    bronze-sec-company_submissions (incremental)
                           │         │
              ┌────────────┘         └────────────┐
              ▼                                   ▼
    gold-dim-cik_ticker                   gold-dim-company
    (explode tickers[])                   (join for SIC codes)
              │                                   │
              │                                   ▼
              │                     gold-dim-sic_to_damodaran_industry (existing)
              │                                   │
              └───────────────┬───────────────────┘
                              ▼
                    gold-valuation-dcf_inputs
                    (now gets real industry betas!)
                              │
                              ▼
                    gold-valuation-dcf_cashflows
                              │
                              ▼
                    gold-valuation-dcf_results
```

---

## Files Summary

### New Files to Create

| Path | Purpose |
|------|---------|
| `src/dcf_valuation/assets/bronze/sec.company_tickers/pipeline.yaml` | Fetch bulk ticker file |
| `src/dcf_valuation/assets/bronze/sec.company_submissions/pipeline.yaml` | Fetch submissions per CIK |

### Files to Modify

| Path | Changes |
|------|---------|
| `src/dcf_valuation/assets/gold/dim.cik_ticker/pipeline.yaml` | Read from bronze.sec, explode tickers[] |
| `src/dcf_valuation/assets/gold/dim.company/pipeline.yaml` | Join to bronze.sec for SIC codes |
| `resources/dcf_valuation_dev.job.yaml` | Add 2 bronze tasks, update dependencies |
| `resources/dcf_valuation.job.yaml` | Same changes for PRD job |

### Files to Deprecate (Keep as Backup)

| Path | Notes |
|------|-------|
| `src/dcf_valuation/assets/gold/seed/dim/cik_ticker.csv` | No longer loaded, keep for reference |

---

## Risk Assessment

### SEC API Rate Limits

- SEC allows ~10 requests/second
- Initial load: ~13k requests for submissions
- Risk: May hit rate limits, causing 403 errors
- Mitigation: RESTOperator should handle retries; may need throttling

### Initial Run Duration

- `bronze-sec-company_submissions` initial run: ~20-30 minutes (13k API calls)
- Subsequent runs: seconds (only new CIKs)
- Risk: Job timeout if not configured properly
- Mitigation: Ensure job timeout is sufficient; task runs independently

### Schema Evolution

- `gold.dim.company` gets new columns
- `gold.dim.cik_ticker` gets new `exchange` column
- Risk: Downstream queries may need updates
- Mitigation: New columns are additive; existing queries unaffected

### Data Quality

- SEC `tickers[]` array may be empty for some companies
- SIC codes may be missing for foreign filers
- Risk: Some companies won't have mappings
- Mitigation: Use COALESCE/fallbacks in downstream queries

---

## Expected Outcomes

| Metric | Before | After |
|--------|--------|-------|
| CIK-ticker mappings | ~10,300 (static CSV) | ~13,000+ (live SEC) |
| SIC codes populated | 0% (all NULL) | ~95%+ of filing companies |
| "Total Market" beta fallback | 100% of companies | Only unmapped SIC codes |
| Industry-specific beta coverage | 0% | ~90%+ |
| `has_minimum_inputs` pass rate | Low | Significantly higher |
| `gold.dcf_results` ticker count | Few | Many more |

---

## Testing Plan

1. **Unit test bronze pipelines locally** (if Databricks Connect available)
2. **Deploy to dev and run bronze tasks only** - verify data quality
3. **Run gold tasks** - verify joins work correctly
4. **Compare before/after** - count distinct tickers in `dcf_results`
5. **Spot check** - verify SIC codes for known companies (AAPL=3571, JPM=6021)

---

## Rollback Plan

If issues arise:
1. Revert `gold.dim.cik_ticker` to read from CSV
2. Revert `gold.dim.company` to hardcode NULL SIC
3. Remove bronze-sec tasks from job YAML
4. CSV files are still present as backup
