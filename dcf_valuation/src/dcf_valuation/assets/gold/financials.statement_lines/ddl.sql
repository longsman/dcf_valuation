-- gold.financials.statement_lines
-- Purpose: Single selected value per (cik, line_item, period_end, fy, fp)
-- Keys: (cik, line_item, period_end, fy, fp, unit_of_measure)

create table if not exists gold.financials.statement_lines (
  _id string,
  cik string,
  line_item string,
  period_start date,
  period_end date,
  fy int,
  fp string,
  val double,
  unit_of_measure string,
  filed date,
  form string,
  accn string,
  frame string,
  source_tag string,
  source_taxonomy string,
  selection_rank int,
  is_restated boolean,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (cik, line_item, period_end, fy, fp)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
