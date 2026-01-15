-- gold.damodaran.synthetic_rating_bands
-- Purpose: Interest coverage ratio to synthetic rating mapping
-- Keys: (rating)

create table if not exists gold.damodaran.synthetic_rating_bands (
  _id string,
  rating string,
  min_interest_coverage double,
  max_interest_coverage double,
  loaded_at timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (rating)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
