"""
Amazon (AMZN) DCF Valuation - Damodaran Methodology
====================================================
Author: DCF Analysis
Date: November 2025
Data Sources: SEC 10-K (FY2024), 10-Q (Q3 2025), Damodaran's NYU datasets
"""

print("=" * 80)
print("AMAZON (AMZN) DCF VALUATION - DAMODARAN METHODOLOGY")
print("=" * 80)

# =============================================================================
# SECTION 1: RAW DATA FROM SEC FILINGS
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 1: BASE DATA FROM SEC FILINGS (FY2024 10-K, Q3 2025 10-Q)")
print("=" * 80)

# Income Statement - FY2024 (in millions)
revenue = 637_959
operating_income_reported = 68_593  # EBIT
tech_infrastructure_2024 = 88_544  # R&D proxy
interest_expense = 2_406
sbc_expense = 22_011  # Stock-based compensation (DO NOT add back per Damodaran)
depreciation_amortization = 52_795

# Balance Sheet - Q3 2025 (in millions)
cash_and_equivalents = 66_922
marketable_securities = 27_275
total_cash = cash_and_equivalents + marketable_securities  # 94,197

short_term_debt = 3_997
long_term_debt = 50_742
total_debt = short_term_debt + long_term_debt  # 54,739

current_assets = 196_866
current_liabilities = 195_196

# Operating Lease Data
operating_lease_liability = 86_233  # Already on balance sheet (ASC 842)

# Shares & Stock Price
shares_outstanding = 10_690  # in millions
stock_price = 229.16
market_cap = shares_outstanding * stock_price  # in millions

# RSU Data for option value calculation
rsu_outstanding = 268.1  # million units
rsu_avg_fair_value = 168  # weighted average grant-date fair value

# Tax Rates
effective_tax_rate_2024 = 0.135  # FY2024: 13.5%
effective_tax_rate_2025 = 0.20  # YTD 2025: 20% (new tax law)
marginal_tax_rate = 0.25  # US statutory rate for terminal value

# Capital Expenditures - FY2024
capex = 82_999

print(f"""
Income Statement (FY2024):
  Revenue:                    ${revenue:,.0f}M
  Operating Income (EBIT):    ${operating_income_reported:,.0f}M
  Tech & Infrastructure:      ${tech_infrastructure_2024:,.0f}M
  Interest Expense:           ${interest_expense:,.0f}M
  D&A:                        ${depreciation_amortization:,.0f}M
  Stock-Based Comp:           ${sbc_expense:,.0f}M

Balance Sheet (Q3 2025):
  Cash + Marketable Sec:      ${total_cash:,.0f}M
  Total Debt:                 ${total_debt:,.0f}M
  Operating Lease Liability:  ${operating_lease_liability:,.0f}M

Market Data:
  Shares Outstanding:         {shares_outstanding:,.0f}M
  Stock Price:                ${stock_price:,.2f}
  Market Cap:                 ${market_cap:,.0f}M
  RSUs Outstanding:           {rsu_outstanding:,.1f}M units
""")

# =============================================================================
# SECTION 2: R&D CAPITALIZATION (DAMODARAN ADJUSTMENT)
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 2: R&D CAPITALIZATION ADJUSTMENT")
print("=" * 80)

# Historical Tech & Infrastructure Expense (R&D proxy)
rd_history = {2024: 88_544, 2023: 85_622, 2022: 73_213, 2021: 56_052, 2020: 42_740}

# Assumption: 3-year amortization life (Damodaran often uses ~2–3 years for software/internet)
amortization_life = 3

# Calculate Research Asset using Damodaran's formula:
# Research Asset = Sum of [R&D(t-i) * (1 - i/n)] for i = 0 to n-1
# Current year = 100%, Year-1 = 66.7%, Year-2 = 33.3%

research_asset = 0
amortization_schedule = []

for i, year in enumerate([2024, 2023, 2022]):
    if i < amortization_life:
        unamortized_pct = 1 - (i / amortization_life)
        contribution = rd_history[year] * unamortized_pct
        research_asset += contribution
        amortization_schedule.append(
            {
                "Year": year,
                "R&D Expense": rd_history[year],
                "Unamortized %": f"{unamortized_pct:.1%}",
                "Contribution to Asset": contribution,
            }
        )

# Calculate R&D amortization (what we subtract from adjusted EBIT)
# Amortization = Sum of each year's R&D / amortization_life
rd_amortization = sum(rd_history[y] for y in [2024, 2023, 2022]) / amortization_life

print("\nR&D Capitalization Schedule (3-year amortizable life):")
print("-" * 60)
print(
    f"{'Year':>6} {'R&D Expense':>15} {'Unamortized %':>14} {'Contribution to Asset':>22}"
)
for row in amortization_schedule:
    print(
        f"{row['Year']:>6} {row['R&D Expense']:>15,.0f} {row['Unamortized %']:>14} {row['Contribution to Asset']:>22,.0f}"
    )
