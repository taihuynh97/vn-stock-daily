-- Biên độ giá sàn VN: HOSE 7%, HNX 10%, UPCOM 15% mỗi phiên — nên biến động
-- (độ lệch chuẩn suất sinh lời ngày, volatility_60d) trên 20%/phiên là bất
-- khả thi về mặt vật lý thị trường trong điều kiện giao dịch bình thường.
--
-- Lớp lỗi test này canh: khoảng trống do tạm ngừng giao dịch dài ngày rò rỉ
-- vào daily_return mà chưa được rào chắn theo gap_days (fix round 1, case
-- PTM nghỉ giao dịch 2018-11-27 → 2025-08-22: volatility_60d giả đo được
-- 0,905 tức 90,5%/phiên, kéo dài suốt ~60 phiên sau khi giao dịch lại). Xem
-- comment gap_days/has_gap trong int_price_features.sql.
select symbol, trade_date, volatility_60d
from {{ ref('int_price_features') }}
where volatility_60d > 0.20
