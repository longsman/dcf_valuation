-- gold.financials.flow_quarterly
-- Purpose: True quarter values for flow items (handles YTD reporting)
-- Keys: (cik, line_item, fiscal_quarter_end)

create table if not exists gold.financials.flow_quarterly (
  _id string,
  cik string,
  line_item string,
  fiscal_quarter_end date,
  fy int,
  fp string,
  quarter_val double,
  normalization_method string,
  normalization_quality string,
  source_accn string,
  source_filed date,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, line_item, fiscal_quarter_end)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
