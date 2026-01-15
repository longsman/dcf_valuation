create table if not exists silver.fred.market_yield_10yr (
  _id string,
  observation_date date,
  percent decimal(38, 2),
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (_id, observation_date, _footprint.modify_ts)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
