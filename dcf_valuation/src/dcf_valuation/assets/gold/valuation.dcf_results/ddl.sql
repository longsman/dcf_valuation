-- gold.valuation.dcf_results
-- Purpose: Final DCF valuation results
-- Keys: (cik, valuation_date, assumption_set_id, source_accn, model_type)

create table if not exists gold.valuation.dcf_results (
  _id string,
  cik string,
  valuation_date date,
  assumption_set_id string,
  source_accn string,
  model_type string,
  pv_explicit double,
  pv_terminal double,
  enterprise_value double,
  equity_value double,
  value_per_share double,
  terminal_pct double,
  upside_downside double,
  has_minimum_inputs boolean,
  missing_fields array<string>,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, valuation_date, source_accn)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
