-- gold.market.prices_daily
-- Purpose: Canonical per-day price record per ticker
-- Keys: (ticker, price_date)

create table if not exists gold.market.prices_daily (
  _id string,
  ticker string,
  price_date date,
  close double,
  price_method string,
  price_date_method string,
  last_trade_ts timestamp,
  source string,
  source_snapshot_date date,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (ticker, price_date)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