print(f"\nResearch Asset Value:      ${research_asset:,.0f}M")
print(f"R&D Amortization (annual): ${rd_amortization:,.0f}M")

# Adjusted EBIT = Reported EBIT + Current R&D - R&D Amortization
adjusted_ebit = operating_income_reported + tech_infrastructure_2024 - rd_amortization

print(f"""
Adjusted EBIT Calculation:
  Reported EBIT:              ${operating_income_reported:,.0f}M
  + Current R&D Expense:      ${tech_infrastructure_2024:,.0f}M
  - R&D Amortization:         ${rd_amortization:,.0f}M
  ─────────────────────────────────────
  Adjusted EBIT:              ${adjusted_ebit:,.0f}M
""")

# =============================================================================
# SECTION 3: OPERATING LEASE ADJUSTMENT
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 3: OPERATING LEASE ADJUSTMENT")
print("=" * 80)

# Under ASC 842, leases are already capitalized on Amazon's balance sheet
# The lease liability of $86,233M is already included
# For Damodaran's approach, we verify and use this directly

# Future lease payments schedule (from 10-K)
lease_schedule = {
    2025: 12_002,
    2026: 11_023,
    2027: 10_087,
    2028: 9_205,
    2029: 8_534,
    "Thereafter": 44_443,  # ~5.2 years at year-5 rate
}

# Pre-tax cost of debt for discounting
pre_tax_cost_of_debt = 0.0461  # 4.01% Rf + 0.60% spread

# Weighted average lease term
avg_lease_term = 10.0  # years

# Depreciation of leased asset = Lease Liability / Avg Lease Term
lease_depreciation = operating_lease_liability / avg_lease_term

# Current lease expense (approximated from cash paid)
current_lease_expense = 12_341

# Adjusted EBIT impact: Add back lease expense, subtract depreciation
# But since we're starting from Operating Income which already excludes
# the operating component of lease expense (per ASC 842), the adjustment
# is primarily for adding the debt to our capital structure

print(f"""
Operating Lease Data (ASC 842 - already capitalized):
  Operating Lease Liability:  ${operating_lease_liability:,.0f}M
  Avg Remaining Lease Term:   {avg_lease_term:.1f} years
  Implied Lease Depreciation: ${lease_depreciation:,.0f}M/year
  
For WACC calculation, treat Operating Lease Liability as DEBT.
Total Debt-Equivalent:        ${total_debt + operating_lease_liability:,.0f}M
""")

# =============================================================================
# SECTION 4: COST OF CAPITAL (WACC)
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 4: COST OF CAPITAL (WACC)")
print("=" * 80)

# Market Data
risk_free_rate = 0.0401  # 10-year Treasury (Nov 2025)
equity_risk_premium = 0.0425  # Damodaran implied ERP (Nov 2025)

# Sector betas from Damodaran (Unlevered)
beta_retail_online = 1.34
beta_software_internet = 1.56  # AWS proxy
beta_advertising = 1.12

# Amazon's business mix by OPERATING INCOME (more relevant than revenue)
# AWS: 58%, North America Retail: 36%, International: 6%
# Advertising is embedded in NA/International segments

# Weight by operating income since that's what drives value
weight_aws = 0.58
weight_retail = 0.42  # Combined NA + International retail

# Calculate weighted unlevered beta
unlevered_beta = (
    weight_aws * beta_software_internet + weight_retail * beta_retail_online
)

print(f"""
Beta Calculation (Bottom-Up Approach):

Sector Betas (Damodaran Jan 2025 data):
  Retail (Online):            {beta_retail_online}
  Software (Internet/AWS):    {beta_software_internet}
  
Amazon Operating Income Mix:
  AWS:                        {weight_aws:.0%} (at 37% margin)
  Retail (NA + Int'l):        {weight_retail:.0%} (at 5.4% margin)
  
Weighted Unlevered Beta:      {unlevered_beta:.3f}
""")

# Calculate capital structure for relevering
# Total debt includes operating leases (Damodaran treatment)
total_debt_with_leases = total_debt + operating_lease_liability
equity_value = market_cap

debt_to_equity = total_debt_with_leases / equity_value

# Relever the beta: Levered Beta = Unlevered Beta * [1 + (1-t)(D/E)]
levered_beta = unlevered_beta * (1 + (1 - marginal_tax_rate) * debt_to_equity)

print(f"""
Capital Structure (Market Values):
  Market Cap (Equity):        ${equity_value:,.0f}M
  Total Debt + Leases:        ${total_debt_with_leases:,.0f}M
  Debt/Equity Ratio:          {debt_to_equity:.3f}
  
Relevering Beta:
  Unlevered Beta:             {unlevered_beta:.3f}
  Levered Beta = {unlevered_beta:.3f} * [1 + (1-{marginal_tax_rate}) * {debt_to_equity:.3f}]
  Levered Beta:               {levered_beta:.3f}
""")

