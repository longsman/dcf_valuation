create table if not exists bronze.edgar.form10_filings_rss (
  _id string,
  guidislink boolean,
  id string,
  link string,
  links array<string>,
  summary string,
  summary_detail string,
  tags array<string>,
  title string,
  title_detail string,
  updated string,
  updated_parsed array<long>,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (_id, id, updated)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
