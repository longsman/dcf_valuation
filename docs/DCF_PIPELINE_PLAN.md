# Spec: Filing-Triggered Damodaran-Strict DCFs at Scale (Databricks + Delta + Superwind)

Date: 2026-01-13
Status: design/spec only (do not build yet)

This document is written as an **agent-executable spec**: data contracts, concrete calculation mechanics, pipeline assets to create, and operational rules (CDF, checkpointing, reruns).

Related context:
- `docs/PROJECT_STATE.md`
- `docs/PIPELINE_EQUITIES_TASK_MAP.md`
- `docs/SUPERWIND_DESIGN.md`

---

## 1) Decisions (locked for v1)

### 1.1 Triggers, keys, outputs
- Trigger: **new filings only** (10‑Q / 10‑K / 10‑QT)
- `valuation_date`: **run date**
- Canonical entity key: `cik` (string, 10-char zero-padded)
- Forecast horizon: **10-year fade** (years 1–10) + terminal
- Output format: **normalized per-year rows**

### 1.2 Two model tracks (no exclusions)
- `model_type='corporate'`: FCFF discounted at WACC
- `model_type='financial'`: equity model (FCFE-style) discounted at cost of equity

### 1.3 Market price policy
We will build a canonical price table used only for:
- market comparison (upside/downside), and
- optional market-weighted WACC / market cap diagnostics.

Price source: `silver.massive.snapshot_all_tickers`.

Price rule (v1):
- Prefer `last_trade.price` and set `price_date` from `last_trade.ts` aligned to America/New_York.
- Else fallback to `previous_day.close`.
- Store `price_method` so all joins are auditable.

### 1.4 Employee options / RSUs policy
- v1 omits option overhang and RSUs (EDGAR scale extraction is inconsistent)
- Output explicit omission flags (never silently assume zero dilution)

---

## 2) Non-negotiable Damodaran constraints (encoded as rules)

### 2.1 Terminal growth discipline
- Terminal growth must satisfy: `g_terminal <= rf` (same currency)
- v1 default: `g_terminal = rf`
  - This is the **maximum allowable** terminal growth under Damodaran’s constraint.
  - Produces higher terminal values than many practitioner defaults (often ~2–3%).
  - Treat as a ceiling / optimistic intrinsic value estimate.
- Optional conservative assumption set:
  - `g_terminal = min(rf, 0.03)` (explicitly conservative, not a Damodaran rule)

Rationale:
- Damodaran’s constraint is `g <= rf`. v1 defaults to the upper bound.
- If you want a margin-of-safety valuation, use the capped assumption set.

### 2.2 Terminal economics discipline
Corporate track:
- Terminal ROIC must converge to WACC by year 10 (unless an explicit moat assumption set exists).

Financial track:
- Terminal ROE converges to cost of equity by year 10.

### 2.3 Tax discipline
- Early years: effective tax rate proxy
- Terminal year: marginal tax rate

---

## 3) Operational model: Superwind + Delta + CDF

### 3.1 Implementation pattern
Each dataset is built as a Superwind YAML pipeline asset:
- DDL (`ddl.sql`) defines the Delta table contract.
- A SQL transform (`transform.sql`, or multiple files) computes rows.
- Superwind runs transforms via `ExecSQL` and persists via `MergeTable`.

### 3.2 CDF / checkpointing policy (addresses “startingVersion” fragility)
Delta Change Data Feed streaming typically requires either `startingVersion` or `startingTimestamp`.

**v1 policy:**
- Every CDF-reading pipeline must support *portable re-deploy/backfill* without editing YAML.
- Use `$ENV{...}` variables for start offsets.

Standard env vars (recommended):
- `CDF_STARTING_VERSION` (default `0`)
- `CDF_STARTING_TIMESTAMP` (optional alternative)

Checkpoint policy:
- Each streaming pipeline uses a stable checkpoint path under `s3://datsando-prod/pipeline_equities/checkpoints/...`.
- To do a full rebuild:
  1) set `CDF_STARTING_VERSION=0`
  2) delete / move the checkpoint directory (manual, user-controlled)
  3) rerun pipeline

The spec does not authorize agents to delete checkpoints without explicit user approval.

---

## 4) External / reference datasets required (gold)

Damodaran-strict DCF requires external parameters. We will materialize them as UC Delta tables so valuations are reproducible and as-of joins are explicit.

### 4.1 Required Damodaran tables
- `gold.damodaran.implied_erp` (monthly)
- `gold.damodaran.industry_betas` (annual)
- `gold.damodaran.ratings_spreads` (default spreads by rating; periodic)
- `gold.damodaran.synthetic_rating_bands` (interest coverage → rating; periodic)

### 4.2 Required mapping tables
- `gold.dim.sic_to_damodaran_industry` (manual/curated mapping; versioned)

### 4.3 Ingestion approach (v1)
Do not web-scrape in v1 unless necessary. Prefer:
- ship a CSV/YAML snapshot as a **package asset** (checked into git)
- load into Delta via a Superwind pipeline
- update snapshots manually on a cadence (monthly for ERP, annual for betas)

