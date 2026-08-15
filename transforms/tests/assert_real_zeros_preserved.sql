-- V7 (Task 8.5): canh lỗi NGƯỢC LẠI với assert_no_impossible_zero — NULL hoá
-- quá tay, xoá dữ liệu THẬT. Đây là rủi ro lớn hơn của task này: một test
-- chỉ canh chiều "còn sót sentinel" sẽ xanh rực rỡ trong khi hàng chục nghìn
-- điểm dữ liệu thật đã bị xoá âm thầm.
--
-- dividend_yield = 0 là giá trị THẬT (phần lớn DN Việt không trả cổ tức
-- trong quý), thuộc Nhóm B (TUYỆT ĐỐI giữ 0) — ngoại lệ DUY NHẤT là NULL hoá
-- bên trong 686 "dòng trắng" (is_blank_row trong stg_financial_ratio.sql).
-- Đo trên production TRƯỚC khi sửa: 38.112 dòng dividend_yield = 0. Cho phép
-- giảm tối đa 686 dòng (đúng số dòng trắng) — dưới ngưỡng 37.000 (38.112 -
-- 686 = 37.426, chừa biên) nghĩa là ai đó đã nullif dividend_yield toàn cục
-- nhầm, không chỉ trong phạm vi dòng trắng.
select count(*) as n_conserved
from {{ ref('stg_financial_ratio') }}
where dividend_yield = 0
having count(*) < 37000
