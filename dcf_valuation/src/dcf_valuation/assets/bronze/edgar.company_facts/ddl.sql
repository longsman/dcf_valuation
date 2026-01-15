create table if not exists bronze.edgar.company_facts (
  _id string,
  cik string,
  content string,
  accession_number string,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (_id, cik, accession_number, _footprint.modify_ts)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