**Concrete deliverables (so day-1 runs don’t fail):**
- Add seed files under `pipeline_equities/src/pipeline_equities/assets/gold/seed/`:
  - `damodaran/implied_erp.csv`
  - `damodaran/industry_betas.csv`
  - `damodaran/ratings_spreads.csv`
  - `damodaran/synthetic_rating_bands.csv`
  - `dim/sic_to_damodaran_industry.csv`
  - `financials/tag_map.csv`
- Add one pipeline per table that loads the seed file and overwrites/merges the Delta table.

**Staleness policy (must be encoded in outputs):**
- In `gold.valuation.dcf_inputs`, persist `erp_as_of_date`, `spreads_as_of_date`, and `industry_beta_as_of_year`.
- Define staleness as: “as-of predates the applicable *mid-month refresh cutoff* (15th).”

  For monthly datasets (ERP and spreads):
  - `prior_month_cutoff = make_date(year(add_months(valuation_date, -1)), month(add_months(valuation_date, -1)), 15)`
  - `current_month_cutoff = make_date(year(valuation_date), month(valuation_date), 15)`
  - `applicable_cutoff = case when day(valuation_date) < 15 then prior_month_cutoff else current_month_cutoff end`
  - `stale_erp = (erp_as_of_date < applicable_cutoff)`
  - `stale_spreads = (spreads_as_of_date < applicable_cutoff)`

  For annual datasets (industry betas):
  - `stale_industry_beta = (industry_beta_as_of_year < year(valuation_date))`

- Staleness must never fail the pipeline; it only emits flags.

This keeps the system stable and avoids brittle HTML parsing, while still making stale reference inputs visible.

---

## 5) Gold table contracts (detailed)

All gold tables include:
- `_id string`
- `_footprint struct<upstream_id:string,create_ts:timestamp,modify_ts:timestamp>`

### 5.1 `gold.edgar.filing_events`
Purpose: canonical event queue of filings.

Keys:
- Merge keys: `(cik, accession_number)`

Columns:
- `cik string`
- `accession_number string`
- `filing_id string`
- `form_type string`
- `filed_date date`
- `link string`
- `source_updated timestamp`

### 5.2 `gold.dim.company`
Purpose: company routing + minimal metadata.

Key:
- `(cik)`

Columns:
- `cik string`
- `entity_name string`
- `sic int` (nullable)
- `is_financial boolean` (derived)
- `financial_class string` (nullable)

### 5.3 `gold.dim.cik_ticker`
Purpose: join EDGAR to market tickers.

Keys:
- `(cik, ticker)`

Columns:
- `cik string`
- `ticker string`
- `is_primary boolean`

### 5.4 `gold.market.prices_daily`
Purpose: canonical per-day price record per ticker.

### 5.4.1 `gold.market.trading_calendar` (placeholder for v1.1)
Purpose: explicit trading day calendar used to correctly align market prices to trading days (holidays, early closes, etc.).

Keys:
- `(market, trade_date)`

Columns:
- `market string` (e.g. `XNYS`, `XNAS`, `US`)
- `trade_date date`
- `is_trading_day boolean`
- `prev_trading_day date` (nullable)
- `next_trading_day date` (nullable)

v1 note:
- This table is not populated in v1; it exists to keep price-dating logic upgradeable without reworking downstream joins.

Keys:
- `(ticker, price_date)`

Columns:
- `ticker string`
- `price_date date`
- `close double`
- `price_method string` (`last_trade` | `previous_day_close`)
- `price_date_method string` (`trading_calendar` | `weekday_heuristic`)  # v1: always weekday_heuristic
- `last_trade_ts timestamp` (nullable)
- `source string`
- `source_snapshot_date date`

Weekend handling (v1):
- If fallback is `previous_day_close`, set `price_date` to the last weekday prior to `source_snapshot_date`:
  - if Monday: `date_sub(snapshot_date, 3)` else `date_sub(snapshot_date, 1)`

Holiday handling (deferred, but leave scaffolding):
- Add a placeholder table contract for `gold.market.trading_calendar` (v1.1):
  - `(market string, trade_date date, is_trading_day boolean, prev_trading_day date, next_trading_day date)`
- v1 emits explicit quality flags when price dating is unvalidated (see `gold.market.prices_daily.price_date_method` and `gold.valuation.dcf_inputs.quality_flags`).
- When available, replace the weekday-only heuristic with:
  - `price_date = coalesce(trading_calendar.prev_trading_day, weekday_heuristic_price_date)`

### 5.5 `gold.damodaran.implied_erp`
Keys:
- `(as_of_date)`

Columns:
- `as_of_date date` (month-end or publish date)
- `implied_erp double`
- `source_url string`
- `loaded_at timestamp`

Join rule:
- use `max(as_of_date) <= valuation_date`.

### 5.6 `gold.damodaran.industry_betas`
Keys:
- `(as_of_year, damodaran_industry)`

