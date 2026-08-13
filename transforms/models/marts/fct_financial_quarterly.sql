{{ config(materialized='table') }}

select
    f.symbol,
    f.year,
    f.quarter,
    f.period_end_date,
    f.period_type,
    f.com_class,
    f.* exclude (symbol, year, quarter, period_end_date, period_type,
                 com_class, ratio_type, icb_code_lv2, icb_code_lv4),
    t.revenue_ttm,
    t.earnings_ttm,
    t.book_value,
    t.eps,
    t.bvps,
    t.revenue_yoy,
    t.earnings_yoy,
    t.revenue_cagr_3y,
    t.earnings_cagr_3y,
    t.growth_consistency,
    t.loss_quarters_12q,
    q.roe_avg_8q,
    q.roe_stability,
    q.gross_margin_slope_8q
from {{ ref('stg_financial_ratio') }} f
left join {{ ref('int_fundamentals_ttm') }} t using (symbol, period_end_date)
left join {{ ref('int_quality_metrics') }}  q using (symbol, period_end_date)
