-- value_vnd phải xấp xỉ close * volume. Sai lệch > 30% nghĩa là lệch đơn vị.
-- Chỉ kiểm khi cả hai đều có dữ liệu và khối lượng đủ lớn để tỉ lệ có nghĩa.
select symbol, trade_date, value_vnd, turnover_proxy_vnd
from {{ ref('stg_price_daily') }}
where has_value
  and volume > 1000
  and turnover_proxy_vnd > 0
  and abs(value_vnd - turnover_proxy_vnd) / turnover_proxy_vnd > 0.30