Columns (minimum):
- `as_of_year int`
- `damodaran_industry string`
- `unlevered_beta double`
- `d_e_ratio double` (industry average, used as target)
- `tax_rate double` (industry average or Damodaran’s assumption)
- `num_firms int`
- `source_url string`

### 5.7 `gold.damodaran.ratings_spreads`
Keys:
- `(as_of_date, rating)`

Columns:
- `as_of_date date`
- `rating string` (AAA, AA, A+, …)
- `default_spread double`

Join rule:
- use `max(as_of_date) <= valuation_date`.

### 5.8 `gold.damodaran.synthetic_rating_bands`
Keys:
- `(rating)`

Columns:
- `rating string`
- `min_interest_coverage double` (exclusive)
- `max_interest_coverage double` (inclusive)

### 5.9 `gold.dim.sic_to_damodaran_industry`
Keys:
- `(sic)`

Columns:
- `sic int`
- `damodaran_industry string`
- `mapping_version string`

### 5.10 `gold.financials.tag_map`
Purpose: explicit XBRL tag → canonical line item mapping.

Keys:
- `(line_item, source_taxonomy, source_tag)`

Columns:
- `line_item string`
- `source_taxonomy string` (e.g. us-gaap, dei)
- `source_tag string`
- `priority int`
- `is_flow boolean`
- `unit_allowlist array<string>` (nullable)
- `duration_months_allowlist array<int>` (nullable)

v1 policy:
- Always enforce `unit_allowlist` when present.
- For flow items, allowlist `duration_months` to `[3, 6, 9, 12]` (quarter/YTD/FY).
- Do not attempt sign normalization in v1; store values as reported and let later transforms decide whether to use `abs(...)` (with an explicit `sign_policy`).

**Proposed v1 seed content (validated against `silver.edgar.company_facts`):**

Flows (`is_flow=true`, `unit_allowlist=['USD']`, `duration_months_allowlist=[3,6,9,12]`)
- `revenue`
  - `us-gaap:Revenues` (priority 1)
  - `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` (2)
  - `us-gaap:SalesRevenueNet` (3)
  - `us-gaap:SalesRevenueGoodsNet` (4)
  - `us-gaap:SalesRevenueServicesNet` (5)
- `ebit`
  - `us-gaap:OperatingIncomeLoss` (1)
- `pretax_income`
  - `us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` (1)
  - `us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments` (2)
- `tax_expense`
  - `us-gaap:IncomeTaxExpenseBenefit` (1)
  - `us-gaap:IncomeTaxExpenseBenefitContinuingOperations` (2)
- `net_income`
  - `us-gaap:NetIncomeLoss` (1)
  - `us-gaap:ProfitLoss` (2)
  - `us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic` (3)
- `da`
  - `us-gaap:DepreciationDepletionAndAmortization` (1)
  - `us-gaap:DepreciationAndAmortization` (2)
  - `us-gaap:Depreciation` (3)
- `capex`
  - `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` (1)
  - `us-gaap:PaymentsToAcquireProductiveAssets` (2)
  - `us-gaap:PaymentsToAcquireIntangibleAssets` (3)
  - `us-gaap:PaymentsToAcquireSoftware` (4)
- `interest_expense`
  - `us-gaap:InterestExpense` (1)
  - `us-gaap:InterestExpenseDebt` (2)

Stocks (`is_flow=false`, `unit_allowlist=['USD']`, `duration_months_allowlist=null`)
- `cash`
  - `us-gaap:CashAndCashEquivalentsAtCarryingValue` (1)
  - `us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` (2)
  - `us-gaap:CashCashEquivalentsAndShortTermInvestments` (3)
- `current_assets`
  - `us-gaap:AssetsCurrent` (1)
- `current_liabilities`
  - `us-gaap:LiabilitiesCurrent` (1)
- `debt_st` (see note below re double-counting)
  - `us-gaap:DebtCurrent` (1)
  - `us-gaap:ShortTermBorrowings` (2)
  - `us-gaap:LongTermDebtCurrent` (3)
- `debt_lt`
  - `us-gaap:LongTermDebtNoncurrent` (1)
  - `us-gaap:LongTermDebt` (2)
  - `us-gaap:LongTermDebtAndCapitalLeaseObligations` (3)
- `book_equity`
  - `us-gaap:StockholdersEquity` (1)
  - `us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` (2)

Shares (optional, v1; `unit_allowlist=['shares']`)
- `shares_basic`
  - `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` (1) (flow, duration)
  - `dei:EntityCommonStockSharesOutstanding` (2) (stock, instant)
  - `us-gaap:CommonStockSharesOutstanding` (3) (stock, instant)
- `shares_diluted`
  - `us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding` (1) (flow, duration)

Debt composition rule (important):
- Do not compute `debt_st` by tag priority alone.
- Compute `debt_st` explicitly in `gold.financials.balance_quarterly` (or a dedicated downstream transform) to avoid double counting:
  - `debt_st = coalesce(nullif(DebtCurrent, 0), coalesce(ShortTermBorrowings, 0) + coalesce(LongTermDebtCurrent, 0))`
  - do not sum `DebtCurrent` with components (prevents double counting).
