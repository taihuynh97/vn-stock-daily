{{ config(materialized='table', tags=['daily']) }}

-- `close` = giá khớp thật của phiên (hiển thị). `adj_close` = giá đã điều chỉnh
-- chia/thưởng/cổ tức (mảng Q) — mọi return_*, ma*, high/low_52w tính trên nó.
-- Đừng chia return tự tính từ `close` qua nhiều phiên: sẽ dính bước nhảy giả
-- ở ngày GDKHQ.
select
    p.symbol,
    p.trade_date,
    s.open, s.high, s.low, p.close, p.adj_close, p.adj_factor, p.volume,
    s.value_vnd, s.turnover_vnd,
    s.ref_price,
    s.foreign_buy_volume, s.foreign_sell_volume,
    s.foreign_buy_value, s.foreign_sell_value,
    p.ma20, p.ma50, p.ma200,
    p.return_1m, p.return_3m, p.return_6m, p.return_12m, p.return_ytd,
    p.avg_turnover_20d, p.avg_turnover_60d,
    p.volatility_60d, p.high_52w, p.low_52w, p.pct_from_high_52w
from {{ ref('int_price_features') }} p
join {{ ref('stg_price_daily') }} s using (symbol, trade_date)
