# Databricks notebook source
# MAGIC %md
# MAGIC # DCF Inputs Backfill for AAPL, AMZN, META, JPM
# MAGIC
# MAGIC This notebook backfills `gold.valuation.dcf_inputs` for specific tickers that were missed
# MAGIC by the streaming pipeline due to checkpoint timing.
# MAGIC
# MAGIC ## TTM Estimation Heuristic
# MAGIC
# MAGIC For flow items (revenue, EBIT, etc.), we need Trailing Twelve Months (TTM) values.
# MAGIC The heuristic prioritizes data quality in this order:
# MAGIC
# MAGIC 1. **Best: Sum of 4 consecutive quarters** - Most accurate when all Q1-Q4 data available
# MAGIC 2. **Good: FY (annual) value** - Direct from 10-K filings, no interpolation needed
# MAGIC 3. **Acceptable: Latest quarter × 4** - Annualized quarterly (may miss seasonality)
# MAGIC 4. **Fallback: Most recent 3Q × 4/3** - Interpolated from partial year data
# MAGIC
# MAGIC The notebook tracks which method was used via `quality_flags`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# Target CIKs for backfill
TARGET_CIKS = [
    "0000320193",  # AAPL
    "0001018724",  # AMZN
    "0001326801",  # META
    "0000019617",  # JPM
]

