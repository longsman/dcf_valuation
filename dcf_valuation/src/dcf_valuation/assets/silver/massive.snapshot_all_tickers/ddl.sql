create table if not exists silver.massive.snapshot_all_tickers (
	_id string,
	ticker string,
	snapshot_date date,
	todays_change_percent double,
	todays_change double,
	updated_ts timestamp,
	day struct<open:float,high:float,low:float,close:float,volume:float,volume_weighted:float,otc:boolean>,
	last_quote struct<ask_price:float,ask_size:int,bid_price:float,bid_size:int,ts:timestamp>,
	last_trade struct<conditions:array<string>,trade_id:string,price:float,size:int,ts:timestamp,exchange_id:int>,
	min struct<accumulated_volume:float,close:float,high:float,low:float,num_transactions:int,open:float,otc:boolean,ts:timestamp,volume:float,volume_weighted:float>,
	previous_day struct<close:float,high:float,low:float,open:float,otc:boolean,volume:float,volume_weighted:float>,
	_footprint struct<upstream_id: string, create_ts: timestamp, modify_ts: timestamp>
)
cluster by (_id, ticker, snapshot_date)
tblproperties(
  'delta.autoOptimize.autoCompact' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed' = 'true'
);
