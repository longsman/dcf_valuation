# DCF Pipeline Enhancement Plan

## Executive Summary

This plan addresses 4 enhancements to the DCF valuation pipeline:

1. **TODO 1:** Wire up `market_price` from `gold.market.prices_daily`
2. **TODO 2:** Calculate `shares_basic_latest` from SEC filings
3. **TODO 3:** Compute `value_per_share` and `upside_downside` in dcf_results
4. **TODO 4:** Replace fixed 5% growth with actual YoY revenue growth

**Key Decision:** Due to streaming pipeline limitations and the existing data backfill scenario, we will implement this as a **hybrid approach**:
- Modify the pipeline YAML for future streaming data
- Run a one-time SQL backfill for existing dcf_inputs rows

---

## Critical Issues Addressed (from Plan Review)

| Issue | Severity | Resolution |
|-------|----------|------------|
| Backfill strategy not addressed | BLOCKER | Added Phase 2A for SQL backfill of existing rows |
| cik_ticker duplicate handling | BLOCKER | Use ROW_NUMBER() to pick single ticker per CIK |
| flow_ttm empty for backfilled companies | MAJOR | Use company_facts directly for growth calc, not flow_ttm |
| Shares date boundary missing | MAJOR | Add `cf.end <= as_of_period_end` constraint |
| Column propagation unclear | MAJOR | Explicit final SELECT replacement shown |

---

## Pre-Requisites

Before executing this plan, verify:

```bash
# Working directory
cd /Users/longsman/Documents/sandbox_projects/dbricks

# Verify git status is clean
git status

# Verify target file exists
ls -la pipeline_equities/src/pipeline_equities/assets/gold/valuation.dcf_inputs/pipeline.yaml
```

### Key File Paths
- **dcf_inputs pipeline:** `pipeline_equities/src/pipeline_equities/assets/gold/valuation.dcf_inputs/pipeline.yaml`
- **dcf_results pipeline:** `pipeline_equities/src/pipeline_equities/assets/gold/valuation.dcf_results/pipeline.yaml`

### Databricks CLI Commands Reference
```bash
# SQL execution
databricks api post /api/2.0/sql/statements -p DEFAULT --json '{
  "warehouse_id": "63cd5138d461d093",
  "statement": "<SQL>",
  "wait_timeout": "50s"
}'

# Bundle deployment
cd pipeline_equities && databricks bundle deploy -p DEFAULT

# Run job
databricks jobs run-now 865126695759134 -p DEFAULT --no-wait
```

---

## Phase 0: Pre-flight Verification

### P0-01: Verify Data Availability

Run this SQL to confirm source data exists:

```sql
SELECT 
  (SELECT COUNT(*) FROM gold.dim.cik_ticker WHERE is_primary = true) as cik_ticker_primary_count,
  (SELECT COUNT(DISTINCT ticker) FROM gold.market.prices_daily 
   WHERE price_date >= current_date() - interval 7 days) as recent_prices_count,
  (SELECT COUNT(*) FROM gold.financials.tag_map WHERE line_item = 'shares_basic') as shares_tags_count,
  (SELECT COUNT(DISTINCT cik) FROM gold.valuation.dcf_inputs WHERE has_minimum_inputs = true) as dcf_inputs_count
```

**Expected:** All counts > 0

### P0-02: Check for Duplicate Primary Tickers

```sql
SELECT cik, COUNT(*) as cnt 
FROM gold.dim.cik_ticker 
WHERE is_primary = true 
GROUP BY cik 
HAVING COUNT(*) > 1
LIMIT 10
```

**Expected:** No rows returned (if rows exist, plan handles via ROW_NUMBER)

### P0-03: Test Market Price Join for Known Company (AAPL)

```sql
SELECT ct.cik, ct.ticker, mp.price_date, mp.close 
FROM gold.dim.cik_ticker ct 
LEFT JOIN (
  SELECT ticker, price_date, close,
    ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY price_date DESC) as rn
  FROM gold.market.prices_daily 
  WHERE price_date >= current_date() - interval 7 days
) mp ON ct.ticker = mp.ticker AND mp.rn = 1
WHERE ct.cik = '0000320193' AND ct.is_primary = true
```

**Expected:** Row with ticker='AAPL', recent close price

### P0-04: Test Shares Lookup for Known Company (AAPL)

```sql
SELECT cf.cik, cf.tag, cf.val as shares, cf.end as shares_date
FROM silver.edgar.company_facts cf
INNER JOIN gold.financials.tag_map tm 
  ON cf.taxonomy = tm.source_taxonomy AND cf.tag = tm.source_tag
WHERE tm.line_item = 'shares_basic'
  AND cf.cik = '0000320193'
  AND cf.unit_of_measure = 'shares'
  AND cf.val > 0
ORDER BY cf.end DESC
LIMIT 3
```

