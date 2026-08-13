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

-- Fix round 2 (coordinator review, C1): GHÉP THEO LỊCH, KHÔNG DÙNG lag()
-- THEO DÒNG.
--
-- lag(x, 4) lấy dòng cách 4 VỊ TRÍ, chỉ đúng nếu chuỗi quý liền mạch. Thực
-- tế 1.378/1.585 mã (87%) có khoảng trống — riêng 2021 Q2 chỉ 177/1.585 mã
-- báo cáo (kể cả HPG: dòng 2021Q2 vắng mặt trong chính chuỗi TTM của nó).
-- Đo trên production với bản dùng lag(): 53% dòng revenue_yoy LẬT DẤU tăng
-- trưởng, và 62,7% giá trị revenue_cagr_3y lẽ ra phải NULL. Chính HPG cũng
-- sai: 2022Q4 đúng là +18,88% nhưng lag() cho ra -5,53%.
--
-- Không tồn tại kỳ đối chiếu thì kết quả là NULL — đó là câu trả lời ĐÚNG.
-- Task 10 chuẩn hoá lại trọng số khi gặp NULL nên không gây hại.
with_lags as (
    select
        t.*,
        y1.revenue_ttm  as revenue_4q_ago,
        y1.earnings_ttm as earnings_4q_ago,
        y3.revenue_ttm  as revenue_12q_ago,
        y3.earnings_ttm as earnings_12q_ago,
        -- Số quý tuyệt đối, dùng cho cửa sổ theo LỊCH ở dưới.
        t.year * 4 + t.quarter as abs_quarter
    from ttm t
    left join ttm y1
           on y1.symbol = t.symbol and y1.year = t.year - 1 and y1.quarter = t.quarter
    left join ttm y3
           on y3.symbol = t.symbol and y3.year = t.year - 3 and y3.quarter = t.quarter
),

-- Cửa sổ 12 quý phải tính theo LỊCH, không theo 12 dòng liền kề — cùng lý
-- do như trên. `range` trên abs_quarter cho đúng ngữ nghĩa "12 quý gần
-- nhất", bất kể chuỗi có khoảng trống hay không.
with_windows as (
    select
        *,
        sum(case when is_loss_making then 1 else 0 end) over w12 as loss_quarters_12q
    from with_lags
    window w12 as (
        partition by symbol order by abs_quarter
        range between 11 preceding and current row
    )
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
    from with_windows
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
    -- Tính nhất quán tăng trưởng: tỉ lệ quý có YoY doanh thu dương trong 12
    -- quý. Cửa sổ theo LỊCH (`range` trên abs_quarter), không phải 12 dòng
    -- liền kề — cùng lý do với loss_quarters_12q ở trên (fix round 2).
    avg(case when revenue_yoy > 0 then 1.0
             when revenue_yoy is null then null
             else 0.0 end) over (
        partition by symbol order by abs_quarter
        range between 11 preceding and current row
    ) as growth_consistency
from with_growth
