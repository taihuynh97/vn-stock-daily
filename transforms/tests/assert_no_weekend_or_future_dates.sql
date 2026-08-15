-- Không có phiên rơi vào T7/CN hoặc ở tương lai.
-- DuckDB: isodow() trả 1=T2 ... 6=T7, 7=CN.
select symbol, trade_date
from {{ ref('stg_price_daily') }}
where isodow(trade_date) >= 6
   or trade_date > current_date
