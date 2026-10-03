{{ config(materialized='table') }}

-- Định giá theo GIÁ HIỆN TẠI (mảng Q).
--
-- Trước mảng Q, pe/pb/valuation_band/value_score trong scorecard là số của
-- NGÀY CHỐT QUÝ (giá ngày 30/06 chia LNST 4 quý đến 30/06) và đứng yên tới khi
-- nguồn có quý mới — trễ tới ~4,5 tháng. Một mã giảm 40% sau ngày chốt vẫn
-- hiện P/E cũ. Tệ hơn, chia `last_close` (sau thưởng cổ phiếu) cho EPS quý cũ
-- (trước thưởng) làm mã trông rẻ giả — PHR ngày 12/09/2026.
--
-- Cách tính không cần số cổ phiếu hiện tại:
--   price_ratio = adj_close(phiên mới nhất) / adj_close(phiên cuối ≤ ngày chốt)
--   pe_current  = pe_ngày_chốt × price_ratio   (tương tự pb, market_cap)
-- adj_close của hai mốc cùng một hệ điều chỉnh nên thưởng/chia cổ phiếu sau
-- ngày chốt tự triệt tiêu. Quy ước: cổ tức tiền sau ngày chốt cũng nằm trong
-- hệ số → P/E hiện tại hơi CAO hơn (thận trọng), lệch cỡ tỷ suất cổ tức.
--
-- GROUP BY + arg_max thay vì row_number()/QUALIFY: tránh lỗi ánh xạ cột của
-- DuckDB 1.5.3 (xem int_quarterly_profit).
with latest_px as (
    select symbol,
           max(trade_date)                 as price_date,
           arg_max(adj_close, trade_date)  as adj_close_now
    from {{ ref('int_price_features') }}
    group by 1
),

latest_period as (
    select symbol, max(period_end_date) as period_end_date
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
    group by 1
),

ratio_latest as (
    select f.symbol, f.period_end_date, f.year, f.quarter,
           f.pe, f.pb, f.market_cap, f.pe_meaningful, f.pb_meaningful
    from {{ ref('stg_financial_ratio') }} f
    join latest_period l using (symbol, period_end_date)
    where f.quarter between 1 and 4
),

-- Phiên cuối cùng ≤ ngày chốt, trong vòng 15 ngày (cùng ngưỡng tạm ngừng giao
-- dịch của int_price_features). Không có phiên nào → không quy đổi được → NULL.
px_at_period as (
    select r.symbol,
           max(p.trade_date)                as period_price_date,
           arg_max(p.adj_close, p.trade_date) as adj_close_at_period
    from ratio_latest r
    join {{ ref('int_price_features') }} p
      on p.symbol = r.symbol
     and p.trade_date <= r.period_end_date
     and p.trade_date >  r.period_end_date - interval 15 day
    group by 1
),

cur as (
    select
        r.symbol,
        r.period_end_date                                   as ratio_period_end,
        r.year * 4 + r.quarter                              as abs_quarter,
        lp.price_date,
        pp.period_price_date,
        lp.adj_close_now / nullif(pp.adj_close_at_period, 0) as price_ratio,
        r.pe, r.pb, r.market_cap,
        case when r.pe_meaningful then r.pe end             as pe_valid,
        case when r.pb_meaningful then r.pb end             as pb_valid
    from ratio_latest r
    left join latest_px lp using (symbol)
    left join px_at_period pp using (symbol)
),

valued as (
    select
        *,
        pe_valid   * price_ratio as pe_current,
        pb_valid   * price_ratio as pb_current,
        market_cap * price_ratio as market_cap_current
    from cur
),

-- Phân vị của P/E HIỆN TẠI trong 20 quý lịch sử của chính mã (gồm quý mới nhất
-- ở giá ngày chốt). Mẫu số = số quý hợp lệ (P/E hiện tại không nằm trong tập).
hist as (
    select symbol, year * 4 + quarter as abs_quarter,
           case when pe_meaningful then pe end as pe_valid,
           case when pb_meaningful then pb end as pb_valid
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

pct as (
    select
        v.symbol,
        count(h.pe_valid) as pe_quarters_used,
        count(h.pb_valid) as pb_quarters_used,
        count(*) filter (where h.pe_valid < v.pe_current)::double
            / nullif(count(h.pe_valid), 0) as pe_pct_raw,
        count(*) filter (where h.pb_valid < v.pb_current)::double
            / nullif(count(h.pb_valid), 0) as pb_pct_raw
    from valued v
    join hist h
      on h.symbol = v.symbol
     and h.abs_quarter between v.abs_quarter - 19 and v.abs_quarter
    group by 1
)

select
    v.symbol,
    v.ratio_period_end,
    v.price_date,
    v.period_price_date,
    v.price_ratio,
    v.pe_current,
    v.pb_current,
    v.market_cap_current,
    case when v.pe_current is not null
              and p.pe_quarters_used >= {{ var('own_history_min_quarters') }}
         then p.pe_pct_raw end as pe_pct_own_5y_current,
    case when v.pb_current is not null
              and p.pb_quarters_used >= {{ var('own_history_min_quarters') }}
         then p.pb_pct_raw end as pb_pct_own_5y_current,
    p.pe_quarters_used,
    p.pb_quarters_used
from valued v
left join pct p using (symbol)
