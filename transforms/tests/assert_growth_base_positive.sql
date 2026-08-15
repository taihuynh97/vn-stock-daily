-- Canh Important #2 của vòng review toàn nhánh: tăng trưởng YoY tính qua MỐC
-- GỐC ÂM làm lật dấu — lỗ phình to đọc thành tăng trưởng đỉnh bảng.
--
-- int_fundamentals_ttm vốn CÓ rào chắn đúng cho earnings_cagr_3y
-- (`earnings_12q_ago > 0 and earnings_ttm > 0`) nhưng THIẾU cho earnings_yoy,
-- cách đó 5 dòng. Đo trước khi sửa (kỳ mới nhất, 1.585 mã): 165 mã tính YoY
-- qua mốc gốc <= 0, trong đó 37 mã ĐANG LỖ nhận YoY DƯƠNG — TSC lỗ 36 tỷ nhận
-- +93,9 với pct_peer = 1,000 (đứng đầu rổ tăng trưởng ngành), KVC và ICF cũng
-- 1,000; chiều ngược lại 352 mã đang CÓ LÃI nhận YoY âm.
--
-- Bất biến: mọi chỉ tiêu tăng trưởng dạng tỉ số chỉ được tồn tại khi MẪU SỐ
-- (kỳ đối chiếu theo LỊCH) dương thật sự. Kỳ đối chiếu ở đây ghép theo lịch
-- (year - 1, cùng quarter) y hệt model — xem assert_growth_uses_calendar_alignment
-- cho lý do không dùng lag() theo dòng.
select 'earnings_yoy' as metric, t.symbol, t.year, t.quarter,
       y1.earnings_ttm as base_value, t.earnings_yoy as growth_value
from {{ ref('int_fundamentals_ttm') }} t
left join {{ ref('int_fundamentals_ttm') }} y1
       on y1.symbol = t.symbol and y1.year = t.year - 1 and y1.quarter = t.quarter
where t.earnings_yoy is not null
  and coalesce(y1.earnings_ttm, 0) <= 0

union all

select 'revenue_yoy', t.symbol, t.year, t.quarter, y1.revenue_ttm, t.revenue_yoy
from {{ ref('int_fundamentals_ttm') }} t
left join {{ ref('int_fundamentals_ttm') }} y1
       on y1.symbol = t.symbol and y1.year = t.year - 1 and y1.quarter = t.quarter
where t.revenue_yoy is not null
  and coalesce(y1.revenue_ttm, 0) <= 0

union all

select 'earnings_cagr_3y', t.symbol, t.year, t.quarter, y3.earnings_ttm, t.earnings_cagr_3y
from {{ ref('int_fundamentals_ttm') }} t
left join {{ ref('int_fundamentals_ttm') }} y3
       on y3.symbol = t.symbol and y3.year = t.year - 3 and y3.quarter = t.quarter
where t.earnings_cagr_3y is not null
  and coalesce(y3.earnings_ttm, 0) <= 0

union all

select 'revenue_cagr_3y', t.symbol, t.year, t.quarter, y3.revenue_ttm, t.revenue_cagr_3y
from {{ ref('int_fundamentals_ttm') }} t
left join {{ ref('int_fundamentals_ttm') }} y3
       on y3.symbol = t.symbol and y3.year = t.year - 3 and y3.quarter = t.quarter
where t.revenue_cagr_3y is not null
  and coalesce(y3.revenue_ttm, 0) <= 0
