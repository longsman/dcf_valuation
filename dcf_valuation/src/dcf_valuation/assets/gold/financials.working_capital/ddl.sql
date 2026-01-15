-- gold.financials.working_capital
-- Purpose: Computed non-cash working capital and YoY changes
-- Keys: (cik, as_of_period_end)

create table if not exists gold.financials.working_capital (
  _id string,
  cik string,
  as_of_period_end date,
  current_assets double,
  cash double,
  current_liabilities double,
  debt_st double,
  non_cash_working_capital double,
  non_cash_working_capital_yoy_change double,
  quality_flags array<string>,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, as_of_period_end)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
