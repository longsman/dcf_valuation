-- gold.dim.company
-- Purpose: Company dimension with routing metadata
-- Keys: (cik)

create table if not exists gold.dim.company (
  _id string,
  cik string,
  entity_name string,
  sic int,
  is_financial boolean,
  financial_class string,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
