-- Giá cổ phiếu VN luôn nằm trong [100, 5.000.000] VNĐ.
-- Nếu fail: nhiều khả năng lệch đơn vị (nghìn VNĐ vs VNĐ).
select symbol, trade_date, close
from {{ ref('stg_price_daily') }}
where close < 100 or close > 5000000
