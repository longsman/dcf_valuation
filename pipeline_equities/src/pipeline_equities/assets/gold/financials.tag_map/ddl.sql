-- gold.financials.tag_map
-- Purpose: XBRL tag to canonical line item mapping
-- Keys: (line_item, source_taxonomy, source_tag)

create table if not exists gold.financials.tag_map (
  _id string,
  line_item string,
  source_taxonomy string,
  source_tag string,
  priority int,
  is_flow boolean,
  unit_allowlist array<string>,
  duration_months_allowlist array<int>,
  loaded_at timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (line_item, source_taxonomy, source_tag)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