**Expected:** Shares in ~15B range for AAPL

### P0-05: Test Revenue Growth Calculation (Using company_facts directly)

```sql
WITH annual_revenue AS (
  SELECT cf.cik, cf.fy, cf.val as revenue,
    ROW_NUMBER() OVER (PARTITION BY cf.cik, cf.fy ORDER BY cf.end DESC, cf.filed DESC) as rn
  FROM silver.edgar.company_facts cf
  INNER JOIN gold.financials.tag_map tm ON cf.taxonomy = tm.source_taxonomy AND cf.tag = tm.source_tag
  WHERE cf.cik = '0000320193'
    AND tm.line_item = 'revenue'
    AND cf.fp = 'FY'
    AND cf.unit_of_measure = 'USD'
),
deduped AS (SELECT cik, fy, revenue FROM annual_revenue WHERE rn = 1),
with_growth AS (
  SELECT cik, fy, revenue, 
    LAG(revenue) OVER (PARTITION BY cik ORDER BY fy) as prev_revenue,
    (revenue - LAG(revenue) OVER (PARTITION BY cik ORDER BY fy)) / 
      NULLIF(LAG(revenue) OVER (PARTITION BY cik ORDER BY fy), 0) as yoy_growth
  FROM deduped
)
SELECT * FROM with_growth WHERE fy >= 2022 ORDER BY fy DESC
```

**Expected:** YoY growth values for AAPL (e.g., 2-10% range)

---

## Phase 1: Modify dcf_inputs Pipeline YAML

### P1-01: Read Current Pipeline State

```bash
# Note the current line numbers for NULL placeholders
grep -n "cast(null as" pipeline_equities/src/pipeline_equities/assets/gold/valuation.dcf_inputs/pipeline.yaml

# Note the growth_initial placeholder
grep -n "growth_initial" pipeline_equities/src/pipeline_equities/assets/gold/valuation.dcf_inputs/pipeline.yaml
```

### P1-02: Add New CTEs After `with_wc`

Insert the following CTEs after `with_wc` and before `rf_rate` (approximately line 120):

```sql
        -- TODO 1: Get market price via ticker mapping
        with_market_price as (
          select
            wwc.*,
            ct.ticker as ticker_primary_lookup,
            mp.price_date as market_price_date_lookup,
            mp.close as market_price_lookup,
            case 
              when mp.close is not null then 'ticker_lookup'
              else null
            end as market_price_method_lookup
          from with_wc wwc
          left join (
            -- Handle duplicate is_primary entries by picking first alphabetically
            select cik, ticker,
              row_number() over (partition by cik order by ticker) as rn
            from gold.dim.cik_ticker 
            where is_primary = true
          ) ct on wwc.cik = ct.cik and ct.rn = 1
          left join (
            select ticker, price_date, close,
              row_number() over (partition by ticker order by price_date desc) as rn
            from gold.market.prices_daily
            where price_date >= current_date() - interval 7 days
          ) mp on ct.ticker = mp.ticker and mp.rn = 1
        ),
        -- TODO 2: Get latest shares outstanding (with date boundary)
        with_shares as (
          select
            wmp.*,
            sh.val as shares_basic_latest_lookup
          from with_market_price wmp
          left join (
            select cf.cik, cf.val, cf.end as shares_date,
              row_number() over (
                partition by cf.cik 
                order by cf.end desc, tm.priority asc
              ) as rn
            from silver.edgar.company_facts cf
            inner join gold.financials.tag_map tm
              on cf.taxonomy = tm.source_taxonomy
              and cf.tag = tm.source_tag
            where tm.line_item = 'shares_basic'
              and cf.unit_of_measure = 'shares'
              and cf.val > 0
          ) sh on wmp.cik = sh.cik 
            and sh.rn = 1
            and sh.shares_date <= wmp.as_of_period_end  -- Prevent look-ahead bias
        ),
        -- TODO 4: Calculate YoY revenue growth from company_facts (not flow_ttm)
        with_growth as (
          select
            ws.*,
            rev_growth.yoy_growth as revenue_yoy_growth,
            case 
              when rev_growth.yoy_growth is not null
              then least(greatest(rev_growth.yoy_growth, -0.20), 0.50)  -- Bound [-20%, +50%]
              else 0.05  -- Default fallback
            end as growth_initial_calc,
            case 
              when rev_growth.yoy_growth is not null then 'revenue_yoy'
              else 'default'
            end as growth_method
          from with_shares ws
          left join (
            -- Calculate YoY growth from annual revenue
            select 
              cik,
              fy,
              revenue,
              prev_revenue,
              (revenue - prev_revenue) / nullif(prev_revenue, 0) as yoy_growth
            from (
              select 
                cik, fy, revenue,
                lag(revenue) over (partition by cik order by fy) as prev_revenue
              from (
                select cf.cik, cf.fy, cf.val as revenue,
                  row_number() over (partition by cf.cik, cf.fy order by cf.end desc, tm.priority asc) as rn
                from silver.edgar.company_facts cf
                inner join gold.financials.tag_map tm 
                  on cf.taxonomy = tm.source_taxonomy and cf.tag = tm.source_tag
                where tm.line_item = 'revenue'
                  and cf.fp = 'FY'
                  and cf.unit_of_measure = 'USD'
                  and cf.val > 0
              ) where rn = 1
            )
          ) rev_growth on ws.cik = rev_growth.cik 
            and rev_growth.fy = year(ws.as_of_period_end)  -- Match fiscal year
        ),
```

