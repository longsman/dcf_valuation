create table if not exists bronze.fred.series_observations (
  _id string,
  series_id string,
  realtime_start date,
  realtime_end date,
  observation_date date,
  value decimal(38, 2),
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (_id, series_id, observation_date, _footprint.modify_ts)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
