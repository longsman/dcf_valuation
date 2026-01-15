create table if not exists silver.edgar.company_facts (
  _id string,
  cik string,
  entity_name string,
  taxonomy string,
  tag string,
  label string,
  description string,
  unit_of_measure string,
  val double,
  accn string,
  start date,
  end date,
  fy int,
  fp string,
  filed date,
  form string,
  frame string,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (_id, cik, taxonomy, tag)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'false',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true',
  'delta.checkpointPolicy' = 'classic',
  'delta.enableDeletionVectors' = 'false'
);