### P1-03: Update `with_params` CTE to Read from `with_growth`

Find the `with_params` CTE (around line 140-155) and change:

**FROM:**
```sql
        with_params as (
          select
            wwc.*,
```

**TO:**
```sql
        with_params as (
          select
            wg.*,
```

And update the `from` clause:

**FROM:**
```sql
          from with_wc wwc
```

**TO:**
```sql
          from with_growth wg
```

### P1-04: Replace NULL Placeholders in Final SELECT

Find lines ~264-269 and replace:

**FROM:**
```sql
          cast(null as string) as ticker_primary,
          cast(null as date) as market_price_date,
          cast(null as double) as market_price,
          cast(null as string) as market_price_method,
          cast(null as double) as shares_basic_latest,
          cast(null as double) as market_cap,
```

**TO:**
```sql
          ticker_primary_lookup as ticker_primary,
          market_price_date_lookup as market_price_date,
          cast(market_price_lookup as double) as market_price,
          market_price_method_lookup as market_price_method,
          shares_basic_latest_lookup as shares_basic_latest,
          cast(market_price_lookup as double) * shares_basic_latest_lookup as market_cap,
```

### P1-05: Replace Fixed growth_initial

Find line ~234 and replace:

**FROM:**
```sql
            0.05 as growth_initial  -- placeholder, will enhance with actual YoY calc
```

**TO:**
```sql
            growth_initial_calc as growth_initial  -- YoY revenue growth, bounded [-20%, +50%]
```

### P1-06: Add Quality Flags

Find the `quality_flags` array (around line 322-328) and add these cases inside the `array_compact(array(...))`:

```sql
            case when ticker_primary_lookup is null then 'no_ticker_mapping' end,
            case when ticker_primary_lookup is not null and market_price_lookup is null then 'no_recent_price' end,
            case when market_price_date_lookup < current_date() - interval 3 days then 'market_price_stale' end,
            case when shares_basic_latest_lookup is null then 'shares_unavailable' end,
            case when growth_method = 'default' then 'growth_default_used' end,
            case when revenue_yoy_growth is not null and revenue_yoy_growth > 0.50 then 'growth_capped_high' end,
            case when revenue_yoy_growth is not null and revenue_yoy_growth < -0.20 then 'growth_capped_low' end,
```

### P1-07: Validate Bundle

```bash
cd /Users/longsman/Documents/sandbox_projects/dbricks/pipeline_equities && databricks bundle validate -p DEFAULT
```

**Expected:** Validation passes without errors

---

## Phase 2: Backfill Existing Data

### Why This Is Needed

The streaming pipeline only processes new filing_events via CDF. Existing rows in `gold.valuation.dcf_inputs` (including our AAPL/AMZN/META/JPM backfill) won't be updated automatically. We need to run a one-time UPDATE.

### P2-01: Backfill Market Price, Shares, and Growth for Existing Rows