# Cost of Equity (CAPM)
cost_of_equity = risk_free_rate + levered_beta * equity_risk_premium

# Cost of Debt
default_spread = 0.006  # 60 bps for AA rating
pre_tax_cost_of_debt = risk_free_rate + default_spread
after_tax_cost_of_debt = pre_tax_cost_of_debt * (1 - marginal_tax_rate)

# Capital weights
total_capital = equity_value + total_debt_with_leases
weight_equity = equity_value / total_capital
weight_debt = total_debt_with_leases / total_capital

# WACC
wacc = weight_equity * cost_of_equity + weight_debt * after_tax_cost_of_debt

print(f"""
Cost of Equity (CAPM):
  Risk-Free Rate:             {risk_free_rate:.2%}
  Equity Risk Premium:        {equity_risk_premium:.2%}
  Levered Beta:               {levered_beta:.3f}
  Cost of Equity:             {risk_free_rate:.2%} + {levered_beta:.3f} * {equity_risk_premium:.2%} = {cost_of_equity:.2%}

Cost of Debt:
  Risk-Free Rate:             {risk_free_rate:.2%}
  Default Spread (AA):        {default_spread:.2%}
  Pre-tax Cost of Debt:       {pre_tax_cost_of_debt:.2%}
  After-tax Cost of Debt:     {after_tax_cost_of_debt:.2%}

WACC Calculation:
  Weight of Equity:           {weight_equity:.2%}
  Weight of Debt:             {weight_debt:.2%}
  WACC = {weight_equity:.2%} * {cost_of_equity:.2%} + {weight_debt:.2%} * {after_tax_cost_of_debt:.2%}
  
  ══════════════════════════════════════
  WACC:                       {wacc:.2%}
  ══════════════════════════════════════
""")

# =============================================================================
# SECTION 5: BASE YEAR FCFF & INVESTED CAPITAL
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 5: BASE YEAR FREE CASH FLOW TO FIRM (FCFF)")
print("=" * 80)

# Use effective tax rate for Year 0, transitioning to marginal later
tax_rate_y0 = effective_tax_rate_2025  # 20% (new tax law)

# After-tax operating income
nopat = adjusted_ebit * (1 - tax_rate_y0)

# Adjusted CapEx = Accounting CapEx + R&D (since we capitalized it)
# But we already added R&D back to EBIT, so CapEx = accounting capex + R&D capitalized
adjusted_capex = capex + tech_infrastructure_2024

# Net CapEx = CapEx - D&A (including R&D amortization)
adjusted_da = depreciation_amortization + rd_amortization
net_capex = adjusted_capex - adjusted_da

# Working Capital Change (using balance sheet data)
# Non-cash WC = (Current Assets - Cash) - (Current Liabilities - Short-term Debt)
non_cash_current_assets = current_assets - total_cash
non_cash_current_liabilities = current_liabilities - short_term_debt
working_capital = non_cash_current_assets - non_cash_current_liabilities

# For base year, estimate delta WC as % of revenue change
# Historical: WC tends to be negative for Amazon (collects before paying)
wc_as_pct_revenue = working_capital / revenue
delta_wc_y0 = revenue * 0.11 * wc_as_pct_revenue  # Assume 11% rev growth, same WC ratio

# Reinvestment
reinvestment = net_capex + delta_wc_y0

# FCFF
fcff_y0 = nopat - reinvestment

# Invested Capital (for ROIC calculation)
# Book Equity + Total Debt + Operating Leases - Cash + Research Asset
# Or: Fixed Assets + Working Capital + Research Asset
invested_capital = (
    total_debt_with_leases
    + 369_631  # Stockholders equity
    + research_asset
    - total_cash
)

roic = nopat / invested_capital