- If `debt_st` is computed from components (i.e., `DebtCurrent` missing/zero), add `debt_st_from_components` to `quality_flags`.

**Minimum line_items needed for v1 corporate**:
- flows: `revenue`, `ebit`, `pretax_income`, `tax_expense`, `net_income`, `da`, `capex`, `interest_expense`
- stock: `cash`, `current_assets`, `current_liabilities`, `debt_st`, `debt_lt`, `book_equity`

**Minimum line_items needed for v1 financial**:
- flows: `net_income`
- stock: `book_equity`

### 5.11 `gold.financials.statement_candidates` (optional but recommended)
Purpose: keep all candidate matches from XBRL → line_item mapping.

Keys:
- `(cik, line_item, period_end, fy, fp, unit_of_measure, accn, source_tag)`

Columns:
- everything needed to debug selection (val, filed, form, frame, selection_rank inputs)

### 5.12 `gold.financials.statement_lines`
Purpose: single selected value per (cik,line_item,period_end,fp,fy).

Keys (selected dataset):
- `(cik, line_item, period_end, fy, fp, unit_of_measure)`

Columns:
- `cik string`
- `line_item string`
- `period_start date`
- `period_end date`
- `fy int`
- `fp string`
- `val double`
- `unit_of_measure string`
- `filed date`
- `form string`
- `accn string`
- `frame string`
- `source_tag string`
- `source_taxonomy string`
- `selection_rank int`
- `is_restated boolean` (true if a newer filing replaces a prior selected value for same key)

Selection rule (dedup/restatement handling):
- Consider only candidates that pass unit/duration filters.
- Rank candidates by:
  1) lowest `priority`
  2) latest `filed`
  3) latest `accn` (tie-break)
- Select `row_number() = 1` per `(cik, line_item, period_end, fy, fp, unit_of_measure)`.
- If a newer filing replaces a prior selected value for the same key, set `is_restated=true`.

### 5.13 `gold.financials.flow_quarterly`
Purpose: true quarter values for flows (handles YTD reporting).

Keys:
- `(cik, line_item, fiscal_quarter_end)`

Columns:
- `cik string`
- `line_item string`
- `fiscal_quarter_end date`
- `fy int`
- `fp string` (Q1..Q4)
- `quarter_val double`
- `normalization_method string` (`direct_q` | `ytd_diff` | `fy_minus_ytd`)
- `normalization_quality string`
- `source_accn string`
- `source_filed date`

### 5.14 `gold.financials.flow_ttm`
Keys:
- `(cik, line_item, as_of_period_end)`

Columns:
- `cik string`
- `line_item string`
- `as_of_period_end date`
- `ttm_val double`
- `quarters_in_ttm int`

### 5.15 `gold.financials.balance_quarterly`
Purpose: point-in-time stock items by quarter end (needed for Δworking capital).

Keys:
- `(cik, line_item, period_end)`

Columns:
- `cik string`
- `line_item string`
- `period_end date`
- `val double`
- `filed date`
- `accn string`

### 5.16 `gold.financials.working_capital`
Purpose: computed non-cash working capital and YoY changes.

Keys:
- `(cik, as_of_period_end)`

Columns:
- `cik string`
- `as_of_period_end date`
- `current_assets double`
- `cash double`
- `current_liabilities double`
- `debt_st double`
- `non_cash_working_capital double`
- `non_cash_working_capital_yoy_change double` (vs same quarter end prior year)
- `quality_flags array<string>`

Definition:
- `non_cash_wc = (current_assets - cash) - (current_liabilities - debt_st)`

### 5.17 `gold.valuation.assumption_sets`
Keys:
- `(assumption_set_id)`

Columns (v1):
- `assumption_set_id string`
- `fade_years int` (10)
- `growth_fade_shape string` (`linear`)
- `terminal_growth_method string` (`rf` | `min_rf_3pct`)
- `terminal_roic_policy string` (`roic_to_wacc`)
- `tax_policy string` (`effective_to_marginal_linear`)
- `marginal_tax_rate double` (0.25)
- `wacc_weight_method string` (`target_de_ratio`)

v1 default assumption set:
- `assumption_set_id = 'damodaran_v1'`
- `terminal_growth_method = 'rf'`

Optional conservative assumption set:
- `assumption_set_id = 'damodaran_v1_conservative'`
- `terminal_growth_method = 'min_rf_3pct'`

### 5.18 `gold.valuation.dcf_inputs`
Keys:
- `(cik, valuation_date, assumption_set_id, source_accn, model_type)`

Common columns:
- identifiers: `cik`, `valuation_date`, `assumption_set_id`, `model_type`
- filing provenance: `source_accn`, `source_filed_date`, `as_of_period_end`
- flags: `has_minimum_inputs`, `missing_fields`, `quality_flags`, `options_omitted`, `rsus_omitted`

