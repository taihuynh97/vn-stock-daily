{{ config(materialized='table') }}

-- CỬA SỔ THEO LỊCH, KHÔNG THEO DÒNG.
--
-- 1.378/1.585 mã (87%) có khoảng trống trong chuỗi quý báo cáo — riêng 2021 Q2
-- chỉ 177/1.585 mã báo cáo. Nên `rows between 7 preceding` KHÔNG phải "8 quý
-- gần nhất" mà là "8 dòng gần nhất", có thể trải dài nhiều năm. Đây đúng lớp
-- lỗi đã xảy ra ở int_fundamentals_ttm với lag() theo dòng.
--
-- `abs_quarter = year * 4 + quarter` cho phép dùng `range`, tức cửa sổ theo
-- khoảng cách LỊCH thật. Nó cũng là biến chạy đúng cho regr_slope: hệ số góc
-- phải là "thay đổi biên gộp trên mỗi QUÝ", không phải "trên mỗi dòng có dữ liệu".
with q as (
    select symbol, period_end_date, com_class, roe, gross_margin,
           year * 4 + quarter as abs_quarter
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

rolled as (
    select
        symbol,
        period_end_date,
        com_class,
        avg(roe)         over w8 as roe_avg_8q,
        stddev_samp(roe) over w8 as roe_sd_8q,
        count(roe)       over w8 as roe_n_8q,
        -- Hệ số góc xu hướng biên gộp: dương = biên đang cải thiện.
        regr_slope(gross_margin, abs_quarter) over w8 as gross_margin_slope_8q
    from q
    window w8 as (partition by symbol order by abs_quarter
                  range between 7 preceding and current row)
)

select
    symbol,
    period_end_date,
    com_class,
    roe_avg_8q,
    gross_margin_slope_8q,
    -- Độ bền ROE = 1 - hệ số biến thiên, chặn về [0, 1].
    -- Doanh nghiệp lỗ (ROE trung bình <= 0) KHÔNG có "độ bền" → 0.
    case
        when roe_n_8q < 4 or roe_avg_8q is null then null
        when roe_avg_8q <= 0                    then 0.0
        else greatest(0.0, least(1.0, 1 - roe_sd_8q / nullif(abs(roe_avg_8q), 0)))
    end as roe_stability
from rolled