print(f"""
Base Year Calculations (FY2024 Adjusted):

After-Tax Operating Income (NOPAT):
  Adjusted EBIT:              ${adjusted_ebit:,.0f}M
  Tax Rate (effective):       {tax_rate_y0:.1%}
  NOPAT:                      ${nopat:,.0f}M

Capital Expenditures (Adjusted for R&D):
  Accounting CapEx:           ${capex:,.0f}M
  + R&D Investment:           ${tech_infrastructure_2024:,.0f}M
  Total CapEx:                ${adjusted_capex:,.0f}M
  
  D&A:                        ${depreciation_amortization:,.0f}M
  + R&D Amortization:         ${rd_amortization:,.0f}M
  Total D&A:                  ${adjusted_da:,.0f}M
  
  Net CapEx:                  ${net_capex:,.0f}M

Working Capital:
  Non-Cash Current Assets:    ${non_cash_current_assets:,.0f}M
  Non-Cash Current Liab:      ${non_cash_current_liabilities:,.0f}M
  Working Capital:            ${working_capital:,.0f}M
  WC as % of Revenue:         {wc_as_pct_revenue:.1%}
  Delta WC (estimated):       ${delta_wc_y0:,.0f}M

Reinvestment:
  Net CapEx + Delta WC:       ${reinvestment:,.0f}M
  Reinvestment Rate:          {reinvestment / nopat:.1%}

FCFF (Base Year):
  NOPAT:                      ${nopat:,.0f}M
  - Reinvestment:             ${reinvestment:,.0f}M
  ─────────────────────────────────────
  FCFF:                       ${fcff_y0:,.0f}M

Invested Capital & ROIC:
  Invested Capital:           ${invested_capital:,.0f}M
  ROIC:                       {roic:.1%}
""")

# =============================================================================
# SECTION 6: GROWTH ASSUMPTIONS & FCFF PROJECTIONS
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 6: GROWTH ASSUMPTIONS & 10-YEAR FCFF PROJECTION")
print("=" * 80)

# Growth Assumptions (per Damodaran: g = Reinvestment Rate * ROIC)
# Amazon's historical 3-yr CAGR: ~10.6%
# AWS growing faster (~17%), Retail slower (~7%)

# Year 1-3: Higher growth (AWS momentum, AI investments)
# Year 4-7: Moderating growth (market maturation)
# Year 8-10: Transition to stable growth
# Terminal: Risk-free rate cap (4.01%)

growth_rates = [0.12, 0.11, 0.10, 0.09, 0.08, 0.07, 0.06, 0.05, 0.045, 0.04]
terminal_growth = risk_free_rate  # 4.01% - Damodaran's cap

# Tax rate transition: Effective -> Marginal
tax_rates = [0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.25, 0.25, 0.25, 0.25]

# ROIC assumptions: Currently ~17.6%, converging toward WACC (~9%)
# Allow premium ROIC due to AWS moat (but declining)
roic_path = [0.17, 0.16, 0.15, 0.14, 0.13, 0.12, 0.11, 0.10, 0.095, 0.09]

# Terminal ROIC = WACC (competitive advantages erode)
terminal_roic = wacc

print(f"""
Growth & ROIC Assumptions:
─────────────────────────────────────────────────────────────────────
Year    Revenue Growth    Tax Rate    ROIC    Reinvest Rate (g/ROIC)
─────────────────────────────────────────────────────────────────────""")
for i, (g, t, r) in enumerate(zip(growth_rates, tax_rates, roic_path), 1):
    reinv_rate = g / r
    print(f"{i:4d}    {g:12.1%}    {t:8.1%}    {r:5.1%}    {reinv_rate:18.1%}")
print(
    f"Term    {terminal_growth:12.2%}    {marginal_tax_rate:8.1%}    {terminal_roic:5.2%}    {terminal_growth / terminal_roic:18.1%}"
)
print("─────────────────────────────────────────────────────────────────────")

# Build projection
projections = []
prev_revenue = revenue
prev_ebit = adjusted_ebit

for year in range(1, 11):
    g = growth_rates[year - 1]
    t = tax_rates[year - 1]
    r = roic_path[year - 1]

    # Revenue projection
    proj_revenue = prev_revenue * (1 + g)

    # Operating margin assumption: Improving due to AWS mix shift
    # Base margin ~24.5% (adjusted EBIT/Revenue), slowly improving
    base_margin = adjusted_ebit / revenue
    margin_improvement = 0.002 * year if year <= 5 else 0.01  # Small margin expansion
    proj_margin = min(base_margin + margin_improvement, 0.30)  # Cap at 30%

    proj_ebit = proj_revenue * proj_margin
    proj_nopat = proj_ebit * (1 - t)

    # Reinvestment = g / ROIC * NOPAT
    reinvest_rate = g / r
    proj_reinvestment = proj_nopat * reinvest_rate

    # FCFF
    proj_fcff = proj_nopat - proj_reinvestment

    projections.append(
        {
            "Year": year,
            "Revenue": proj_revenue,
            "Growth": g,
            "EBIT": proj_ebit,
            "Margin": proj_margin,
            "Tax Rate": t,
            "NOPAT": proj_nopat,
            "ROIC": r,
            "Reinvest Rate": reinvest_rate,
            "Reinvestment": proj_reinvestment,
            "FCFF": proj_fcff,
        }
    )

    prev_revenue = proj_revenue
    prev_ebit = proj_ebit

# Convenience lists
fcff_projection = [row["FCFF"] for row in projections]

