{{ config(materialized='table') }}

with ratio_stats as (
    select
        symbol,
        count(*) filter (where quarter between 1 and 4) as quarters_available,
        date_diff('day', max(period_end_date), current_date) as ratio_age_days
    from {{ ref('stg_financial_ratio') }}
    group by 1
),

-- Khoảng trống đo bằng SỐ PHIÊN THỊ TRƯỜNG BỊ BỎ, không phải số ngày lịch.
-- Đã đo trên production: nghỉ Tết 2026 tạo khoảng trống đúng 10 NGÀY LỊCH cho
-- 891/1.577 mã. Ngưỡng ">10 ngày lịch" của bản kế hoạch cũ chỉ vừa đủ không
-- nổ — Tết dài thêm một ngày là cờ nổ cho 891 mã và thành phần điểm này mất
-- sạch ý nghĩa. Đếm phiên bị bỏ thì miễn nhiễm với lịch nghỉ: đã kiểm, khoảng
-- trống Tết cho ra ĐÚNG 0 phiên bị bỏ, vì thị trường đóng cửa không phải lỗi
-- của mã nào.
market_sessions as (
    select trade_date, row_number() over (order by trade_date) as session_no
    from (
        select distinct trade_date
        from {{ ref('stg_price_daily') }}
        where trade_date >= current_date - interval '365 days'
    )
),

symbol_sessions as (
    select
        p.symbol,
        m.session_no,
        lag(m.session_no) over (partition by p.symbol order by m.session_no)
            as prev_session_no
    from {{ ref('stg_price_daily') }} p
    join market_sessions m using (trade_date)
    where p.trade_date >= current_date - interval '365 days'
),

price_stats as (
    -- lag() ở CTE trên, max() ở đây — hai bậc riêng. Không lồng hàm cửa sổ vào
    -- hàm tổng hợp: SQL không cho phép, và dự án này đã vấp đúng lỗi đó ở Task 3.
    select
        symbol,
        count(*)                              as price_sessions_1y,
        max(session_no - prev_session_no - 1) as max_missed_sessions
    from symbol_sessions
    group by 1
),

-- Ngân hàng phải có NIM và NPL; phi tài chính phải có ROIC. Thiếu = sentinel
-- chưa được xử lý đúng hoặc nguồn không trả dữ liệu.
--
-- OTHERFIN (công ty chứng khoán, bảo hiểm) dùng CHUNG bộ chỉ tiêu với NONFIN
-- theo phán quyết ở Task 2, nên phải chịu CÙNG phép kiểm. Bản đầu viết `else 1`
-- cho nhóm này: 54 mã tự động đạt mà không kiểm gì, nhưng vẫn ăn trọn 15% trọng
-- số của `data_quality_score` — và cột đó chảy thẳng vào `mart_stock_scorecard`
-- lẫn ngưỡng lọc `min_data_quality_score` của screener, nên 15 điểm cho không
-- có thể đẩy một mã qua mốc 60. Một phép kiểm không bao giờ trượt thì tệ hơn
-- không có phép kiểm, vì nó tạo cảm giác an toàn.
--
-- Đã đo trên production trước khi sửa: cả 54 mã OTHERFIN đều có `roic` ở kỳ mới
-- nhất, nên thay đổi này KHÔNG đổi điểm mã nào hôm nay. Giá trị của nó là bịt
-- lỗ hổng cho mai sau.
--
-- `UNKNOWN` giữ `else 1` vì nhóm này không có dòng nào trong stg_financial_ratio
-- (10 mã thiếu hồ sơ) nên không bao giờ tới được nhánh đó; chúng nhận 0 qua
-- `coalesce` ở CTE `scored`.
required_ok as (
    select
        f.symbol,
        max(case
            when f.com_class = 'BANK'
                then (f.net_interest_margin is not null and f.npl is not null)::int
            when f.com_class in ('NONFIN', 'OTHERFIN')
                then (f.roic is not null)::int
            else 1
        end) as has_required_metrics
    from {{ ref('stg_financial_ratio') }} f
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('stg_financial_ratio') }} where quarter between 1 and 4
          group by 1) m using (symbol, period_end_date)
    -- Lọc dòng quý ở CẢ query ngoài, không chỉ trong subquery. Dòng năm
    -- (quarter = 5) dùng CHUNG period_end_date = 31/12 với dòng quý 4 — đã đo
    -- trên production: tại 2025-12-31 có 1.390 dòng quý VÀ 1.438 dòng năm.
    -- Thiếu mệnh đề này thì mọi mã có kỳ mới nhất là quý 4 sẽ kéo cả dòng năm
    -- vào, và max() nhặt giá trị dễ dãi hơn giữa hai trục sentinel khác nhau —
    -- báo "đủ chỉ tiêu bắt buộc" cho mã thực ra không đủ.
    where f.quarter between 1 and 4
    group by 1
),

scored as (
    select
        d.symbol,
        coalesce(r.quarters_available, 0)  as quarters_available,
        coalesce(p.price_sessions_1y, 0)   as price_sessions_1y,
        r.ratio_age_days,
        -- Giữ NULL ở đầu ra, KHÔNG coalesce về 999. Một mã chưa có phiên giá
        -- nào thì "số phiên bỏ" là không đo được, không phải 999. coalesce chỉ
        -- được dùng bên trong công thức điểm bên dưới.
        p.max_missed_sessions,
        coalesce(q.has_required_metrics, 0) as has_required_metrics,
        -- 5 thành phần, tổng trọng số = 1.
        0.30 * least(1.0, coalesce(r.quarters_available, 0) / 20.0)
      + 0.25 * least(1.0, coalesce(p.price_sessions_1y, 0) / 240.0)
      + 0.20 * case when r.ratio_age_days is null then 0.0
                    when r.ratio_age_days <= 120  then 1.0
                    when r.ratio_age_days <= 240  then 0.5
                    else 0.0 end
      + 0.15 * coalesce(q.has_required_metrics, 0)
      -- Ngưỡng 5 phiên = hơn một tuần giao dịch. Phân bố đã đo trên production:
      -- 612 mã bỏ 0 phiên · 242 mã bỏ 1-2 · 154 mã bỏ 3-5 · 188 mã bỏ 6-10 ·
      -- 381 mã bỏ >10 (tệ nhất là BDB, chỉ giao dịch 47 trong 247 phiên, có lúc
      -- bỏ liền 200 phiên).
      + 0.10 * case when coalesce(p.max_missed_sessions, 999) <= 5 then 1.0 else 0.0 end
            as ratio
    from {{ ref('dim_stock') }} d
    left join ratio_stats r using (symbol)
    left join price_stats p using (symbol)
    left join required_ok q using (symbol)
)

select
    symbol,
    quarters_available,
    price_sessions_1y,
    ratio_age_days,
    max_missed_sessions,
    (has_required_metrics = 1) as has_required_metrics,
    ratio                      as data_quality_ratio,
    round(ratio * 100, 1)      as data_quality_score,
    concat_ws('; ',
        case when quarters_available < 12 then 'thiếu lịch sử tỷ số (<12 quý)' end,
        case when price_sessions_1y < 200 then 'thiếu phiên giá trong 1 năm' end,
        case when ratio_age_days > 240    then 'tỷ số quá cũ (>8 tháng)' end,
        case when has_required_metrics = 0 then 'thiếu chỉ tiêu bắt buộc của loại hình' end,
        case when max_missed_sessions > 5 then 'bỏ >5 phiên giao dịch liên tiếp' end
    ) as quality_flags
from scored
