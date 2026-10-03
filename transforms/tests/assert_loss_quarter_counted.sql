-- Mảng Q: một quý lỗ thật phải được đếm trong cửa sổ 4 quý của chính nó.
-- Đây là bất biến mà loss_quarters_12q cũ (đếm TTM âm) vi phạm ở 103 mã.
select symbol, year, quarter, net_profit, loss_quarters_4q_actual
from {{ ref('int_quarterly_profit') }}
where is_loss_quarter
  and coalesce(loss_quarters_4q_actual, 0) < 1
