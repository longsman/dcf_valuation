-- gold.damodaran.industry_betas
-- Purpose: Damodaran industry unlevered betas and D/E ratios by year
-- Keys: (as_of_year, damodaran_industry)

create table if not exists gold.damodaran.industry_betas (
  _id string,
  as_of_year int,
  damodaran_industry string,
  unlevered_beta double,
  d_e_ratio double,
  tax_rate double,
  num_firms int,
  source_url string,
  loaded_at timestamp,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (as_of_year, damodaran_industry)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
