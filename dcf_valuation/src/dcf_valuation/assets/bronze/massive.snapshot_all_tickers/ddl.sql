CREATE TABLE bronze.massive.snapshot_all_tickers (
  _id STRING,
  snapshot_date DATE,
  access_ts TIMESTAMP,
  headers STRING,
  content BINARY,
  _footprint STRUCT<upstream_id: STRING, create_ts: TIMESTAMP, modify_ts: TIMESTAMP>
)
USING delta
CLUSTER BY (_id, snapshot_date, access_ts, _footprint.modify_ts)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
