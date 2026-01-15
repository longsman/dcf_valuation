-- gold.financials.flow_ttm
-- Purpose: Trailing twelve month (TTM) values for flow items
-- Keys: (cik, line_item, as_of_period_end)

create table if not exists gold.financials.flow_ttm (
  _id string,
  cik string,
  line_item string,
  as_of_period_end date,
  ttm_val double,
  quarters_in_ttm int,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, line_item, as_of_period_end)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
