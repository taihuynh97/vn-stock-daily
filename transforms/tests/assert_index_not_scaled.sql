-- VNINDEX quanh 1.700 điểm. Nếu bị nhân nhầm x1000 sẽ ra ~1.700.000.
select index_code, trade_date, close
from {{ ref('stg_index_daily') }}
where index_code = 'VNINDEX'
  and (close < 500 or close > 5000)
