{{ config(materialized='table') }}

with ratios as (
    select
        f.symbol,
        f.period_end_date,
        f.com_class,
        d.icb_code_lv2,
        d.industry_lv2,
        case when f.pe_meaningful then f.pe end as pe,
        case when f.pb_meaningful then f.pb end as pb,
        f.roe
    from {{ ref('stg_financial_ratio') }} f
    join {{ ref('dim_stock') }} d using (symbol)
    where f.quarter between 1 and 4
      -- Mã chưa có hồ sơ DN (thường là mã mới niêm yết, hồ sơ chỉ nạp ở job
      -- monthly) không có ngành → không thuộc nhóm ngành nào để so. Giữ lại thì
      -- sinh một "ngành" NULL gộp mã lạ với nhau: DTR/KAI/GTX (lên sàn 09/2026)
      -- làm test not_null fail ở run weekly 17/10/2026. Cùng quy tắc
      -- int_metric_percentile loại com_class 'UNKNOWN'.
      and d.icb_code_lv2 is not null
),

lp as (select max(period_end_date) as max_period from ratios),

sector_return as (
    -- Chỉ lấy mã CÒN giao dịch. Một mã bị đình chỉ sẽ đóng băng phiên cuối
    -- của nó, và `return_3m` cũ hàng tháng vẫn được tính vào suất sinh lời
    -- ngành hôm nay như thể còn hiệu lực. Ngưỡng 15 ngày thống nhất với quy
    -- tắc đứt gãy giao dịch đã chốt ở Task 3.
    select d.icb_code_lv2, d.com_class,
           sum(p.return_3m * d.market_cap) / nullif(sum(d.market_cap), 0) as sector_return_3m
    from {{ ref('dim_stock') }} d
    join (select symbol, max(trade_date) as last_session
          from {{ ref('fct_price_daily') }} group by 1) m
      on m.symbol = d.symbol
    join {{ ref('fct_price_daily') }} p
      on p.symbol = d.symbol and p.trade_date = m.last_session
    cross join (select max(trade_date) as market_date
                from {{ ref('fct_price_daily') }}) mk
    where d.market_cap is not null
      and p.return_3m is not null
      and datediff('day', m.last_session, mk.market_date) <= 15
    group by 1, 2
)

select
    r.icb_code_lv2,
    r.industry_lv2,
    r.com_class,
    r.period_end_date,
    count(distinct r.symbol) as n_symbols,
    -- `n_symbols` đếm mọi mã trong nhóm, nhưng median chỉ tính trên mã có số
    -- liệu dùng được. Không phơi ba cột dưới thì `median_pe` của một nhóm 238
    -- mã trông như dựa trên 238 mã, trong khi thực tế chỉ 182 mã có P/E hợp
    -- lệ (đã đo trên production: 17/21 nhóm lệch).
    count(r.pe)              as n_pe,
    count(r.pb)              as n_pb,
    count(r.roe)             as n_roe,
    median(r.pe)             as median_pe,
    median(r.pb)             as median_pb,
    median(r.roe)            as median_roe,
    -- `sector_return_3m` tính từ phiên giao dịch GẦN NHẤT và lấy trọng số là
    -- `market_cap` HIỆN TẠI, nên nó chỉ đúng cho kỳ mới nhất. Gắn nó vào một
    -- kỳ quá khứ là trộn hai mốc thời gian — dòng 2018Q1 sẽ mang suất sinh
    -- lời của 2026. Ta không có vốn hoá lịch sử nên không tính ngược được;
    -- để NULL là trung thực, đừng bịa.
    max(case when r.period_end_date = lp.max_period
             then s.sector_return_3m end) as sector_return_3m
from ratios r
cross join lp
left join sector_return s
       on s.icb_code_lv2 = r.icb_code_lv2 and s.com_class = r.com_class
group by 1, 2, 3, 4
