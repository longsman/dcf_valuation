-- gold.valuation.dcf_inputs
-- Purpose: All inputs needed for DCF calculation per filing
-- Keys: (cik, valuation_date, assumption_set_id, source_accn, model_type)

create table if not exists gold.valuation.dcf_inputs (
  _id string,
  -- Identifiers
  cik string,
  valuation_date date,
  assumption_set_id string,
  model_type string,
  
  -- Filing provenance
  source_accn string,
  source_filed_date date,
  as_of_period_end date,
  
  -- Company metadata
  entity_name string,
  sic int,
  is_financial boolean,
  damodaran_industry string,
  
  -- TTM flows (corporate)
  revenue_ttm double,
  ebit_ttm double,
  pretax_income_ttm double,
  tax_expense_ttm double,
  net_income_ttm double,
  da_ttm double,
  capex_ttm double,
  interest_expense_ttm double,
  
  -- Latest balances
  cash_latest double,
  debt_st_latest double,
  debt_lt_latest double,
  book_equity_latest double,
  
  -- Working capital
  non_cash_working_capital_yoy_change double,
  wc_change_available boolean,
  
  -- Market data
  ticker_primary string,
  market_price_date date,
  market_price double,
  market_price_method string,
  shares_basic_latest double,
  market_cap double,
  
  -- Damodaran parameters
  rf double,
  erp double,
  erp_as_of_date date,
  
  -- Beta calculation
  unlevered_beta double,
  target_de_ratio double,
  industry_beta_as_of_year int,
  levered_beta double,
  
  -- Cost of equity
  cost_of_equity double,
  
  -- Cost of debt (synthetic rating)
  interest_coverage double,
  synthetic_rating string,
  default_spread double,
  spreads_as_of_date date,
  cost_of_debt double,
  
  -- Tax rates
  tax_rate_effective double,
  tax_rate_marginal double,
  
  -- WACC (corporate)
  wacc double,
  
  -- Derived metrics
  operating_margin double,
  nopat_ttm double,
  reinvestment_base double,
  fcff_base double,
  roe_proxy double,
  
  -- Growth
  growth_initial double,
  g_terminal double,
  
  -- Validation
  has_minimum_inputs boolean,
  missing_fields array<string>,
  quality_flags array<string>,
  options_omitted boolean,
  rsus_omitted boolean,
  
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, valuation_date, source_accn)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
