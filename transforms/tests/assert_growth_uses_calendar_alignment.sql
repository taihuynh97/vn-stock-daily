-- Fix round 2 (coordinator review, C1): canh đúng lớp lỗi đã xảy ra —
-- lag() theo VỊ TRÍ DÒNG thay vì theo LỊCH. 87% mã có khoảng trống trong
-- chuỗi quý (2021 Q2 chỉ 177/1.585 mã báo cáo), nên lag(x, 4) lấy nhầm
-- dòng ở đa số trường hợp — đo được 53% dòng revenue_yoy LẬT DẤU tăng
-- trưởng so với tính đúng theo lịch.
--
-- Khẳng định: mọi dòng có revenue_yoy phải TỒN TẠI kỳ đối chiếu đúng lịch
-- (cùng symbol, cùng quarter, year - 1) trong chính model.
select t.symbol, t.year, t.quarter
from {{ ref('int_fundamentals_ttm') }} t
left join {{ ref('int_fundamentals_ttm') }} y1
       on y1.symbol = t.symbol and y1.year = t.year - 1 and y1.quarter = t.quarter
where t.revenue_yoy is not null
  and y1.symbol is null
