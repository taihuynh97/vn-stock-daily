-- Fix round 1 (coordinator review): bản gốc kiểm TỪNG DÒNG với dải
-- market_cap/100..market_cap*100 — báo động sai 344/36.676 dòng (0,94%)
-- trên production, toàn bộ là mã cực đoan CÓ THẬT (VEF/SQC ôm quỹ đất
-- doanh thu gần zero, nano-cap thanh khoản cực mỏng), không phải lỗi công
-- thức (HPG 2024Q4/2023Q2 khớp 0% tuyệt đối). Một cổng kiểm từng dòng như
-- vậy đỏ vĩnh viễn cho ~1% thị trường thật — tệ hơn không có cổng (bài học
-- C4 mảng A1).
--
-- Đổi sang kiểm TỔNG THỂ: revenue_ttm = market_cap/ps (khi ps>0) nên
-- market_cap/revenue_ttm = ps đại số. Một lỗi công thức HỆ THỐNG (quên
-- chia, chia nhầm cột, sai đơn vị) kéo TRUNG VỊ của tỉ lệ này lệch nhiều
-- bậc độ lớn trên toàn thị trường; vài trăm mã cực đoan không đủ sức kéo
-- trung vị lệch khỏi dải hợp lý (var fundamentals_median_ps_min/max, xem
-- dbt_project.yml).
with stats as (
    select median(market_cap / revenue_ttm) as median_market_cap_to_revenue
    from {{ ref('int_fundamentals_ttm') }}
    where revenue_ttm is not null
)

select
    'median_market_cap_to_revenue_out_of_range' as check_failed,
    median_market_cap_to_revenue                as value
from stats
where median_market_cap_to_revenue is null
   or median_market_cap_to_revenue < {{ var('fundamentals_median_ps_min') }}
   or median_market_cap_to_revenue > {{ var('fundamentals_median_ps_max') }}

union all

-- Rào chắn hồi quy rẻ tiền: sau bước NULL hoá ps<=0 ở model, không dòng
-- nào còn revenue_ttm <= 0 — nếu có, nghĩa là rào chắn đó bị gỡ/hỏng.
select
    'revenue_ttm_nonpositive' as check_failed,
    revenue_ttm                as value
from {{ ref('int_fundamentals_ttm') }}
where revenue_ttm <= 0