Definition of `has_minimum_inputs` (must be implemented exactly in SQL):
- Corporate:
  - `revenue_ttm is not null`
  - `ebit_ttm is not null`
  - `rf is not null`
  - `erp is not null`
  - `beta is not null` (post-relevering)
  - `growth_initial is not null`
- Financial:
  - `net_income_ttm is not null`
  - `book_equity_latest is not null and book_equity_latest > 0`
  - `rf is not null`
  - `erp is not null`
  - `beta is not null`
  - `growth_initial is not null`

`missing_fields` must be a deterministic array built from a fixed field list (no free-text).

`quality_flags` must be a deterministic array built from a fixed flag list (no free-text).

Canonical `quality_flags` values (v1):
- `stale_erp`
- `stale_spreads`
- `stale_industry_beta`
- `effective_tax_clamped`
- `roe_clamped`
- `wc_change_unavailable`
- `debt_st_from_components`
- `industry_beta_fallback`
- `price_date_unvalidated`
- `synthetic_rating_fallback`

Implementation pattern:
- `quality_flags = array_compact(array(case when <cond> then 'flag' end, ...))`
- No free-text flags and no dynamic concatenation.


Corporate minimum inputs (must exist to compute valuation):
- `revenue_ttm`, `ebit_ttm`
- `rf`, `erp`, `beta`
- `growth_initial`

Corporate optional-but-important:
- `tax_rate_effective`, `tax_rate_marginal`
- `capex_ttm`, `da_ttm`
- `non_cash_working_capital_yoy_change`
- `cash_latest`, `debt_st_latest`, `debt_lt_latest`
- `interest_expense_ttm` (for synthetic rating)

Corporate computed:
- `operating_margin = ebit_ttm / revenue_ttm`
- `nopat_ttm = ebit_ttm * (1 - tax_rate_effective)`
- `reinvestment_base_raw = (capex_ttm - da_ttm) + non_cash_working_capital_yoy_change`
- `reinvestment_base = coalesce(reinvestment_base_raw, (capex_ttm - da_ttm))`
- `wc_change_available = non_cash_working_capital_yoy_change is not null`
- `fcff_base = nopat_ttm - reinvestment_base`
- `interest_coverage = ebit_ttm / interest_expense_ttm` (guardrailed)
- `synthetic_rating`, `default_spread`, `cost_of_debt = rf + default_spread`
- `unlevered_beta` (from industry table)
- `target_de_ratio` (from industry table)
- `levered_beta = unlevered_beta * (1 + (1 - tax_rate_marginal)*target_de_ratio)`
- `cost_of_equity = rf + levered_beta * erp`
- `wacc` using target weights:
  - `E/(D+E) = 1/(1+target_de_ratio)`
  - `D/(D+E) = target_de_ratio/(1+target_de_ratio)`

Financial minimum inputs:
- `net_income_ttm`, `book_equity_latest`
- `rf`, `erp`, `beta`
- `growth_initial`

Financial computed:
- `roe_proxy = net_income_ttm / book_equity_latest`
- Guardrails:
  - if `book_equity_latest <= 0`: `has_minimum_inputs=false`
  - clamp `roe_proxy` into `[0, 0.25]` and flag if clamped (`roe_clamped` in `quality_flags`)
- `cost_of_equity = rf + beta * erp`

Market price join (best-effort):
- `ticker_primary`
- `market_price_date` (max `price_date` <= `valuation_date`)
- `market_price`, `market_price_method`
- `shares_basic_latest` (nullable)
- `market_cap = market_price * shares_basic_latest` (nullable)

### 5.19 `gold.valuation.dcf_cashflows`
Keys:
- `(cik, valuation_date, assumption_set_id, source_accn, model_type, year)`

Columns:
- `year int` (1..10, terminal row uses 11)
- `is_terminal boolean`
- `g_year double`
- `margin_year double`
- `roic_or_roe_year double`
- `revenue double` (nullable for financial track)
- `ebit double` (corporate)
- `nopat_or_net_income double`
- `reinvestment double`
- `fcf double` (FCFF or FCFE)
- `discount_rate double` (WACC or Ke)
- `discount_factor double`
- `pv double`

### 5.20 `gold.valuation.dcf_results`
Keys:
- `(cik, valuation_date, assumption_set_id, source_accn, model_type)`

Columns:
- `pv_explicit double`
- `pv_terminal double`
- `enterprise_value double` (corporate)
- `equity_value double` (corporate/financial)
- `value_per_share double` (nullable)
- `terminal_pct double`
- `upside_downside double` (nullable)
- flags: `has_minimum_inputs`, `missing_fields`

---

## 6) Pipeline specs (what assets to create)

For each asset below, create:
- `ddl.sql`
- `transform.sql`
- `pipeline.yaml`

Unless noted, these should be streaming + `available_now` to process deltas and stop.

### 6.1 `gold_edgar_filing_events`
Input: `silver.edgar.form10_filings_rss` (CDF)
Output: `gold.edgar.filing_events`