print("\n10-YEAR FCFF PROJECTION ($ in millions)")
print("=" * 120)
print(
    f"{'Year':>4} {'Revenue':>12} {'Growth':>8} {'EBIT':>12} {'Margin':>8} {'Tax':>6} {'NOPAT':>12} {'Reinvest':>12} {'FCFF':>12}"
)
print("-" * 120)
for row in projections:
    print(
        f"{row['Year']:>4d} {row['Revenue']:>12,.0f} {row['Growth']:>8.1%} {row['EBIT']:>12,.0f} {row['Margin']:>8.1%} {row['Tax Rate']:>6.0%} {row['NOPAT']:>12,.0f} {row['Reinvestment']:>12,.0f} {row['FCFF']:>12,.0f}"
    )
print("-" * 120)

# =============================================================================
# SECTION 7: TERMINAL VALUE
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 7: TERMINAL VALUE CALCULATION")
print("=" * 80)

# Terminal year values (Year 10)
terminal_nopat = projections[-1]["NOPAT"]
terminal_fcff = projections[-1]["FCFF"]

# Terminal FCFF (Year 11) with terminal growth
# Per Damodaran: In terminal, reinvestment rate = g / ROIC = g / WACC
terminal_reinvest_rate = terminal_growth / terminal_roic
terminal_year_nopat = terminal_nopat * (1 + terminal_growth)
terminal_year_reinvestment = terminal_year_nopat * terminal_reinvest_rate
terminal_year_fcff = terminal_year_nopat - terminal_year_reinvestment

# Terminal Value using perpetuity growth model
terminal_value = terminal_year_fcff / (wacc - terminal_growth)

print(f"""
Terminal Value Calculation (Damodaran's Constraints Applied):
─────────────────────────────────────────────────────────────

Constraints Verified:
  Terminal Growth ({terminal_growth:.2%}) <= Risk-Free Rate ({risk_free_rate:.2%}): {"YES" if terminal_growth <= risk_free_rate else "NO"}
  Terminal ROIC ({terminal_roic:.2%}) = WACC ({wacc:.2%}): {"YES (approx)" if abs(terminal_roic - wacc) < 0.005 else "NO"}

Terminal Year (Year 11) Calculations:
  Year 10 NOPAT:                ${terminal_nopat:,.0f}M
  Terminal Growth:              {terminal_growth:.2%}
  Year 11 NOPAT:                ${terminal_year_nopat:,.0f}M
  
  Terminal ROIC:                {terminal_roic:.2%}
  Terminal Reinvest Rate:       {terminal_reinvest_rate:.1%} (= {terminal_growth:.2%} / {terminal_roic:.2%})
  Terminal Reinvestment:        ${terminal_year_reinvestment:,.0f}M
  Terminal FCFF (Year 11):      ${terminal_year_fcff:,.0f}M

Terminal Value (Perpetuity):
  TV = FCFF(11) / (WACC - g)
  TV = ${terminal_year_fcff:,.0f}M / ({wacc:.2%} - {terminal_growth:.2%})
  
  ══════════════════════════════════════════════════
  Terminal Value:               ${terminal_value:,.0f}M
  ══════════════════════════════════════════════════
""")

# =============================================================================
# SECTION 8: DCF VALUATION - ENTERPRISE VALUE
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 8: DCF VALUATION - ENTERPRISE VALUE")
print("=" * 80)

# Discount FCFF and Terminal Value
discount_factors = [(1 + wacc) ** -i for i in range(1, 11)]
pv_fcff = sum(fcff * df for fcff, df in zip(fcff_projection, discount_factors))

# PV of Terminal Value
pv_terminal_value = terminal_value * (1 + wacc) ** -10

# Enterprise Value
enterprise_value = pv_fcff + pv_terminal_value

print(f"""
Present Value of Projected FCFF:
─────────────────────────────────────────────────────────────
Year    FCFF          Discount Factor    PV of FCFF
─────────────────────────────────────────────────────────────""")
pv_details = []
for i, (fcff, df) in enumerate(zip(fcff_projection, discount_factors), 1):
    pv = fcff * df
    pv_details.append({"Year": i, "FCFF": fcff, "DF": df, "PV": pv})
    print(f"{i:4d}    ${fcff:>12,.0f}    {df:>14.4f}    ${pv:>12,.0f}")
print("-" * 60)
print(f"{'Sum':>4}    {'':>12}    {'':>14}    ${pv_fcff:>12,.0f}")

print(f"""

Present Value of Terminal Value:
  Terminal Value:               ${terminal_value:,.0f}M
  Discount Factor (Year 10):    {(1 + wacc) ** -10:.4f}
  PV of Terminal Value:         ${pv_terminal_value:,.0f}M

Enterprise Value Composition:
─────────────────────────────────────────────────────────────
  PV of FCFF (Years 1-10):      ${pv_fcff:>15,.0f}M ({pv_fcff / enterprise_value:.1%})
  PV of Terminal Value:         ${pv_terminal_value:>15,.0f}M ({pv_terminal_value / enterprise_value:.1%})
  ───────────────────────────────────────────────────────────
  ENTERPRISE VALUE:             ${enterprise_value:>15,.0f}M
═════════════════════════════════════════════════════════════
""")

