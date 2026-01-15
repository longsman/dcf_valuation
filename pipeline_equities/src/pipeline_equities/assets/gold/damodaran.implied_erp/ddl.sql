-- gold.damodaran.implied_erp
-- Purpose: Damodaran implied equity risk premium by month
-- Keys: (as_of_date)

create table if not exists gold.damodaran.implied_erp (
  _id string,
  as_of_date date,
  implied_erp double,
  source_url string,
  loaded_at timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (as_of_date)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
