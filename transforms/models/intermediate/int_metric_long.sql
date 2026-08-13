{{ config(materialized='table') }}

{% set metric_list = all_metrics() %}

-- Kỳ tỷ số mới nhất của mỗi mã (chỉ dòng TTM).
with latest_period as (
    select symbol, max(period_end_date) as period_end_date
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
    group by 1
),

ratio_latest as (
    select f.*
    from {{ ref('stg_financial_ratio') }} f
    join latest_period p using (symbol, period_end_date)
    where f.quarter between 1 and 4
),

-- (1) 44 chỉ tiêu gốc → dạng long. UNPIVOT của DuckDB tự bỏ giá trị NULL.
-- Dùng cú pháp UNPIVOT chuẩn SQL (đặt sau FROM) vì nó lồng được trong CTE.
ratio_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from (
        select symbol, com_class, icb_code_lv2,
               {{ metric_list | join(', ') }}
        from ratio_latest
    )
    unpivot (value for metric in ({{ metric_list | join(', ') }}))
),

-- (2) Chỉ tiêu suy ra ở kỳ mới nhất.
fund_latest as (
    select f.symbol, f.com_class, c.icb_code_lv2,
           f.revenue_yoy, f.earnings_yoy, f.revenue_cagr_3y,
           f.earnings_cagr_3y, f.growth_consistency,
           cast(f.loss_quarters_12q as double) as loss_quarters_12q
    from {{ ref('int_fundamentals_ttm') }} f
    join latest_period p using (symbol, period_end_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

fund_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from fund_latest
    unpivot (value for metric in (
        revenue_yoy, earnings_yoy, revenue_cagr_3y, earnings_cagr_3y,
        growth_consistency, loss_quarters_12q))
),

qual_latest as (
    select q.symbol, q.com_class, c.icb_code_lv2,
           q.roe_avg_8q, q.roe_stability, q.gross_margin_slope_8q
    from {{ ref('int_quality_metrics') }} q
    join latest_period p using (symbol, period_end_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

qual_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from qual_latest
    unpivot (value for metric in (
        roe_avg_8q, roe_stability, gross_margin_slope_8q))
),

div_latest as (
    select d.symbol, c.com_class, c.icb_code_lv2,
           d.dividend_yield_avg_5y,
           cast(d.dividend_years_consecutive as double) as dividend_years_consecutive,
           d.dividend_stability
    from {{ ref('int_dividend_history') }} d
    left join {{ ref('stg_company_info') }} c using (symbol)
),

div_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from div_latest
    unpivot (value for metric in (
        dividend_yield_avg_5y, dividend_years_consecutive, dividend_stability))
),

-- (3) Chỉ tiêu giá ở phiên mới nhất.
price_latest as (
    select p.symbol, c.com_class, c.icb_code_lv2,
           p.avg_turnover_20d, p.volatility_60d,
           cast(c.listing_age_years as double) as listing_age_years,
           c.free_float_percentage
    from {{ ref('int_price_features') }} p
    join (
        select symbol, max(trade_date) as trade_date
        from {{ ref('int_price_features') }} group by 1
    ) m using (symbol, trade_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

price_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from price_latest
    unpivot (value for metric in (
        avg_turnover_20d, volatility_60d, listing_age_years,
        free_float_percentage))
)

select symbol, com_class, icb_code_lv2, lower(metric) as metric, value
from (
    select * from ratio_long
    union all select * from fund_long
    union all select * from qual_long
    union all select * from div_long
    union all select * from price_long
)
where value is not null
  and isfinite(value)