```sql
-- Run via databricks api post with warehouse_id: 63cd5138d461d093

MERGE INTO gold.valuation.dcf_inputs AS target
USING (
  WITH ticker_lookup AS (
    SELECT cik, ticker,
      ROW_NUMBER() OVER (PARTITION BY cik ORDER BY ticker) as rn
    FROM gold.dim.cik_ticker 
    WHERE is_primary = true
  ),
  price_lookup AS (
    SELECT ticker, price_date, close,
      ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY price_date DESC) as rn
    FROM gold.market.prices_daily
    WHERE price_date >= current_date() - interval 7 days
  ),
  shares_lookup AS (
    SELECT cf.cik, cf.val as shares, cf.end as shares_date,
      ROW_NUMBER() OVER (PARTITION BY cf.cik ORDER BY cf.end DESC, tm.priority ASC) as rn
    FROM silver.edgar.company_facts cf
    INNER JOIN gold.financials.tag_map tm 
      ON cf.taxonomy = tm.source_taxonomy AND cf.tag = tm.source_tag
    WHERE tm.line_item = 'shares_basic'
      AND cf.unit_of_measure = 'shares'
      AND cf.val > 0
  ),
  growth_lookup AS (
    SELECT cik, fy,
      (revenue - prev_revenue) / NULLIF(prev_revenue, 0) as yoy_growth
    FROM (
      SELECT cik, fy, revenue,
        LAG(revenue) OVER (PARTITION BY cik ORDER BY fy) as prev_revenue
      FROM (
        SELECT cf.cik, cf.fy, cf.val as revenue,
          ROW_NUMBER() OVER (PARTITION BY cf.cik, cf.fy ORDER BY cf.end DESC, tm.priority ASC) as rn
        FROM silver.edgar.company_facts cf
        INNER JOIN gold.financials.tag_map tm 
          ON cf.taxonomy = tm.source_taxonomy AND cf.tag = tm.source_tag
        WHERE tm.line_item = 'revenue' AND cf.fp = 'FY' 
          AND cf.unit_of_measure = 'USD' AND cf.val > 0
      ) WHERE rn = 1
    )
  ),
  enriched AS (
    SELECT 
      i.cik,
      i.valuation_date,
      i.assumption_set_id,
      i.source_accn,
      i.model_type,
      t.ticker as ticker_primary_new,
      p.price_date as market_price_date_new,
      p.close as market_price_new,
      CASE WHEN p.close IS NOT NULL THEN 'ticker_lookup' END as market_price_method_new,
      s.shares as shares_basic_latest_new,
      p.close * s.shares as market_cap_new,
      CASE 
        WHEN g.yoy_growth IS NOT NULL 
        THEN LEAST(GREATEST(g.yoy_growth, -0.20), 0.50)
        ELSE 0.05
      END as growth_initial_new
    FROM gold.valuation.dcf_inputs i
    LEFT JOIN ticker_lookup t ON i.cik = t.cik AND t.rn = 1
    LEFT JOIN price_lookup p ON t.ticker = p.ticker AND p.rn = 1
    LEFT JOIN shares_lookup s ON i.cik = s.cik AND s.rn = 1 
      AND s.shares_date <= i.as_of_period_end
    LEFT JOIN growth_lookup g ON i.cik = g.cik AND g.fy = YEAR(i.as_of_period_end)
  )
  SELECT * FROM enriched
) AS source
ON target.cik = source.cik 
  AND target.valuation_date = source.valuation_date
  AND target.assumption_set_id = source.assumption_set_id
  AND target.source_accn = source.source_accn
  AND target.model_type = source.model_type
WHEN MATCHED THEN UPDATE SET
  ticker_primary = source.ticker_primary_new,
  market_price_date = source.market_price_date_new,
  market_price = source.market_price_new,
  market_price_method = source.market_price_method_new,
  shares_basic_latest = source.shares_basic_latest_new,
  market_cap = source.market_cap_new,
  growth_initial = source.growth_initial_new
```

### P2-02: Verify Backfill Results

```sql
SELECT 
  COUNT(*) as total,
  COUNT(market_price) as with_price,
  COUNT(shares_basic_latest) as with_shares,
  SUM(CASE WHEN growth_initial != 0.05 THEN 1 ELSE 0 END) as with_real_growth,
  ROUND(COUNT(market_price) * 100.0 / COUNT(*), 1) as price_pct,
  ROUND(COUNT(shares_basic_latest) * 100.0 / COUNT(*), 1) as shares_pct
FROM gold.valuation.dcf_inputs
```

**Expected:** price_pct > 50%, shares_pct > 50%

---

## Phase 3: Deploy and Run Pipeline

### P3-01: Deploy Bundle

```bash
cd /Users/longsman/Documents/sandbox_projects/dbricks/pipeline_equities
databricks bundle deploy -p DEFAULT
```

### P3-02: Run Full Job

```bash
databricks jobs run-now 865126695759134 -p DEFAULT --no-wait -o json
```

Note the `run_id` from the output.

### P3-03: Monitor Job Completion

```bash
# Replace RUN_ID with actual value
databricks jobs get-run <RUN_ID> -p DEFAULT -o json | jq '.state'
```

Wait for `life_cycle_state: TERMINATED` and `result_state: SUCCESS`.