Transform steps:
- Filter `_change_type IN ('insert','update_postimage')`
- Filter `form_type IN ('10-Q','10-K','10-QT')`
- Select & normalize columns

### 6.2 `gold_dim_company`
Input: SEC company submissions JSON (recommended) OR derive minimal metadata from companyfacts headers.

If submissions ingestion is required:
- Add upstream silver tables:
  - `bronze.edgar.company_submissions` (raw JSON)
  - `silver.edgar.company_submissions` (parsed; includes SIC)
- Then populate `gold.dim.company`.

### 6.3 `gold_dim_cik_ticker`
Input: SEC company tickers mapping dataset
Output: `gold.dim.cik_ticker`

### 6.4 `gold_market_prices_daily`
Input: `silver.massive.snapshot_all_tickers`
Output: `gold.market.prices_daily`

Transform steps:
- For each ticker row:
  - if `last_trade.price` exists:
    - `close = last_trade.price`
    - `price_date = to_date(from_utc_timestamp(last_trade.ts,'America/New_York'))`
    - `price_method='last_trade'`
    - `price_date_method='weekday_heuristic'` (v1: unvalidated)
  - else:
    - `close = previous_day.close`
    - `price_date = previous_trading_weekday(snapshot_date)` (weekday-only heuristic)
    - future: swap to `gold.market.trading_calendar.prev_trading_day` when available
    - `price_method='previous_day_close'`
    - `price_date_method='weekday_heuristic'` (v1: unvalidated)

Downstream quality flagging:
- In `gold.valuation.dcf_inputs`, if `price_date_method = 'weekday_heuristic'`, add `price_date_unvalidated` to `quality_flags`.

### 6.5 Damodaran reference data pipelines
- `gold_damodaran_implied_erp`
- `gold_damodaran_industry_betas`
- `gold_damodaran_ratings_spreads`
- `gold_damodaran_synthetic_rating_bands`

v1 ingestion approach:
- load from package assets (CSV/YAML snapshots)
- update cadence:
  - ERP + spreads: monthly, with staleness evaluated mid-month (15th)
  - industry betas: annual

### 6.6 `gold_dim_sic_to_damodaran_industry`
Seed from a curated mapping asset.

### 6.7 `gold_financials_tag_map`
Seed from a curated mapping asset.

Seed file format (v1): `financials/tag_map.csv`
- This is a plain CSV checked into git and packaged as an asset.
- In Superwind YAML, resolve it via:
  - `$ASSET_PATH{pipeline_equities, pipeline_equities/assets/gold/seed/financials/tag_map.csv}`

Required CSV columns (header row):
- `line_item`
- `source_taxonomy`
- `source_tag`
- `priority`
- `is_flow`
- `unit_allowlist` (pipe-delimited string; empty means null)
- `duration_months_allowlist` (pipe-delimited ints; empty means null)

CSV parsing rules (must be implemented exactly):
- Treat empty strings as null for `unit_allowlist` and `duration_months_allowlist`.
- `unit_allowlist_array`:
  - `case when unit_allowlist is null or trim(unit_allowlist) = '' then null else transform(split(unit_allowlist, '\\|'), x -> trim(x)) end`
- `duration_months_allowlist_array`:
  - `case when duration_months_allowlist is null or trim(duration_months_allowlist) = '' then null else transform(split(duration_months_allowlist, '\\|'), x -> try_cast(trim(x) as int)) end`

Seed file validation (required):
- If `duration_months_allowlist` is non-empty, then `duration_months_allowlist_array` must contain no nulls.
- If validation fails, the seed load must error and report invalid `(line_item, source_taxonomy, source_tag)` rows.

Example rows (illustrative):
- `revenue,us-gaap,Revenues,1,true,USD,3|6|9|12`
- `ebit,us-gaap,OperatingIncomeLoss,1,true,USD,3|6|9|12`
- `cash,us-gaap,CashAndCashEquivalentsAtCarryingValue,1,false,USD,`
- `shares_basic,us-gaap,WeightedAverageNumberOfSharesOutstandingBasic,1,true,shares,3|6|9|12`
- `shares_basic,dei,EntityCommonStockSharesOutstanding,2,false,shares,`

CSV format spec:
- Encoding: UTF-8
- Delimiter: comma (`,`) with header row required
- Quote char: `"` when values contain commas/newlines
- `|` is reserved as array delimiter in allowlist fields

v1 note:
- The recommended seed content is specified in section `5.10 gold.financials.tag_map`.
- Keep the seed file as a static snapshot and update it as we find edge cases in `silver.edgar.company_facts`.

### 6.8 `gold_financials_statement_lines` (+ optional candidates)
Input: `silver.edgar.company_facts` (CDF)
Output: `gold.financials.statement_lines`

Transform steps:
- Join to `gold.financials.tag_map`
- Enforce unit allowlist when present
- Rank candidates by priority, then filed desc
- Output selected rows
- If emitting candidates table, output all matches with rank

### 6.9 `gold_financials_flow_quarterly`
Input: `gold.financials.statement_lines` (flow items)
Output: `gold.financials.flow_quarterly`

