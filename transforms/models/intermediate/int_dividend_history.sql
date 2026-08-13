{{ config(materialized='table') }}

-- Đếm trên các dòng NĂM (quarter = 5), không phải dòng TTM.
with yearly as (
    select symbol, year, dividend_yield
    from {{ ref('stg_financial_ratio') }}
    where quarter = 5 and dividend_yield is not null
),

latest_year as (
    select symbol, max(year) as max_year from yearly group by 1
),

-- Đánh dấu năm KHÔNG trả cổ tức để cắt chuỗi liên tiếp.
gapped as (
    select
        y.symbol,
        y.year,
        y.dividend_yield,
        l.max_year,
        max(case when y.dividend_yield <= 0 then y.year end)
            over (partition by y.symbol) as last_zero_year
    from yearly y
    join latest_year l using (symbol)
)

select
    symbol,
    avg(case when year >= max_year - 4 then dividend_yield end) as dividend_yield_avg_5y,
    -- Số năm liên tiếp có cổ tức, tính lùi từ năm gần nhất.
    count(*) filter (
        where dividend_yield > 0
          and (last_zero_year is null or year > last_zero_year)
    ) as dividend_years_consecutive,
    case
        when avg(dividend_yield) is null or avg(dividend_yield) <= 0 then 0.0
        else greatest(0.0, least(1.0,
             1 - stddev_samp(dividend_yield) / nullif(avg(dividend_yield), 0)))
    end as dividend_stability
from gapped
group by symbol
