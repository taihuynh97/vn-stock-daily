-- Chiều ngược lại: doanh nghiệp phi tài chính không được có chỉ tiêu ngân hàng.
select symbol, year, quarter, npl, net_interest_margin, cir
from {{ ref('stg_financial_ratio') }}
where com_class = 'NONFIN'
  and (npl is not null or net_interest_margin is not null or cir is not null)
