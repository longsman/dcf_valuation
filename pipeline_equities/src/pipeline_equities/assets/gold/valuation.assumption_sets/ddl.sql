-- gold.valuation.assumption_sets
-- Purpose: DCF model assumption sets
-- Keys: (assumption_set_id)

create table if not exists gold.valuation.assumption_sets (
  _id string,
  assumption_set_id string,
  fade_years int,
  growth_fade_shape string,
  terminal_growth_method string,
  terminal_roic_policy string,
  tax_policy string,
  marginal_tax_rate double,
  wacc_weight_method string,
  _footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (assumption_set_id)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
