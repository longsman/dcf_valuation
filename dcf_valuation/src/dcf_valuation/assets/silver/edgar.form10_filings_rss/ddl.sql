create table if not exists silver.edgar.form10_filings_rss (
  _id string,
  filing_id string,
  accession_number string,
  cik string,
  link string,
  filed_date date,
  form_type string,
  title string,
  updated timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (_id, cik, filing_id, filed_date)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
