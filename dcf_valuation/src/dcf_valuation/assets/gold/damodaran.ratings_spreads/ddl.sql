-- gold.damodaran.ratings_spreads
-- Purpose: Damodaran default spreads by credit rating
-- Keys: (as_of_date, rating)

create table if not exists gold.damodaran.ratings_spreads (
  _id string,
  as_of_date date,
  rating string,
  default_spread double,
  loaded_at timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (as_of_date, rating)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
