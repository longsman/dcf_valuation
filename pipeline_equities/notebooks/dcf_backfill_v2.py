# Databricks notebook source
# MAGIC %md
# MAGIC # DCF Inputs Backfill v2 - Simplified
# MAGIC
# MAGIC Simplified backfill that uses FY (annual) data directly from company_facts.
# MAGIC This avoids expensive quarterly normalization for the backfill use case.

# COMMAND ----------

# Target CIKs
TARGET_CIKS = ["0000320193", "0001018724", "0001326801", "0000019617"]
TARGET_CIKS_SQL = ",".join([f"'{c}'" for c in TARGET_CIKS])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Get Latest Filing Info

# COMMAND ----------

latest_filings_df = spark.sql(f"""
    SELECT 
        cik,
        accession_number,
        form_type,
        filed_date
    FROM silver.edgar.filings_rss
    WHERE cik IN ({TARGET_CIKS_SQL})
      AND form_type IN ('10-K', '10-Q')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY cik ORDER BY filed_date DESC) = 1
""")
latest_filings_df.createOrReplaceTempView("latest_filings")
display(latest_filings_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Get FY Financial Data (Annual Values = TTM)
# MAGIC
# MAGIC For 10-K filers, FY values are already TTM. For simplicity, we use the most recent FY data.

# COMMAND ----------

# Get the tag mappings we need
tag_map_df = spark.sql("""
    SELECT line_item, source_taxonomy, source_tag, is_flow, priority
    FROM gold.financials.tag_map
    WHERE line_item IN (
        'revenue', 'ebit', 'pretax_income', 'tax_expense', 'net_income',
        'da', 'capex', 'interest_expense',
        'cash', 'debt_st', 'debt_lt', 'book_equity'
    )
""")
tag_map_df.createOrReplaceTempView("tag_map_subset")
display(tag_map_df)

# COMMAND ----------

# Get financial facts - use FY for flows (TTM equivalent), latest for balances
financials_df = spark.sql(f"""
WITH mapped_facts AS (
    SELECT
        cf.cik,
        tm.line_item,
        tm.is_flow,
        cf.fp,
        cf.fy,
        cf.end as period_end,
        cf.val,
        cf.filed,
        ROW_NUMBER() OVER (
            PARTITION BY cf.cik, tm.line_item
            ORDER BY 
                CASE WHEN tm.is_flow AND cf.fp = 'FY' THEN 0 ELSE 1 END,  -- Prefer FY for flows
                cf.end DESC,
                tm.priority ASC,
                cf.filed DESC
        ) as rn
    FROM silver.edgar.company_facts cf
    INNER JOIN tag_map_subset tm 
        ON cf.taxonomy = tm.source_taxonomy 
        AND cf.tag = tm.source_tag
    WHERE cf.cik IN ({TARGET_CIKS_SQL})
      AND cf.unit_of_measure = 'USD'
)
SELECT cik, line_item, is_flow, fp, fy, period_end, val
FROM mapped_facts
WHERE rn = 1
ORDER BY cik, line_item
""")
financials_df.createOrReplaceTempView("financials")
display(financials_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Pivot Financial Data

# COMMAND ----------

pivoted_df = spark.sql(f"""
SELECT
    cik,
    MAX(CASE WHEN line_item = 'revenue' THEN val END) as revenue_ttm,
    MAX(CASE WHEN line_item = 'ebit' THEN val END) as ebit_ttm,
    MAX(CASE WHEN line_item = 'pretax_income' THEN val END) as pretax_income_ttm,
    MAX(CASE WHEN line_item = 'tax_expense' THEN val END) as tax_expense_ttm,
    MAX(CASE WHEN line_item = 'net_income' THEN val END) as net_income_ttm,
    MAX(CASE WHEN line_item = 'da' THEN val END) as da_ttm,
    MAX(CASE WHEN line_item = 'capex' THEN val END) as capex_ttm,
    MAX(CASE WHEN line_item = 'interest_expense' THEN val END) as interest_expense_ttm,
    MAX(CASE WHEN line_item = 'cash' THEN val END) as cash_latest,
    MAX(CASE WHEN line_item = 'debt_st' THEN val END) as debt_st_latest,
    MAX(CASE WHEN line_item = 'debt_lt' THEN val END) as debt_lt_latest,
    MAX(CASE WHEN line_item = 'book_equity' THEN val END) as book_equity_latest,
    MAX(period_end) as as_of_period_end
FROM financials
GROUP BY cik
""")
pivoted_df.createOrReplaceTempView("financials_pivoted")
display(pivoted_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Get Company Names

# COMMAND ----------

company_names_df = spark.sql(f"""
SELECT cik, MAX(val) as entity_name
FROM silver.edgar.company_facts
WHERE cik IN ({TARGET_CIKS_SQL})
  AND taxonomy = 'dei'
  AND tag = 'EntityRegistrantName'
GROUP BY cik
""")
company_names_df.createOrReplaceTempView("company_names")
display(company_names_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Get Damodaran Reference Data

# COMMAND ----------

# Risk-free rate
rf_df = spark.sql("""
SELECT percent / 100.0 as rf
FROM silver.fred.market_yield_10yr
WHERE percent IS NOT NULL
ORDER BY observation_date DESC
LIMIT 1
""")
RF_VALUE = rf_df.collect()[0]["rf"]
print(f"Risk-free rate: {RF_VALUE:.4f}")

# ERP
erp_df = spark.sql("""
SELECT implied_erp as erp, as_of_date as erp_as_of_date
FROM gold.damodaran.implied_erp
ORDER BY as_of_date DESC
LIMIT 1
""")
erp_row = erp_df.collect()[0]
ERP_VALUE = erp_row["erp"]
ERP_DATE = erp_row["erp_as_of_date"]
print(f"Equity Risk Premium: {ERP_VALUE:.4f} as of {ERP_DATE}")

# Industry beta (Total Market fallback)
beta_df = spark.sql("""
SELECT unlevered_beta, d_e_ratio as target_de_ratio, as_of_year
FROM gold.damodaran.industry_betas
WHERE damodaran_industry = 'Total Market'
ORDER BY as_of_year DESC
LIMIT 1
""")
beta_row = beta_df.collect()[0]
UNLEVERED_BETA = beta_row["unlevered_beta"]
TARGET_DE_RATIO = beta_row["target_de_ratio"]
BETA_YEAR = beta_row["as_of_year"]
print(
    f"Unlevered Beta: {UNLEVERED_BETA:.4f}, Target D/E: {TARGET_DE_RATIO:.4f}, Year: {BETA_YEAR}"
)

# Compute levered beta
MARGINAL_TAX = 0.25
LEVERED_BETA = UNLEVERED_BETA * (1 + (1 - MARGINAL_TAX) * TARGET_DE_RATIO)
print(f"Levered Beta: {LEVERED_BETA:.4f}")

# Cost of equity
COST_OF_EQUITY = RF_VALUE + LEVERED_BETA * ERP_VALUE
print(f"Cost of Equity: {COST_OF_EQUITY:.4f}")

# COMMAND ----------

# Get spreads for synthetic rating
spreads_df = spark.sql("""
SELECT rating, default_spread, as_of_date as spreads_as_of_date
FROM gold.damodaran.ratings_spreads
WHERE as_of_date = (SELECT MAX(as_of_date) FROM gold.damodaran.ratings_spreads)
""")
spreads_df.createOrReplaceTempView("spreads")

rating_bands_df = spark.sql("SELECT * FROM gold.damodaran.synthetic_rating_bands")
rating_bands_df.createOrReplaceTempView("rating_bands")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Assemble Final DCF Inputs

# COMMAND ----------

# Build final dataframe with all computed values
final_df = spark.sql(f"""
WITH base AS (
    SELECT
        lf.cik,
        lf.accession_number as source_accn,
        lf.filed_date as source_filed_date,
        cn.entity_name,
        fp.as_of_period_end,
        fp.revenue_ttm,
        fp.ebit_ttm,
        fp.pretax_income_ttm,
        fp.tax_expense_ttm,
        fp.net_income_ttm,
        fp.da_ttm,
        fp.capex_ttm,
        fp.interest_expense_ttm,
        fp.cash_latest,
        fp.debt_st_latest,
        fp.debt_lt_latest,
        fp.book_equity_latest
    FROM latest_filings lf
    LEFT JOIN company_names cn ON lf.cik = cn.cik
    LEFT JOIN financials_pivoted fp ON lf.cik = fp.cik
),
with_derived AS (
    SELECT
        b.*,
        -- Tax rate effective
        CASE 
            WHEN b.pretax_income_ttm > 0 
            THEN LEAST(GREATEST(b.tax_expense_ttm / b.pretax_income_ttm, 0), 0.5)
            ELSE 0.25
        END as tax_rate_effective,
        -- Operating margin
        CASE WHEN b.revenue_ttm > 0 THEN b.ebit_ttm / b.revenue_ttm ELSE NULL END as operating_margin,
        -- Interest coverage
        CASE 
            WHEN b.interest_expense_ttm > 0 THEN b.ebit_ttm / b.interest_expense_ttm 
            ELSE NULL 
        END as interest_coverage
    FROM base b
),
with_rating AS (
    SELECT
        wd.*,
        srb.rating as synthetic_rating
    FROM with_derived wd
    LEFT JOIN rating_bands srb
        ON wd.interest_coverage > srb.min_interest_coverage
        AND wd.interest_coverage <= srb.max_interest_coverage
),
with_spread AS (
    SELECT
        wr.*,
        s.default_spread,
        s.spreads_as_of_date
    FROM with_rating wr
    LEFT JOIN spreads s ON wr.synthetic_rating = s.rating
),
final AS (
    SELECT
        ws.*,
        -- NOPAT
        ws.ebit_ttm * (1 - ws.tax_rate_effective) as nopat_ttm,
        -- Reinvestment base
        ws.capex_ttm - ws.da_ttm as reinvestment_base,
        -- ROE proxy
        CASE 
            WHEN ws.book_equity_latest > 0 
            THEN LEAST(GREATEST(ws.net_income_ttm / ws.book_equity_latest, 0), 0.25)
            ELSE NULL
        END as roe_proxy,
        -- WACC
        (1 / (1 + {TARGET_DE_RATIO})) * {COST_OF_EQUITY} +
        ({TARGET_DE_RATIO} / (1 + {TARGET_DE_RATIO})) * ({RF_VALUE} + COALESCE(ws.default_spread, 0)) * (1 - {MARGINAL_TAX}) as wacc
    FROM with_spread ws
)
SELECT * FROM final
""")
final_df.createOrReplaceTempView("dcf_base")
display(final_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Generate Rows for Both Assumption Sets

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
    struct,
)
from pyspark.sql.types import StringType, DateType, DoubleType

dcf_base_df = spark.table("dcf_base")


# Common columns for both assumption sets
def build_dcf_inputs(df, assumption_set_id, g_terminal):
    return df.select(
        concat(
            col("cik"),
            lit("-"),
            col("source_accn"),
            lit(f"-backfill-{assumption_set_id}"),
        ).alias("_id"),
        col("cik"),
        current_date().alias("valuation_date"),
        lit(assumption_set_id).alias("assumption_set_id"),
        lit("corporate").alias("model_type"),
        col("source_accn"),
        col("source_filed_date"),
        col("as_of_period_end"),
        col("entity_name"),
        lit(None).cast("int").alias("sic"),
        lit(False).alias("is_financial"),
        lit("Total Market").alias("damodaran_industry"),
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
        lit(None).cast("double").alias("non_cash_working_capital_yoy_change"),
        lit(False).alias("wc_change_available"),
        lit(None).cast("string").alias("ticker_primary"),
        lit(None).cast("date").alias("market_price_date"),
        lit(None).cast("double").alias("market_price"),
        lit(None).cast("string").alias("market_price_method"),
        lit(None).cast("double").alias("shares_basic_latest"),
        lit(None).cast("double").alias("market_cap"),
        lit(RF_VALUE).alias("rf"),
        lit(ERP_VALUE).alias("erp"),
        lit(ERP_DATE).alias("erp_as_of_date"),
        lit(UNLEVERED_BETA).alias("unlevered_beta"),
        lit(TARGET_DE_RATIO).alias("target_de_ratio"),
        lit(BETA_YEAR).alias("industry_beta_as_of_year"),
        lit(LEVERED_BETA).alias("levered_beta"),
        lit(COST_OF_EQUITY).alias("cost_of_equity"),
        col("interest_coverage"),
        col("synthetic_rating"),
        col("default_spread"),
        col("spreads_as_of_date"),
        (lit(RF_VALUE) + col("default_spread")).alias("cost_of_debt"),
        col("tax_rate_effective"),
        lit(MARGINAL_TAX).alias("tax_rate_marginal"),
        col("wacc"),
        col("operating_margin"),
        col("nopat_ttm"),
        col("reinvestment_base"),
        (col("nopat_ttm") - col("reinvestment_base")).alias("fcff_base"),
        col("roe_proxy"),
        lit(0.05).alias("growth_initial"),
        lit(g_terminal).alias("g_terminal"),
        # has_minimum_inputs - for corporate model
        (
            col("revenue_ttm").isNotNull()
            & col("ebit_ttm").isNotNull()
            & lit(True)  # rf, erp, beta are always set
        ).alias("has_minimum_inputs"),
        # missing_fields
        array_compact(
            array(
                when(col("revenue_ttm").isNull(), lit("revenue_ttm")),
                when(col("ebit_ttm").isNull(), lit("ebit_ttm")),
                when(col("net_income_ttm").isNull(), lit("net_income_ttm")),
            )
        ).alias("missing_fields"),
        # quality_flags
        array_compact(
            array(
                lit("wc_change_unavailable"),
                lit("industry_beta_fallback"),
                lit("backfill_fy_direct"),
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


# damodaran_v1: terminal growth = rf
dcf_v1 = build_dcf_inputs(dcf_base_df, "damodaran_v1", RF_VALUE)

# damodaran_v1_conservative: terminal growth = max(rf, 0.03)
dcf_conservative = build_dcf_inputs(
    dcf_base_df, "damodaran_v1_conservative", max(RF_VALUE, 0.03)
)

# Union both
dcf_inputs_final = dcf_v1.union(dcf_conservative)
dcf_inputs_final.createOrReplaceTempView("dcf_inputs_to_merge")

print(f"Total rows to insert: {dcf_inputs_final.count()}")
display(dcf_inputs_final)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Preview Before Insert

# COMMAND ----------

preview = spark.sql("""
SELECT 
    cik, assumption_set_id, entity_name,
    revenue_ttm, ebit_ttm, net_income_ttm,
    wacc, cost_of_equity, g_terminal, fcff_base,
    has_minimum_inputs, missing_fields
FROM dcf_inputs_to_merge
ORDER BY cik, assumption_set_id
""")
display(preview)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9: Execute MERGE

# COMMAND ----------

merge_result = spark.sql("""
MERGE INTO gold.valuation.dcf_inputs AS target
USING dcf_inputs_to_merge AS source
ON target.cik = source.cik 
   AND target.valuation_date = source.valuation_date 
   AND target.assumption_set_id = source.assumption_set_id 
   AND target.source_accn = source.source_accn 
   AND target.model_type = source.model_type
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")
print("MERGE completed!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10: Validation

# COMMAND ----------

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
    i.fcff_base
FROM gold.valuation.dcf_inputs i
LEFT JOIN gold.dim.cik_ticker t ON i.cik = t.cik
WHERE i.cik IN ('0000320193', '0001018724', '0001326801', '0000019617')
ORDER BY t.ticker, i.assumption_set_id
""")
display(validation)

# COMMAND ----------

summary = spark.sql("""
SELECT 
    COUNT(*) as total_backfilled_rows,
    SUM(CASE WHEN has_minimum_inputs THEN 1 ELSE 0 END) as ready_for_dcf
FROM gold.valuation.dcf_inputs
WHERE cik IN ('0000320193', '0001018724', '0001326801', '0000019617')
""")
display(summary)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Backfill Complete!
# MAGIC
# MAGIC You can now run the pipeline_equities_dev job to populate dcf_cashflows and dcf_results.
