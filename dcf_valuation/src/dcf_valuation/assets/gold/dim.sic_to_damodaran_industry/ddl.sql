-- gold.dim.sic_to_damodaran_industry
-- Purpose: SIC code to Damodaran industry mapping
-- Keys: (sic)

create table if not exists gold.dim.sic_to_damodaran_industry (
  _id string,
  sic int,
  damodaran_industry string,
  mapping_version string,
  loaded_at timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (sic)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