# =============================================================================
# SECTION 9: EQUITY VALUE & PRICE PER SHARE
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 9: BRIDGE TO EQUITY VALUE PER SHARE")
print("=" * 80)

# Per Damodaran, treat employee equity claims explicitly:
# - Employee options: value as options and subtract from equity value
# - Restricted stock / RSUs: treat as common shares (add to share count)
#
# Amazon's employee equity is primarily RSUs (effective exercise price = $0), so we add
# RSUs to the share count.

minority_interest = 0  # Amazon has minimal minority interest

value_of_equity = (
    enterprise_value
    + total_cash
    - total_debt
    - operating_lease_liability
    - minority_interest
)

share_count = shares_outstanding + rsu_outstanding

# If employee stock options exist (not RSUs), compute option_value and subtract here:
# value_of_equity -= option_value

equity_value_per_share = value_of_equity / share_count

print(f"""
Equity Value Bridge (Damodaran Method):
═══════════════════════════════════════════════════════════════

  Enterprise Value:             ${enterprise_value:>15,.0f}M
  + Cash & Marketable Sec:      ${total_cash:>15,.0f}M
  - Total Debt:                 ${total_debt:>15,.0f}M
  - Operating Lease Liability:  ${operating_lease_liability:>15,.0f}M
  - Minority Interest:          ${minority_interest:>15,.0f}M
  ───────────────────────────────────────────────────────────────
  VALUE OF EQUITY:              ${value_of_equity:>15,.0f}M
═══════════════════════════════════════════════════════════════

Shares (Primary):               {shares_outstanding:,.0f}M
RSUs (treated as shares):       {rsu_outstanding:,.1f}M
Total Shares:                   {share_count:,.1f}M

═══════════════════════════════════════════════════════════════
  EQUITY VALUE PER SHARE:       ${equity_value_per_share:>15,.2f}
═══════════════════════════════════════════════════════════════

Current Market Price:           ${stock_price:>15,.2f}
Implied Upside/(Downside):      {(equity_value_per_share / stock_price - 1):>15.1%}
""")

# =============================================================================
# SECTION 10: SENSITIVITY ANALYSIS & SANITY CHECKS
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 10: SENSITIVITY ANALYSIS & SANITY CHECKS")
print("=" * 80)

# Sensitivity table: WACC vs Terminal Growth
print("\nSensitivity Analysis: Equity Value per Share")
print("Terminal Growth Rate vs WACC")
print("-" * 70)

wacc_range = [0.075, 0.085, wacc, 0.095, 0.105]
growth_range = [0.02, 0.03, terminal_growth, 0.04]

# Header
header = "WACC \\ g  |"
for g in growth_range:
    header += f"  {g:>6.2%}  |"
print(header)
print("-" * 70)

for w in wacc_range:
    row = f"  {w:.2%}   |"
    for g in growth_range:
        if w > g:  # Valid only if WACC > g
            # Recalculate terminal value and equity value
            tv_sens = terminal_year_fcff / (w - g)
            pv_tv_sens = tv_sens * (1 + w) ** -10
            # Recalculate PV of FCFF with new WACC
            df_sens = [(1 + w) ** -i for i in range(1, 11)]
            pv_fcff_sens = sum(fcff * df for fcff, df in zip(fcff_projection, df_sens))
            ev_sens = pv_fcff_sens + pv_tv_sens
            eq_sens = (
                ev_sens
                + total_cash
                - total_debt
                - operating_lease_liability
                - minority_interest
            )
            price_sens = eq_sens / share_count
            row += f"  ${price_sens:>6.0f}  |"
        else:
            row += f"    N/A   |"
    print(row)

print("-" * 70)

# Implied Multiples
print(f"""

Sanity Check - Implied Multiples:
─────────────────────────────────────────────────────────────
  Implied P/E (NTM):            {value_of_equity / (projections[0]["NOPAT"] / (1 - tax_rates[0])):.1f}x
  Implied EV/Revenue (TTM):     {enterprise_value / revenue:.2f}x
  Implied EV/EBIT (TTM):        {enterprise_value / adjusted_ebit:.1f}x
  
Terminal Value as % of EV:      {pv_terminal_value / enterprise_value:.1%}

Key Assumptions Recap:
  WACC:                         {wacc:.2%}
  Terminal Growth:              {terminal_growth:.2%} (capped at Rf)
  Terminal ROIC:                {terminal_roic:.2%} (= WACC)
  
Commentary:
  - Terminal value is {pv_terminal_value / enterprise_value:.0%} of total value (typical for growth company)
  - Implied multiples appear {"reasonable" if 25 < enterprise_value / adjusted_ebit < 40 else "elevated"} for a tech/cloud hybrid
  - ROIC converges to WACC in terminal year (competitive advantages erode)
""")

