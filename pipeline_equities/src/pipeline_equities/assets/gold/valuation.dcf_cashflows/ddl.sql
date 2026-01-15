-- gold.valuation.dcf_cashflows
-- Purpose: Per-year projected cashflows for DCF valuation
-- Keys: (cik, valuation_date, assumption_set_id, source_accn, model_type, year)

create table if not exists gold.valuation.dcf_cashflows (
  _id string,
  cik string,
  valuation_date date,
  assumption_set_id string,
  source_accn string,
  model_type string,
  year int,
  is_terminal boolean,
  g_year double,
  margin_year double,
  roic_or_roe_year double,
  revenue double,
  ebit double,
  nopat_or_net_income double,
  reinvestment double,
  fcf double,
  discount_rate double,
  discount_factor double,
  pv double,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, valuation_date, source_accn, year)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
