-- gold.dim.cik_ticker
-- Purpose: CIK to ticker mapping for market price joins
-- Keys: (cik, ticker)

create table if not exists gold.dim.cik_ticker (
  _id string,
  cik string,
  ticker string,
  is_primary boolean,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, ticker)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
