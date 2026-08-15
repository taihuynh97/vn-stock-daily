{{ config(materialized='table', tags=['daily']) }}

select
    p.symbol,
    p.trade_date,
    s.open, s.high, s.low, p.close, p.volume,
    s.value_vnd, s.turnover_vnd,
    p.ma20, p.ma50, p.ma200,
    p.return_1m, p.return_3m, p.return_6m, p.return_12m, p.return_ytd,
    p.avg_turnover_20d, p.avg_turnover_60d,
    p.volatility_60d, p.high_52w, p.low_52w, p.pct_from_high_52w
from {{ ref('int_price_features') }} p
join {{ ref('stg_price_daily') }} s using (symbol, trade_date)