Transform steps:
- Choose latest filed per `(cik,line_item,fy,fp,period_end)`
- Normalize YTD quarters:
  - Q1: direct
  - Q2/Q3: ytd_diff
  - Q4: fy_minus_ytd
- Emit `normalization_quality` flags when prior YTD is missing

### 6.10 `gold_financials_flow_ttm`
Input: `gold.financials.flow_quarterly`
Output: `gold.financials.flow_ttm`

Transform steps:
- rolling sum of last 4 quarters
- emit `quarters_in_ttm`

### 6.11 `gold_financials_balance_quarterly`
Input: `gold.financials.statement_lines` (stock items)
Output: `gold.financials.balance_quarterly`

Transform steps:
- choose latest filed per `(cik,line_item,period_end)`

### 6.12 `gold_financials_working_capital`
Input: `gold.financials.balance_quarterly`
Output: `gold.financials.working_capital`

Transform steps:
- compute `non_cash_wc`
- compute YoY change vs same quarter end prior year

### 6.13 `gold_valuation_assumption_sets`
Seed a small Delta table.

### 6.14 `gold_valuation_dcf_inputs`
Driver: `gold.edgar.filing_events` (CDF)
Output: `gold.valuation.dcf_inputs`

Transform steps:
- Determine `as_of_period_end` from filing context (period end if available; else latest quarter end)
- Join required TTM flows ending at `as_of_period_end`:
  - revenue, ebit, pretax, taxes, net income, da, capex, interest expense
- Join balance_latest (cash/debt/book equity) and working capital YoY change
- Join `gold.dim.company` (is_financial)
- Join Damodaran params as-of `valuation_date`:
  - implied_erp
  - industry_betas + target_de_ratio
  - ratings_spreads + synthetic_rating_bands
- Join `gold.market.prices_daily`:
  - `cik -> ticker (primary)`
  - `ticker -> max(price_date <= valuation_date)`

Compute:
- effective tax proxy (guardrailed)
- marginal tax rate from assumption set
- beta lever/unlever per policy
- cost of equity
- synthetic rating + cost of debt
- WACC
- base-year FCFF/FCFE inputs

Quality flags (minimum required):
- `price_date_unvalidated` if the joined price row has `price_date_method='weekday_heuristic'`.

Emit `has_minimum_inputs`, a deterministic `missing_fields` list, and a deterministic `quality_flags` list.

### 6.15 `gold_valuation_dcf_cashflows`
Input: new rows from `gold.valuation.dcf_inputs` where `has_minimum_inputs=true`
Output: `gold.valuation.dcf_cashflows`

Transform steps:
- Generate years `1..fade_years` and compute fades:
  - growth fades linearly from `growth_initial` to `g_terminal`
  - corporate margin: hold constant v1 (explicitly) OR fade to industry target (v2)
  - corporate ROIC fades to WACC; financial ROE fades to Ke
- Compute reinvestment requirement:
  - corporate: `reinvestment_rate = g / roic_year`
  - financial: `reinvestment_rate = g / roe_year`
- Compute cashflows:
  - corporate: FCFF = NOPAT - reinvestment
  - financial: FCFE = NetIncome * (1 - reinvestment_rate)
- Terminal row:
  - corporate: `TV = FCFF_11 / (WACC - g_terminal)`
  - financial: `TV = FCFE_11 / (Ke - g_terminal)`
- Discount and compute PV.

### 6.16 `gold_valuation_dcf_results`
Input: `gold.valuation.dcf_cashflows`
Output: `gold.valuation.dcf_results`

Transform steps:
- Sum PV explicit and PV terminal
- Corporate bridge:
  - EV = pv_explicit + pv_terminal
  - Equity = EV + cash - debt (leases/options omitted v1)
  - Value/share = Equity / shares_basic (nullable)
- Financial:
  - Equity = pv_explicit + pv_terminal
  - Value/share as above
- Market comparison:
  - if market_price exists: upside/downside

---

## 7) Calculation mechanics (explicit formulas)

### 7.1 CIK normalization
Always treat `cik` as a 10-char string with left-zero padding.

### 7.2 Tax rate
- Effective tax proxy (corporate):
  - if `pretax_income_ttm > 0`: `tax_expense_ttm / pretax_income_ttm`
  - else: fallback to assumption-set marginal tax
- Clamp effective tax into `[0, 0.5]` and flag if clamped (`effective_tax_clamped` in `quality_flags`).
- Tax fade (linear):
  - `tax(year) = eff_tax + (marg_tax - eff_tax) * (year / fade_years)`

### 7.3 Cost of equity
- `Ke = rf + beta * erp`

ERP selection:
- use most recent `gold.damodaran.implied_erp.as_of_date <= valuation_date`.

### 7.4 Beta (bottom-up proxy)
- Lookup industry unlevered beta and target D/E:
  - map CIK→SIC→Damodaran industry
  - join to `gold.damodaran.industry_betas`