---

## Phase 4: Validate Results

### P4-01: Verify dcf_results Has value_per_share

```sql
SELECT 
  COUNT(*) as total,
  COUNT(value_per_share) as with_vps,
  COUNT(upside_downside) as with_updown
FROM gold.valuation.dcf_results
WHERE equity_value > 0
```

**Expected:** with_vps > 0, with_updown > 0

### P4-02: Spot-Check AAPL

```sql
SELECT 
  i.cik,
  i.ticker_primary,
  i.market_price,
  i.shares_basic_latest,
  i.market_cap,
  i.growth_initial,
  r.equity_value,
  r.value_per_share,
  r.upside_downside
FROM gold.valuation.dcf_inputs i
JOIN gold.valuation.dcf_results r 
  ON i.cik = r.cik 
  AND i.valuation_date = r.valuation_date 
  AND i.assumption_set_id = r.assumption_set_id
WHERE i.cik = '0000320193'
  AND i.assumption_set_id = 'damodaran_v1'
ORDER BY i.valuation_date DESC
LIMIT 1
```

**Expected:**
- ticker_primary = 'AAPL'
- market_price > 200
- shares_basic_latest in billions (~15B)
- market_cap in trillions
- growth_initial = actual YoY (likely 2-10%, not 5%)
- value_per_share > 0
- upside_downside is a percentage

### P4-03: Summary of All Target Tickers

```sql
SELECT 
  t.ticker,
  i.cik,
  i.market_price,
  i.shares_basic_latest,
  i.growth_initial,
  r.value_per_share,
  r.upside_downside,
  ROUND(r.upside_downside * 100, 1) as upside_pct
FROM gold.valuation.dcf_inputs i
JOIN gold.valuation.dcf_results r 
  ON i.cik = r.cik 
  AND i.valuation_date = r.valuation_date 
  AND i.assumption_set_id = r.assumption_set_id
LEFT JOIN gold.dim.cik_ticker t ON i.cik = t.cik AND t.is_primary = true
WHERE i.cik IN ('0000320193', '0001018724', '0001326801', '0000019617')
  AND i.assumption_set_id = 'damodaran_v1'
ORDER BY t.ticker
```

---

## Rollback Procedures

### Rollback Pipeline Code

```bash
cd /Users/longsman/Documents/sandbox_projects/dbricks
git checkout -- pipeline_equities/src/pipeline_equities/assets/gold/valuation.dcf_inputs/pipeline.yaml
cd pipeline_equities && databricks bundle deploy -p DEFAULT
```

### Rollback Data (Reset to NULL)

```sql
UPDATE gold.valuation.dcf_inputs
SET 
  ticker_primary = NULL,
  market_price_date = NULL,
  market_price = NULL,
  market_price_method = NULL,
  shares_basic_latest = NULL,
  market_cap = NULL,
  growth_initial = 0.05
WHERE cik IN ('0000320193', '0001018724', '0001326801', '0000019617')
```

---

## Success Criteria

| Metric | Target | Verification Query |
|--------|--------|-------------------|
| market_price coverage | ≥50% of has_minimum_inputs rows | P2-02 |
| shares_basic_latest coverage | ≥50% of has_minimum_inputs rows | P2-02 |
| Real growth_initial | ≥50% != 0.05 | P2-02 |
| value_per_share populated | >0 for rows with equity_value>0 | P4-01 |
| upside_downside populated | >0 for rows with market_price>0 | P4-01 |
| AAPL spot-check | All fields non-NULL | P4-02 |

---

## Appendix: Key Design Decisions

### Why Use company_facts Directly for Growth (Not flow_ttm)?

The `gold.financials.flow_ttm` table is populated via streaming from `statement_lines`, which itself streams from `filing_events`. For backfilled companies (AAPL, AMZN, META, JPM), this table is empty because they bypassed the normal streaming flow.

Using `silver.edgar.company_facts` directly ensures growth calculation works for all companies regardless of how they entered the system.

### Why [-20%, +50%] Growth Bounds?

- **-20% floor:** Prevents extreme negative growth from producing unrealistic valuations (mature companies rarely shrink >20% YoY sustainably)
- **+50% cap:** Prevents hypergrowth outliers from dominating terminal value (50% growth fading to 4% over 10 years is already aggressive)

These can be made configurable in future versions via `gold.valuation.assumption_sets`.

### Why 7-Day Price Lookback?

- Covers weekends (2 days) and typical market holidays (1-2 days)
- Longer lookbacks risk using stale prices
- Shorter lookbacks may miss prices during long holiday periods

Consider making this configurable or using a trading calendar in future versions.
