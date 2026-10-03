{{ config(severity='warn') }}
-- Mảng Q: dòng bảng giá ghi sau khi sửa ánh xạ cột (có ref_price) phải có close
-- trong [low, high] khi có khớp lệnh. Trước sửa, 52–63% dòng hằng ngày vi phạm
-- vì close = giá tham chiếu. Lớp chặn chính nằm ở src/dq.assert_ohlc_consistent
-- (làm đỏ job ingest); test này là lưới thứ hai ở tầng warehouse.
select symbol, trade_date, low, high, close
from {{ ref('stg_price_daily') }}
where ref_price is not null
  and is_ohlc_inconsistent