Fallback handling:
- Not all filers have SIC codes, and not all SICs map cleanly. If mapping fails, use a stable fallback:
  - `damodaran_industry = 'Total Market'`
  - add `industry_beta_fallback` to `quality_flags`
- Seed requirement: `gold.damodaran.industry_betas` must include `damodaran_industry='Total Market'` for each `as_of_year`, with:
  - `unlevered_beta = 1.0`
  - `d_e_ratio = 0.30`
  - `tax_rate = 0.25`

- Relever:
  - `β_levered = β_unlevered * (1 + (1 - marg_tax) * target_de_ratio)`

### 7.5 Cost of debt (synthetic rating)
- Interest coverage:
  - `icr = ebit_ttm / interest_expense_ttm` (if interest_expense_ttm>0)
- Synthetic rating:
  - join `gold.damodaran.synthetic_rating_bands` where `min < icr <= max`
- Default spread:
  - join `gold.damodaran.ratings_spreads` for that rating as-of date
- `Kd = rf + default_spread`

Fallbacks:
- If interest expense missing or <=0:
  - set `Kd = null`, `default_spread = null`, and treat WACC = Ke under target weights (i.e., D=0).
  - add `synthetic_rating_fallback` to `quality_flags`.

### 7.6 Corporate base-year FCFF
- `NOPAT = EBIT * (1 - eff_tax)`
- `Reinvestment_base_raw = (CapEx_TTM - DA_TTM) + ΔNonCashWC_YoY`
- `Reinvestment_base = coalesce(Reinvestment_base_raw, (CapEx_TTM - DA_TTM))`
- `FCFF_base = NOPAT - Reinvestment_base`
- Emit `wc_change_available` and flag if WC is missing (`wc_change_unavailable` in `quality_flags`)

### 7.7 Growth initialization
- `growth_initial` is computed from history when available:
  - corporate: YoY change of `revenue_ttm` at same quarter end
  - financial: YoY change of `net_income_ttm` (guardrailed)
- If not available:
  - fallback to an assumption-set default (store explicitly in `missing_fields`)

### 7.8 Corporate projection mechanics
For each year 1..10:
- `g_year = linear_fade(g0, g_terminal)`
- `margin_year = margin0` (v1)
- `revenue_year = revenue_{year-1} * (1 + g_year)`
- `ebit_year = revenue_year * margin_year`
- `tax_year = tax_fade(eff_tax, marg_tax)`
- `nopat_year = ebit_year * (1 - tax_year)`
- `roic_year = linear_fade(roic0, wacc)`
- `reinvestment_rate = g_year / roic_year` (guardrailed)
- `reinvestment = nopat_year * reinvestment_rate`
- `fcff = nopat_year - reinvestment`

Terminal year:
- `roic_terminal = wacc`
- `reinvestment_rate_terminal = g_terminal / roic_terminal`
- `fcff_11 = nopat_11 * (1 - reinvestment_rate_terminal)`
- `TV = fcff_11 / (wacc - g_terminal)`

### 7.9 Financial projection mechanics
Guardrails:
- If `book_equity_latest <= 0`, do not produce a financial valuation (`has_minimum_inputs=false`).
- Clamp `roe0`/`roe_year` to `[0, 0.25]` and flag if clamped.

Projection:
- `roe_year = linear_fade(roe0, ke)`
- `reinvestment_rate = g_year / roe_year` (guardrailed)
- `fcfe = net_income_year * (1 - reinvestment_rate)`
- `TV = fcfe_11 / (ke - g_terminal)`

---

## 8) Validation / acceptance criteria (agent checklist)

### 8.1 Table-level checks
For each gold table:
- primary key uniqueness
- required column null-rate thresholds
- incremental behavior (rows increase only when filings arrive)

### 8.2 Financial sanity checks
- Require `ke > g_terminal` and `wacc > g_terminal` for terminal value
- Flag extreme values:
  - `terminal_pct > 0.95`
  - `wacc < rf` or `ke < rf`
  - negative or >100% margins

### 8.3 Provenance checks
- Every valuation row must store:
  - `source_accn`, `source_filed_date`, `as_of_period_end`
  - `assumption_set_id`
  - `erp_as_of_date`, `industry_beta_as_of_year`, `spreads_as_of_date` (recommended)

---

## 9) Job graph (Workflows) — how to schedule

Preferred: extend existing `pipeline_equities` job by appending gold tasks.

Proposed DAG order:
1) existing silver ingestion tasks
2) gold events/dims + damodaran reference tables + prices
3) gold financial normalization (statement_lines → quarterly/TTM/balances/WC)
4) gold valuation artifacts (inputs → cashflows → results)

Every task is a `python_wheel_task` calling `superwind exec_superwind`.

---

## 10) Future enhancements (explicitly deferred)

- Trading calendar / holiday-aware price dating
- Employee options/RSUs extraction and option valuation
- R&D capitalization
- Operating lease capitalization
- Acquisition reinvestment normalization
- Currency consistency for ADRs/foreign filers
- Multi-segment beta weighting by estimated segment value
