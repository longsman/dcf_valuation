-- gold.financials.balance_quarterly
-- Purpose: Point-in-time stock items by quarter end
-- Keys: (cik, line_item, period_end)

create table if not exists gold.financials.balance_quarterly (
  _id string,
  cik string,
  line_item string,
  period_end date,
  val double,
  filed date,
  accn string,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, line_item, period_end)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