# Both assumption sets
ASSUMPTION_SETS = ["damodaran_v1", "damodaran_v1_conservative"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Validate Source Data Availability

# COMMAND ----------

# Check company_facts data exists
company_facts_check = spark.sql(f"""
    SELECT 
        cik,
        COUNT(*) as fact_count,
        COUNT(DISTINCT tag) as distinct_tags,
        MIN(filed) as earliest_filing,
        MAX(filed) as latest_filing
    FROM silver.edgar.company_facts 
    WHERE cik IN ({",".join([f"'{c}'" for c in TARGET_CIKS])})
      AND taxonomy IN ('us-gaap', 'dei')
    GROUP BY cik
    ORDER BY cik
""")
display(company_facts_check)

# COMMAND ----------

# Check latest filings for each target company
latest_filings = spark.sql(f"""
    SELECT 
        cik,
        accession_number,
        form_type,
        filed_date,
        title
    FROM silver.edgar.filings_rss
    WHERE cik IN ({",".join([f"'{c}'" for c in TARGET_CIKS])})
      AND form_type IN ('10-K', '10-Q', '10-QT')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY cik ORDER BY filed_date DESC) = 1
    ORDER BY cik
""")
display(latest_filings)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Build TTM Flow Values with Robust Heuristic

# COMMAND ----------

# Create temp view of target CIKs
spark.sql(f"""
    CREATE OR REPLACE TEMP VIEW target_ciks AS
    SELECT cik FROM (VALUES {",".join([f"('{c}')" for c in TARGET_CIKS])}) AS t(cik)
""")

# COMMAND ----------

# Map company_facts to line_items using tag_map, then compute TTM
# This replicates the logic from flow_quarterly and flow_ttm pipelines

ttm_calculation_sql = """
-- Step 2a: Map raw facts to standardized line items
WITH facts_mapped AS (
    SELECT
        cf.cik,
        tm.line_item,
        cf.end as period_end,
        cf.start as period_start,
        cf.fy,
        cf.fp,
        cf.val,
        cf.filed,
        cf.accn,
        tm.is_flow,
        tm.priority,
        -- Calculate duration in months
        DATEDIFF(cf.end, cf.start) / 30.0 as duration_months_approx,
        -- Rank by priority and recency
        ROW_NUMBER() OVER (
            PARTITION BY cf.cik, tm.line_item, cf.end, cf.fp
            ORDER BY tm.priority ASC, cf.filed DESC, cf.accn DESC
        ) as selection_rank
    FROM silver.edgar.company_facts cf
    INNER JOIN gold.financials.tag_map tm 
        ON cf.taxonomy = tm.source_taxonomy 
        AND cf.tag = tm.source_tag
    INNER JOIN target_ciks tc ON cf.cik = tc.cik
    WHERE cf.unit_of_measure = 'USD'
),

-- Step 2b: Select best fact per (cik, line_item, period_end, fp)
best_facts AS (
    SELECT * FROM facts_mapped WHERE selection_rank = 1
),

-- Step 2c: Identify the most recent reporting period per CIK
latest_periods AS (
    SELECT 
        cik,
        MAX(period_end) as latest_period_end,
        MAX(CASE WHEN fp = 'FY' THEN period_end END) as latest_fy_end,
        MAX(CASE WHEN fp IN ('Q1','Q2','Q3','Q4') THEN fy END) as latest_fy_year
    FROM best_facts
    WHERE is_flow = true
    GROUP BY cik
),

-- Step 2d: Get FY (annual) values - these are direct TTM for the fiscal year end
fy_values AS (
    SELECT
        bf.cik,
        bf.line_item,
        bf.period_end as fy_period_end,
        bf.fy,
        bf.val as fy_val
    FROM best_facts bf
    INNER JOIN latest_periods lp ON bf.cik = lp.cik
    WHERE bf.is_flow = true
      AND bf.fp = 'FY'
      -- Only consider FY data from last 2 years
      AND bf.fy >= lp.latest_fy_year - 1
),

-- Step 2e: Get quarterly values and normalize YTD to true quarterly
-- This handles the Q1 direct, Q2-Q4 YTD differencing
quarterly_raw AS (
    SELECT
        bf.cik,
        bf.line_item,
        bf.period_end,
        bf.fy,
        bf.fp,
        bf.val,
        -- For Q1, value is already quarterly
        -- For Q2/Q3/Q4, we need the prior cumulative to subtract
        LAG(bf.val) OVER (
            PARTITION BY bf.cik, bf.line_item, bf.fy 
            ORDER BY bf.fp
        ) as prior_ytd_val
    FROM best_facts bf
    WHERE bf.is_flow = true
      AND bf.fp IN ('Q1', 'Q2', 'Q3', 'Q4')
),

quarterly_normalized AS (
    SELECT
        cik,
        line_item,
        period_end,
        fy,
        fp,
        CASE 
            WHEN fp = 'Q1' THEN val
            ELSE COALESCE(val - prior_ytd_val, val)  -- YTD diff or direct if prior unavailable
        END as quarter_val,
        CASE 
            WHEN fp = 'Q1' THEN 'direct'
            WHEN prior_ytd_val IS NOT NULL THEN 'ytd_diff'
            ELSE 'direct_fallback'
        END as normalization_method
    FROM quarterly_raw
),

-- Step 2f: Calculate TTM by summing last 4 quarters where available
quarterly_with_row AS (
    SELECT
        cik,
        line_item,
        period_end,
        quarter_val,
        ROW_NUMBER() OVER (
            PARTITION BY cik, line_item 
            ORDER BY period_end DESC
        ) as recency_rank
    FROM quarterly_normalized
    WHERE quarter_val IS NOT NULL
),

ttm_from_quarters AS (
    SELECT
        cik,
        line_item,
        MAX(period_end) as ttm_period_end,
        SUM(quarter_val) as ttm_val,
        COUNT(*) as quarters_used,
        'sum_quarters' as ttm_method
    FROM quarterly_with_row
    WHERE recency_rank <= 4  -- Last 4 quarters
    GROUP BY cik, line_item
),

-- Step 2g: Combine TTM sources with priority
-- Priority: 4-quarter sum > FY value > annualized single quarter
ttm_combined AS (
    SELECT
        COALESCE(tq.cik, fy.cik) as cik,
        COALESCE(tq.line_item, fy.line_item) as line_item,
        COALESCE(tq.ttm_period_end, fy.fy_period_end) as as_of_period_end,
        CASE
            -- Best: 4 quarters summed
            WHEN tq.quarters_used = 4 THEN tq.ttm_val
            -- Good: Use FY if available and more recent or equal
            WHEN fy.fy_val IS NOT NULL AND (tq.ttm_val IS NULL OR fy.fy_period_end >= tq.ttm_period_end) THEN fy.fy_val
            -- Acceptable: Use partial quarters, annualized
            WHEN tq.quarters_used >= 2 THEN tq.ttm_val * 4.0 / tq.quarters_used
            -- Fallback: Single quarter annualized
            WHEN tq.quarters_used = 1 THEN tq.ttm_val * 4
            -- Last resort: Use FY even if older
            ELSE fy.fy_val
        END as ttm_val,
        CASE
            WHEN tq.quarters_used = 4 THEN 'sum_4_quarters'
            WHEN fy.fy_val IS NOT NULL AND (tq.ttm_val IS NULL OR fy.fy_period_end >= tq.ttm_period_end) THEN 'fy_direct'
            WHEN tq.quarters_used >= 2 THEN CONCAT('annualized_', tq.quarters_used, '_quarters')
            WHEN tq.quarters_used = 1 THEN 'annualized_1_quarter'
            ELSE 'fy_fallback'
        END as ttm_method,
        COALESCE(tq.quarters_used, 0) as quarters_used
    FROM ttm_from_quarters tq
    FULL OUTER JOIN (
        SELECT cik, line_item, MAX(fy_period_end) as fy_period_end, MAX(fy_val) as fy_val
        FROM fy_values
        GROUP BY cik, line_item
    ) fy ON tq.cik = fy.cik AND tq.line_item = fy.line_item
)

SELECT * FROM ttm_combined
WHERE ttm_val IS NOT NULL
"""

ttm_values = spark.sql(ttm_calculation_sql)
ttm_values.createOrReplaceTempView("ttm_values")
display(ttm_values.orderBy("cik", "line_item"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Build Balance Sheet Values (Point-in-Time)

# COMMAND ----------

balance_sql = """
WITH balance_facts AS (
    SELECT
        cf.cik,
        tm.line_item,
        cf.end as period_end,
        cf.val,
        cf.filed,
        ROW_NUMBER() OVER (
            PARTITION BY cf.cik, tm.line_item
            ORDER BY cf.end DESC, cf.filed DESC
        ) as recency_rank
    FROM silver.edgar.company_facts cf
    INNER JOIN gold.financials.tag_map tm 
        ON cf.taxonomy = tm.source_taxonomy 
        AND cf.tag = tm.source_tag
    INNER JOIN target_ciks tc ON cf.cik = tc.cik
    WHERE cf.unit_of_measure = 'USD'
      AND tm.is_flow = false
)
SELECT
    cik,
    line_item,
    period_end,
    val
FROM balance_facts
WHERE recency_rank = 1
"""

balance_values = spark.sql(balance_sql)
balance_values.createOrReplaceTempView("balance_values")
display(balance_values.orderBy("cik", "line_item"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Get Latest Filing Info Per CIK

# COMMAND ----------

filing_info_sql = """
SELECT 
    cik,
    accession_number,
    form_type,
    filed_date
FROM silver.edgar.filings_rss
WHERE cik IN (SELECT cik FROM target_ciks)
  AND form_type IN ('10-K', '10-Q', '10-QT')
QUALIFY ROW_NUMBER() OVER (PARTITION BY cik ORDER BY filed_date DESC) = 1
"""

filing_info = spark.sql(filing_info_sql)
filing_info.createOrReplaceTempView("filing_info")
display(filing_info)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Get Company Metadata

# COMMAND ----------

company_meta_sql = """
SELECT
    cik,
    MAX(CASE WHEN tag = 'EntityRegistrantName' THEN val END) as entity_name
FROM silver.edgar.company_facts
WHERE cik IN (SELECT cik FROM target_ciks)
  AND taxonomy = 'dei'
  AND tag IN ('EntityRegistrantName')
GROUP BY cik
"""

company_meta = spark.sql(company_meta_sql)
company_meta.createOrReplaceTempView("company_meta")
display(company_meta)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Get Damodaran Reference Data

# COMMAND ----------

# Risk-free rate
rf_rate = spark.sql("""
    SELECT
        observation_date as rf_date,
        percent / 100.0 as rf
    FROM silver.fred.market_yield_10yr
    WHERE percent IS NOT NULL
    ORDER BY observation_date DESC
    LIMIT 1
""")
rf_rate.createOrReplaceTempView("rf_rate")
display(rf_rate)

# COMMAND ----------

# Equity Risk Premium
erp_val = spark.sql("""
    SELECT
        as_of_date as erp_as_of_date,
        implied_erp as erp
    FROM gold.damodaran.implied_erp
    ORDER BY as_of_date DESC
    LIMIT 1
""")
erp_val.createOrReplaceTempView("erp_val")
display(erp_val)

# COMMAND ----------

# Industry betas (using Total Market as fallback since we don't have SIC mapping)
industry_beta = spark.sql("""
    SELECT
        damodaran_industry,
        unlevered_beta,
        d_e_ratio as target_de_ratio,
        as_of_year as industry_beta_as_of_year
    FROM gold.damodaran.industry_betas
    WHERE damodaran_industry = 'Total Market'
    ORDER BY as_of_year DESC
    LIMIT 1
""")
industry_beta.createOrReplaceTempView("industry_beta")
display(industry_beta)

# COMMAND ----------

# Ratings spreads
spreads = spark.sql("""
    SELECT
        as_of_date as spreads_as_of_date,
        rating,
        default_spread
    FROM gold.damodaran.ratings_spreads
    WHERE as_of_date = (SELECT MAX(as_of_date) FROM gold.damodaran.ratings_spreads)
""")
spreads.createOrReplaceTempView("spreads")

# COMMAND ----------

# Synthetic rating bands
rating_bands = spark.sql("""
    SELECT * FROM gold.damodaran.synthetic_rating_bands
""")
rating_bands.createOrReplaceTempView("rating_bands")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Assemble DCF Inputs

# COMMAND ----------

dcf_inputs_sql = """
WITH base AS (
    SELECT
        fi.cik,
        fi.accession_number as source_accn,
        fi.filed_date as source_filed_date,
        fi.form_type,
        cm.entity_name,
        -- Get the as_of_period_end from TTM values
        (SELECT MAX(as_of_period_end) FROM ttm_values tv WHERE tv.cik = fi.cik) as as_of_period_end
    FROM filing_info fi
    LEFT JOIN company_meta cm ON fi.cik = cm.cik
),

-- Pivot TTM values
ttm_pivot AS (
    SELECT
        cik,
        MAX(as_of_period_end) as ttm_period_end,
        MAX(CASE WHEN line_item = 'revenue' THEN ttm_val END) as revenue_ttm,
        MAX(CASE WHEN line_item = 'revenue' THEN ttm_method END) as revenue_ttm_method,
        MAX(CASE WHEN line_item = 'ebit' THEN ttm_val END) as ebit_ttm,
        MAX(CASE WHEN line_item = 'ebit' THEN ttm_method END) as ebit_ttm_method,
        MAX(CASE WHEN line_item = 'pretax_income' THEN ttm_val END) as pretax_income_ttm,
        MAX(CASE WHEN line_item = 'tax_expense' THEN ttm_val END) as tax_expense_ttm,
        MAX(CASE WHEN line_item = 'net_income' THEN ttm_val END) as net_income_ttm,
        MAX(CASE WHEN line_item = 'da' THEN ttm_val END) as da_ttm,
        MAX(CASE WHEN line_item = 'capex' THEN ttm_val END) as capex_ttm,
        MAX(CASE WHEN line_item = 'interest_expense' THEN ttm_val END) as interest_expense_ttm
    FROM ttm_values
    GROUP BY cik
),

-- Pivot balance values
balance_pivot AS (
    SELECT
        cik,
        MAX(CASE WHEN line_item = 'cash' THEN val END) as cash_latest,
        MAX(CASE WHEN line_item = 'debt_st' THEN val END) as debt_st_latest,
        MAX(CASE WHEN line_item = 'debt_lt' THEN val END) as debt_lt_latest,
        MAX(CASE WHEN line_item = 'book_equity' THEN val END) as book_equity_latest,
        MAX(CASE WHEN line_item = 'current_assets' THEN val END) as current_assets,
        MAX(CASE WHEN line_item = 'current_liabilities' THEN val END) as current_liabilities
    FROM balance_values
    GROUP BY cik
),

-- Join base with financials
with_financials AS (
    SELECT
        b.cik,
        b.source_accn,
        b.source_filed_date,
        b.entity_name,
        COALESCE(b.as_of_period_end, tp.ttm_period_end, b.source_filed_date) as as_of_period_end,
        -- TTM flows
        tp.revenue_ttm,
        tp.revenue_ttm_method,
        tp.ebit_ttm,
        tp.ebit_ttm_method,
        tp.pretax_income_ttm,
        tp.tax_expense_ttm,
        tp.net_income_ttm,
        tp.da_ttm,
        tp.capex_ttm,
        tp.interest_expense_ttm,
        -- Balances
        bp.cash_latest,
        bp.debt_st_latest,
        bp.debt_lt_latest,
        bp.book_equity_latest,
        -- Working capital (no YoY change available in backfill)
        (COALESCE(bp.current_assets, 0) - COALESCE(bp.cash_latest, 0)) 
            - (COALESCE(bp.current_liabilities, 0) - COALESCE(bp.debt_st_latest, 0)) as non_cash_wc,
        CAST(NULL AS DOUBLE) as non_cash_working_capital_yoy_change,
        false as wc_change_available,
        -- Company classification (default to corporate without SIC)
        CAST(NULL AS INT) as sic,
        false as is_financial,
        'Total Market' as damodaran_industry,
        true as industry_beta_fallback
    FROM base b
    LEFT JOIN ttm_pivot tp ON b.cik = tp.cik
    LEFT JOIN balance_pivot bp ON b.cik = bp.cik
),

-- Add Damodaran parameters
with_params AS (
    SELECT
        wf.*,
        rf.rf,
        erp.erp,
        erp.erp_as_of_date,
        ib.unlevered_beta,
        ib.target_de_ratio,
        ib.industry_beta_as_of_year
    FROM with_financials wf
    CROSS JOIN rf_rate rf
    CROSS JOIN erp_val erp
    CROSS JOIN industry_beta ib
),

-- Compute derived values
with_derived AS (
    SELECT
        wp.*,
        -- Tax rate effective
        CASE 
            WHEN wp.pretax_income_ttm > 0 
            THEN LEAST(GREATEST(wp.tax_expense_ttm / wp.pretax_income_ttm, 0), 0.5)
            ELSE 0.25
        END as tax_rate_effective,
        0.25 as tax_rate_marginal,
        -- Levered beta
        wp.unlevered_beta * (1 + (1 - 0.25) * wp.target_de_ratio) as levered_beta,
        -- Operating margin
        CASE WHEN wp.revenue_ttm > 0 THEN wp.ebit_ttm / wp.revenue_ttm ELSE NULL END as operating_margin,
        -- Interest coverage
        CASE 
            WHEN wp.interest_expense_ttm > 0 THEN wp.ebit_ttm / wp.interest_expense_ttm 
            ELSE NULL 
        END as interest_coverage
    FROM with_params wp
),

-- Get synthetic rating
with_rating AS (
    SELECT
        wd.*,
        srb.rating as synthetic_rating
    FROM with_derived wd
    LEFT JOIN rating_bands srb
        ON wd.interest_coverage > srb.min_interest_coverage
        AND wd.interest_coverage <= srb.max_interest_coverage
),

-- Get default spread
with_spread AS (
    SELECT
        wr.*,
        s.default_spread,
        s.spreads_as_of_date
    FROM with_rating wr
    LEFT JOIN spreads s ON wr.synthetic_rating = s.rating
),

-- Final calculations
final AS (
    SELECT
        ws.*,
        -- Cost of equity
        ws.rf + ws.levered_beta * ws.erp as cost_of_equity,
        -- Cost of debt
        ws.rf + COALESCE(ws.default_spread, 0) as cost_of_debt,
        -- NOPAT
        ws.ebit_ttm * (1 - ws.tax_rate_effective) as nopat_ttm,
        -- Reinvestment base (no WC change in backfill)
        ws.capex_ttm - ws.da_ttm as reinvestment_base,
        -- WACC
        (1 / (1 + ws.target_de_ratio)) * (ws.rf + ws.levered_beta * ws.erp) +
        (ws.target_de_ratio / (1 + ws.target_de_ratio)) * (ws.rf + COALESCE(ws.default_spread, 0)) * (1 - ws.tax_rate_marginal) as wacc,
        -- ROE proxy
        CASE 
            WHEN ws.book_equity_latest > 0 
            THEN LEAST(GREATEST(ws.net_income_ttm / ws.book_equity_latest, 0), 0.25)
            ELSE NULL
        END as roe_proxy,
        -- Terminal growth = rf for damodaran_v1
        ws.rf as g_terminal_v1,
        -- Terminal growth = max(rf, 0.03) for damodaran_v1_conservative
        GREATEST(ws.rf, 0.03) as g_terminal_conservative,
        -- Initial growth placeholder
        0.05 as growth_initial
    FROM with_spread ws
)

SELECT * FROM final
"""

dcf_base = spark.sql(dcf_inputs_sql)
dcf_base.createOrReplaceTempView("dcf_base")
display(dcf_base)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Generate Final DCF Inputs for Both Assumption Sets

# COMMAND ----------

from pyspark.sql.functions import (
    col,
    lit,
    current_date,
    current_timestamp,
    when,
    array,
    array_compact,
    concat,
    uuid,
    struct,
)

# Read the base DCF data
dcf_base_df = spark.table("dcf_base")

# Generate rows for both assumption sets
dcf_inputs_v1 = dcf_base_df.select(
    concat(col("cik"), lit("-"), col("source_accn"), lit("-dcf-backfill-v1")).alias(
        "_id"
    ),
    col("cik"),
    current_date().alias("valuation_date"),
    lit("damodaran_v1").alias("assumption_set_id"),
    when(col("is_financial"), lit("financial"))
    .otherwise(lit("corporate"))
    .alias("model_type"),
    col("source_accn"),
    col("source_filed_date"),
    col("as_of_period_end"),
    col("entity_name"),
    col("sic"),
    col("is_financial"),
    col("damodaran_industry"),
    col("revenue_ttm"),
    col("ebit_ttm"),
    col("pretax_income_ttm"),
    col("tax_expense_ttm"),
    col("net_income_ttm"),
    col("da_ttm"),
    col("capex_ttm"),
    col("interest_expense_ttm"),
    col("cash_latest"),
    col("debt_st_latest"),
    col("debt_lt_latest"),
    col("book_equity_latest"),
    col("non_cash_working_capital_yoy_change"),
    col("wc_change_available"),
    lit(None).cast("string").alias("ticker_primary"),
    lit(None).cast("date").alias("market_price_date"),
    lit(None).cast("double").alias("market_price"),
    lit(None).cast("string").alias("market_price_method"),
    lit(None).cast("double").alias("shares_basic_latest"),
    lit(None).cast("double").alias("market_cap"),
    col("rf"),
    col("erp"),
    col("erp_as_of_date"),
    col("unlevered_beta"),
    col("target_de_ratio"),
    col("industry_beta_as_of_year"),
    col("levered_beta"),
    col("cost_of_equity"),
    col("interest_coverage"),
    col("synthetic_rating"),
    col("default_spread"),
    col("spreads_as_of_date"),
    col("cost_of_debt"),
    col("tax_rate_effective"),
    col("tax_rate_marginal"),
    col("wacc"),
    col("operating_margin"),
    col("nopat_ttm"),
    col("reinvestment_base"),
    (col("nopat_ttm") - col("reinvestment_base")).alias("fcff_base"),
    col("roe_proxy"),
    col("growth_initial"),
    col("g_terminal_v1").alias("g_terminal"),
    # has_minimum_inputs
    when(
        ~col("is_financial"),
        col("revenue_ttm").isNotNull()
        & col("ebit_ttm").isNotNull()
        & col("rf").isNotNull()
        & col("erp").isNotNull()
        & col("levered_beta").isNotNull()
        & col("growth_initial").isNotNull(),
    )
    .otherwise(
        col("net_income_ttm").isNotNull()
        & col("book_equity_latest").isNotNull()
        & (col("book_equity_latest") > 0)
        & col("rf").isNotNull()
        & col("erp").isNotNull()
        & col("levered_beta").isNotNull()
        & col("growth_initial").isNotNull()
    )
    .alias("has_minimum_inputs"),
    # missing_fields - simplified for PySpark
    array_compact(
        array(
            when(
                col("revenue_ttm").isNull() & ~col("is_financial"), lit("revenue_ttm")
            ),
            when(col("ebit_ttm").isNull() & ~col("is_financial"), lit("ebit_ttm")),
            when(col("net_income_ttm").isNull(), lit("net_income_ttm")),
            when(col("rf").isNull(), lit("rf")),
            when(col("erp").isNull(), lit("erp")),
            when(col("levered_beta").isNull(), lit("beta")),
            when(
                col("book_equity_latest").isNull() & col("is_financial"),
                lit("book_equity"),
            ),
        )
    ).alias("missing_fields"),
    # quality_flags
    array_compact(
        array(
            when(~col("wc_change_available"), lit("wc_change_unavailable")),
            when(col("industry_beta_fallback"), lit("industry_beta_fallback")),
            when(
                (col("tax_rate_effective") == 0.25) & (col("pretax_income_ttm") <= 0),
                lit("effective_tax_clamped"),
            ),
            when(
                col("roe_proxy").isNotNull()
                & ((col("roe_proxy") == 0) | (col("roe_proxy") == 0.25)),
                lit("roe_clamped"),
            ),
            when(
                col("synthetic_rating").isNull()
                & col("interest_expense_ttm").isNotNull(),
                lit("synthetic_rating_fallback"),
            ),
            lit("backfill_ttm_heuristic"),  # Flag that TTM was estimated
        )
    ).alias("quality_flags"),
    lit(True).alias("options_omitted"),
    lit(True).alias("rsus_omitted"),
    # _footprint
    struct(
        lit(None).cast("string").alias("upstream_id"),
        current_timestamp().alias("create_ts"),
        current_timestamp().alias("modify_ts"),
    ).alias("_footprint"),
)

# Conservative version with different terminal growth
dcf_inputs_conservative = dcf_base_df.select(
    concat(
        col("cik"), lit("-"), col("source_accn"), lit("-dcf-backfill-conservative")
    ).alias("_id"),
    col("cik"),
    current_date().alias("valuation_date"),
    lit("damodaran_v1_conservative").alias("assumption_set_id"),
    when(col("is_financial"), lit("financial"))
    .otherwise(lit("corporate"))
    .alias("model_type"),
    col("source_accn"),
    col("source_filed_date"),
    col("as_of_period_end"),
    col("entity_name"),
    col("sic"),
    col("is_financial"),
    col("damodaran_industry"),
    col("revenue_ttm"),
    col("ebit_ttm"),
    col("pretax_income_ttm"),
    col("tax_expense_ttm"),
    col("net_income_ttm"),
    col("da_ttm"),
    col("capex_ttm"),
    col("interest_expense_ttm"),
    col("cash_latest"),
    col("debt_st_latest"),
    col("debt_lt_latest"),
    col("book_equity_latest"),
    col("non_cash_working_capital_yoy_change"),
    col("wc_change_available"),
    lit(None).cast("string").alias("ticker_primary"),
    lit(None).cast("date").alias("market_price_date"),
    lit(None).cast("double").alias("market_price"),
    lit(None).cast("string").alias("market_price_method"),
    lit(None).cast("double").alias("shares_basic_latest"),
    lit(None).cast("double").alias("market_cap"),
    col("rf"),
    col("erp"),
    col("erp_as_of_date"),
    col("unlevered_beta"),
    col("target_de_ratio"),
    col("industry_beta_as_of_year"),
    col("levered_beta"),
    col("cost_of_equity"),
    col("interest_coverage"),
    col("synthetic_rating"),
    col("default_spread"),
    col("spreads_as_of_date"),
    col("cost_of_debt"),
    col("tax_rate_effective"),
    col("tax_rate_marginal"),
    col("wacc"),
    col("operating_margin"),
    col("nopat_ttm"),
    col("reinvestment_base"),
    (col("nopat_ttm") - col("reinvestment_base")).alias("fcff_base"),
    col("roe_proxy"),
    col("growth_initial"),
    col("g_terminal_conservative").alias("g_terminal"),
    # has_minimum_inputs (same logic)
    when(
        ~col("is_financial"),
        col("revenue_ttm").isNotNull()
        & col("ebit_ttm").isNotNull()
        & col("rf").isNotNull()
        & col("erp").isNotNull()
        & col("levered_beta").isNotNull()
        & col("growth_initial").isNotNull(),
    )
    .otherwise(
        col("net_income_ttm").isNotNull()
        & col("book_equity_latest").isNotNull()
        & (col("book_equity_latest") > 0)
        & col("rf").isNotNull()
        & col("erp").isNotNull()
        & col("levered_beta").isNotNull()
        & col("growth_initial").isNotNull()
    )
    .alias("has_minimum_inputs"),
    # missing_fields
    array_compact(
        array(
            when(
                col("revenue_ttm").isNull() & ~col("is_financial"), lit("revenue_ttm")
            ),
            when(col("ebit_ttm").isNull() & ~col("is_financial"), lit("ebit_ttm")),
            when(col("net_income_ttm").isNull(), lit("net_income_ttm")),
            when(col("rf").isNull(), lit("rf")),
            when(col("erp").isNull(), lit("erp")),
            when(col("levered_beta").isNull(), lit("beta")),
            when(
                col("book_equity_latest").isNull() & col("is_financial"),
                lit("book_equity"),
            ),
        )
    ).alias("missing_fields"),
    # quality_flags
    array_compact(
        array(
            when(~col("wc_change_available"), lit("wc_change_unavailable")),
            when(col("industry_beta_fallback"), lit("industry_beta_fallback")),
            when(
                (col("tax_rate_effective") == 0.25) & (col("pretax_income_ttm") <= 0),
                lit("effective_tax_clamped"),
            ),
            when(
                col("roe_proxy").isNotNull()
                & ((col("roe_proxy") == 0) | (col("roe_proxy") == 0.25)),
                lit("roe_clamped"),
            ),
            when(
                col("synthetic_rating").isNull()
                & col("interest_expense_ttm").isNotNull(),
                lit("synthetic_rating_fallback"),
            ),
            lit("backfill_ttm_heuristic"),
        )
    ).alias("quality_flags"),
    lit(True).alias("options_omitted"),
    lit(True).alias("rsus_omitted"),
    struct(
        lit(None).cast("string").alias("upstream_id"),
        current_timestamp().alias("create_ts"),
        current_timestamp().alias("modify_ts"),
    ).alias("_footprint"),
)

# Union both assumption sets
dcf_inputs_final = dcf_inputs_v1.union(dcf_inputs_conservative)
dcf_inputs_final.createOrReplaceTempView("dcf_inputs_final")

print(f"Total rows to insert: {dcf_inputs_final.count()}")
display(dcf_inputs_final)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9: Preview Key Metrics Before Insert

# COMMAND ----------

# Preview key metrics
preview = spark.sql("""
    SELECT 
        cik,
        assumption_set_id,
        entity_name,
        revenue_ttm,
        ebit_ttm,
        net_income_ttm,
        wacc,
        cost_of_equity,
        g_terminal,
        fcff_base,
        has_minimum_inputs,
        missing_fields,
        quality_flags
    FROM dcf_inputs_final
    ORDER BY cik, assumption_set_id
""")
display(preview)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10: Execute MERGE into gold.valuation.dcf_inputs
# MAGIC
# MAGIC **Run this cell to actually insert the data!**

# COMMAND ----------

# MERGE into the target table
dcf_inputs_final.createOrReplaceTempView("dcf_inputs_to_merge")

merge_sql = """
MERGE INTO gold.valuation.dcf_inputs AS target
USING dcf_inputs_to_merge AS source
ON target.cik = source.cik 
   AND target.valuation_date = source.valuation_date 
   AND target.assumption_set_id = source.assumption_set_id 
   AND target.source_accn = source.source_accn 
   AND target.model_type = source.model_type
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
"""

spark.sql(merge_sql)
print("MERGE completed successfully!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 11: Validation

# COMMAND ----------

# Verify the inserted rows
validation = spark.sql("""
    SELECT 
        t.ticker,
        i.cik,
        i.assumption_set_id,
        i.entity_name,
        i.has_minimum_inputs,
        i.revenue_ttm,
        i.ebit_ttm,
        i.wacc,
        i.fcff_base,
        i.missing_fields,
        i.quality_flags
    FROM gold.valuation.dcf_inputs i
    LEFT JOIN gold.dim.cik_ticker t ON i.cik = t.cik
    WHERE i.cik IN ('0000320193', '0001018724', '0001326801', '0000019617')
    ORDER BY t.ticker, i.assumption_set_id
""")
display(validation)

# COMMAND ----------

# Count total rows and ready rows
summary = spark.sql("""
    SELECT 
        COUNT(*) as total_rows,
        SUM(CASE WHEN has_minimum_inputs THEN 1 ELSE 0 END) as ready_for_dcf,
        COUNT(DISTINCT cik) as distinct_ciks
    FROM gold.valuation.dcf_inputs
    WHERE cik IN ('0000320193', '0001018724', '0001326801', '0000019617')
""")
display(summary)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Rollback (if needed)
# MAGIC
# MAGIC Uncomment and run this cell to delete the backfilled rows:

# COMMAND ----------

# # ROLLBACK - Delete backfilled rows
# spark.sql("""
#     DELETE FROM gold.valuation.dcf_inputs
#     WHERE cik IN ('0000320193', '0001018724', '0001326801', '0000019617')
#       AND valuation_date = current_date()
# """)
# print("Rollback completed - backfilled rows deleted")
