-- gold.edgar.filing_events
-- Purpose: Canonical event queue of 10-K/10-Q/10-QT filings
-- Keys: (cik, accession_number)

create table if not exists gold.edgar.filing_events (
  _id string,
  cik string,
  accession_number string,
  filing_id string,
  form_type string,
  filed_date date,
  link string,
  source_updated timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, accession_number, filed_date)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
