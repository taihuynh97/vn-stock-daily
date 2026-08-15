-- value_vnd phải xấp xỉ close * volume. Mục đích DUY NHẤT của test này là bắt
-- lệch đơn vị 10⁶ — không phải bắt nhiễu giá.
--
-- Dung sai ban đầu 30% cho 5/27.981 dòng (0,018%) fail trên production, với
-- mức lệch 32-40%. Đó KHÔNG phải lệch đơn vị (lệch 10⁶ tương đương 99.999.900%)
-- mà là nhiễu bình thường: giao dịch thoả thuận, hoặc close là giá khớp cuối
-- còn value tính theo giá bình quân cả phiên.
--
-- Nới lên 50%: vẫn bắt lệch đơn vị dư sức, mà không báo động sai. Một cổng
-- báo động sai liên tục thì tệ hơn không có cổng, vì người ta học cách bỏ qua
-- nó — bài học từ finding C4 của mảng A1.
select symbol, trade_date, value_vnd, turnover_proxy_vnd
from {{ ref('stg_price_daily') }}
where has_value
  and volume > 1000
  and turnover_proxy_vnd > 0
  and abs(value_vnd - turnover_proxy_vnd) / turnover_proxy_vnd > 0.50