# =============================================================================
# FINAL SUMMARY
# =============================================================================
print("\n" + "=" * 80)
print("FINAL SUMMARY: AMAZON DCF VALUATION (DAMODARAN METHODOLOGY)")
print("=" * 80)

print(f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AMAZON (AMZN) DCF VALUATION                          │
│                       Damodaran Methodology Applied                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  KEY INPUTS:                                                                │
│    Risk-Free Rate:          {risk_free_rate:>6.2%}    (10-yr Treasury, Nov 2025)       │
│    Equity Risk Premium:     {equity_risk_premium:>6.2%}    (Damodaran Implied ERP)          │
│    Levered Beta:            {levered_beta:>6.3f}    (Bottom-up, Op Income weighted)    │
│    Cost of Equity:          {cost_of_equity:>6.2%}                                       │
│    After-tax Cost of Debt:  {after_tax_cost_of_debt:>6.2%}    (AA rating)                         │
│    WACC:                    {wacc:>6.2%}                                       │
│    Terminal Growth:         {terminal_growth:>6.2%}    (capped at Rf)                    │
│                                                                             │
│  ADJUSTMENTS APPLIED:                                                       │
│    R&D Capitalized:         ${research_asset:>10,.0f}M (3-yr amortization)             │
│    Operating Leases:        ${operating_lease_liability:>10,.0f}M (treated as debt)               │
│    SBC:                     NOT added back (Damodaran treatment)            │
│    Tax Rate:                Effective -> Marginal transition                │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  VALUATION RESULTS:                                                         │
│    Enterprise Value:        ${enterprise_value:>14,.0f}M                               │
│    Value of Equity:         ${value_of_equity:>14,.0f}M                               │
│    Share Count (incl RSUs): {share_count:>14,.0f}M                               │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════   │
│    DCF VALUE PER SHARE:     ${equity_value_per_share:>14,.2f}                               │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                             │
│    Current Market Price:    ${stock_price:>14,.2f}                               │
│    Implied Upside:          {(equity_value_per_share / stock_price - 1):>14.1%}                               │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Data Sources:                                                              │
│    - Amazon 10-K FY2024 (Filed Feb 7, 2025)                                 │
│    - Amazon 10-Q Q3 2025 (Filed Oct 2025)                                   │
│    - US Treasury (10-yr yield, Nov 26, 2025)                                │
│    - Damodaran NYU datasets (Betas, ERP, Spreads - Jan/Nov 2025)            │
└─────────────────────────────────────────────────────────────────────────────┘
""")

# =============================================================================
# SECTION 11: ANALYSIS OF VALUATION GAP
# =============================================================================
print("\n" + "=" * 80)
print("SECTION 11: UNDERSTANDING THE VALUATION GAP")
print("=" * 80)

# Market implied assumptions
market_ev = market_cap + total_debt_with_leases - total_cash
market_ev_ebit = market_ev / adjusted_ebit


# What WACC would justify current price?
# Working backwards: What discount rate makes DCF = market price?
def calc_ev_for_wacc(w, g_term=terminal_growth):
    """Calculate EV for a given WACC"""
    if w <= g_term:
        return float("inf")
    # Recalc terminal value
    term_reinv = g_term / w  # ROIC = WACC in terminal
    term_fcff = terminal_nopat * (1 + g_term) * (1 - term_reinv)
    tv = term_fcff / (w - g_term)
    pv_tv = tv * (1 + w) ** -10
    # PV of FCFF
    dfs = [(1 + w) ** -i for i in range(1, 11)]
    pv_f = sum(f * d for f, d in zip(fcff_projection, dfs))
    return pv_f + pv_tv


# Binary search for implied WACC
low_w, high_w = 0.04, 0.15
target_ev = market_ev
while high_w - low_w > 0.0001:
    mid_w = (low_w + high_w) / 2
    calc_ev = calc_ev_for_wacc(mid_w)
    if calc_ev > target_ev:
        low_w = mid_w
    else:
        high_w = mid_w
implied_wacc = (low_w + high_w) / 2


# What if we allow higher terminal ROIC (moat premium)?
def calc_ev_with_moat(roic_premium=0.02):
    """Allow terminal ROIC > WACC"""
    term_roic = wacc + roic_premium
    term_reinv = terminal_growth / term_roic
    term_fcff = terminal_nopat * (1 + terminal_growth) * (1 - term_reinv)
    tv = term_fcff / (wacc - terminal_growth)
    pv_tv = tv * (1 + wacc) ** -10
    return pv_fcff + pv_tv


ev_2pct_moat = calc_ev_with_moat(0.02)
ev_5pct_moat = calc_ev_with_moat(0.05)
ev_10pct_moat = calc_ev_with_moat(0.10)

# What if we add back SBC (like most Wall Street analysts)?
fcff_with_sbc_addback = []
for row in projections:
    # Assume SBC grows at same rate as NOPAT
    year_num = int(row["Year"])
    sbc_proj = sbc_expense * ((1 + 0.08) ** year_num)  # ~8% CAGR
    fcff_with_sbc_addback.append(row["FCFF"] + sbc_proj * (1 - tax_rates[year_num - 1]))

pv_fcff_sbc = sum(f * d for f, d in zip(fcff_with_sbc_addback, discount_factors))
# Terminal with SBC
sbc_terminal = sbc_expense * (1.08**10) * (1 + terminal_growth)
term_fcff_sbc = terminal_year_fcff + sbc_terminal * (1 - marginal_tax_rate)
tv_sbc = term_fcff_sbc / (wacc - terminal_growth)
pv_tv_sbc = tv_sbc * (1 + wacc) ** -10
ev_with_sbc = pv_fcff_sbc + pv_tv_sbc
eq_with_sbc = (
    ev_with_sbc
    + total_cash
    - total_debt
    - operating_lease_liability
    - minority_interest
)
price_with_sbc = eq_with_sbc / share_count

print(f"""
The strict Damodaran DCF yields ${equity_value_per_share:.0f}/share vs market price ${stock_price:.0f}.
This gap reflects several conservative assumptions in the methodology:

MARKET IMPLIED METRICS:
  Market Enterprise Value:      ${market_ev:,.0f}M
  Market EV/Adjusted EBIT:      {market_ev_ebit:.1f}x (vs DCF implied {enterprise_value / adjusted_ebit:.1f}x)
  Implied WACC to justify:      {implied_wacc:.2%} (vs calculated {wacc:.2%})

WHAT THE MARKET MAY BE PRICING IN:

1. LOWER DISCOUNT RATE (implied WACC ~{implied_wacc:.1%} vs {wacc:.1%}):
   - Lower beta assumption (pure retail beta ~1.1 vs our 1.5)
   - Lower ERP expectation
   - More optimistic view on AWS dominance reducing risk

2. HIGHER TERMINAL ROIC (moat premium):
   If we allow excess returns in perpetuity:
   - Terminal ROIC = WACC + 2%:  EV = ${ev_2pct_moat:,.0f}M  → ${(ev_2pct_moat + total_cash - total_debt - operating_lease_liability - minority_interest) / share_count:.0f}/share
   - Terminal ROIC = WACC + 5%:  EV = ${ev_5pct_moat:,.0f}M  → ${(ev_5pct_moat + total_cash - total_debt - operating_lease_liability - minority_interest) / share_count:.0f}/share
   - Terminal ROIC = WACC + 10%: EV = ${ev_10pct_moat:,.0f}M → ${(ev_10pct_moat + total_cash - total_debt - operating_lease_liability - minority_interest) / share_count:.0f}/share

3. SBC TREATMENT (Wall Street style - add it back):
   If we add back SBC as "non-cash":
   - Equity Value with SBC:     ${eq_with_sbc:,.0f}M
   - Price per Share:           ${price_with_sbc:.0f}/share
   (Damodaran explicitly argues AGAINST this treatment)

4. HIGHER GROWTH / LONGER HIGH-GROWTH PERIOD:
   The market may be pricing in:
   - AWS AI/ML growth acceleration (GenAI boom)
   - Advertising business scaling to $100B+
   - International profitability inflection
   - Healthcare, logistics, and other new ventures

DAMODARAN'S LIKELY RESPONSE:
─────────────────────────────────────────────────────────────────────────────
"The market price reflects narrative, not just numbers. My DCF represents
what Amazon is worth IF it achieves reasonable growth AND those advantages
erode over time (as they do for most companies). The market is pricing in
either perpetual dominance (ROIC > WACC forever) or much higher growth.

Both could be right - but one of us will be wrong. The value of a rigorous
DCF is not to predict the price, but to understand what the price implies."
─────────────────────────────────────────────────────────────────────────────

RECOMMENDATION:
  The Damodaran DCF value of ${equity_value_per_share:.0f} represents a CONSERVATIVE 
  intrinsic value. At ${stock_price:.0f}, the market is pricing in significant optionality
  on AWS/AI growth and a durable competitive moat. 
  
  Investors should decide: Do you believe Amazon's ROIC will remain above its
  cost of capital for decades? If yes, the market price may be justified.
  If no, the stock appears overvalued by Damodaran's framework.
""")
