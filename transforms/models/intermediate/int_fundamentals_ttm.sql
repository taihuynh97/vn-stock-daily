{{ config(materialized='table') }}

-- Vì pe, ps, pb và market_cap cùng thuộc một dòng (cùng thời điểm giá),
-- phép chia triệt tiêu giá và cho ra chỉ tiêu tuyệt đối.
-- Đối chiếu HPG 2024Q4: 138.855 tỷ doanh thu / 12.021 tỷ LNST — khớp BCTC.
-- Chỉ dùng dòng TTM (quarter 1-4); dòng cả năm (quarter=5) bị loại để chuỗi
-- thời gian không lẫn hai loại kỳ.
with ttm as (
    select
        symbol,
        year,
        quarter,
        period_end_date,
        com_class,
        market_cap,
        number_of_shares_mkt_cap                as shares,
        -- Fix round 1 (coordinator review): ps <= 0 bị NULL hoá TRƯỚC khi
        -- chia — doanh thu ÂM vô nghĩa kinh tế/vô dụng cho định giá (đo
        -- production: 43 dòng ps<0 + 486 dòng ps=0). Ví dụ PTC 2020Q4
        -- ps=-1277: bất động sản hoàn nhập doanh thu do huỷ hợp đồng — có
        -- thật về kế toán nhưng không dùng được ở tầng chấm điểm/định giá.
        -- KHÁC với pe bên dưới: pe âm là HỢP LỆ và PHẢI giữ (doanh nghiệp
        -- lỗ → earnings_ttm âm là kết quả ĐÚNG, đã đối chiếu HPG 2023Q2 =
        -- -1.908 tỷ khớp tuyệt đối). ĐỪNG áp cùng logic `case when > 0` cho
        -- pe để "nhất quán" — điều đó sẽ xoá mất tín hiệu lỗ thật.
        market_cap / nullif(case when ps > 0 then ps end, 0)  as revenue_ttm,
        market_cap / nullif(pe, 0)                            as earnings_ttm,
        -- pb <= 0: vốn chủ sở hữu suy ra ÂM hoặc bằng 0 (mất vốn/sentinel)
        -- — P/B không có nghĩa trong trường hợp này, NULL hoá trước khi
        -- chia, cùng lý do với ps ở trên (khác pe: không có khái niệm "lỗ
        -- vốn chủ" hợp lệ tương tự "lỗ lợi nhuận").
        market_cap / nullif(case when pb > 0 then pb end, 0)  as book_value,
        is_loss_making
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

with_lags as (
    select
        *,
        lag(revenue_ttm,   4) over (partition by symbol order by period_end_date) as revenue_4q_ago,
        lag(earnings_ttm,  4) over (partition by symbol order by period_end_date) as earnings_4q_ago,
        lag(revenue_ttm,  12) over (partition by symbol order by period_end_date) as revenue_12q_ago,
        lag(earnings_ttm, 12) over (partition by symbol order by period_end_date) as earnings_12q_ago,
        sum(case when is_loss_making then 1 else 0 end) over (
            partition by symbol order by period_end_date
            rows between 11 preceding and current row
        ) as loss_quarters_12q
    from ttm
),

with_growth as (
    select
        *,
        revenue_ttm  / nullif(revenue_4q_ago, 0)  - 1 as revenue_yoy,
        earnings_ttm / nullif(earnings_4q_ago, 0) - 1 as earnings_yoy,
        -- CAGR 3 năm chỉ có nghĩa khi mốc gốc dương.
        case when revenue_12q_ago > 0 and revenue_ttm > 0
             then power(revenue_ttm / revenue_12q_ago, 1.0 / 3) - 1 end as revenue_cagr_3y,
        case when earnings_12q_ago > 0 and earnings_ttm > 0
             then power(earnings_ttm / earnings_12q_ago, 1.0 / 3) - 1 end as earnings_cagr_3y
    from with_lags
)

select
    symbol,
    year,
    quarter,
    period_end_date,
    com_class,
    market_cap,
    shares,
    revenue_ttm,
    earnings_ttm,
    book_value,
    earnings_ttm / nullif(shares, 0) as eps,
    book_value   / nullif(shares, 0) as bvps,
    revenue_yoy,
    earnings_yoy,
    revenue_cagr_3y,
    earnings_cagr_3y,
    loss_quarters_12q,
    -- Tính nhất quán tăng trưởng: tỉ lệ quý có YoY doanh thu dương trong 12 quý.
    avg(case when revenue_yoy > 0 then 1.0
             when revenue_yoy is null then null
             else 0.0 end) over (
        partition by symbol order by period_end_date
        rows between 11 preceding and current row
    ) as growth_consistency
from with_growth
