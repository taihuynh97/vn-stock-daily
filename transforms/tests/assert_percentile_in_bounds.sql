-- Mọi percentile (so với chính mã lẫn so với nhóm tương đương) phải nằm
-- trong [0, 1] — percent_rank() theo định nghĩa toán học đã đảm bảo điều
-- này, test này canh phòng lỗi logic khi ghép nối/lọc làm sai lệch giá trị.
select symbol, metric, pct_peer
from {{ ref('int_metric_percentile') }}
where pct_peer is not null and (pct_peer < 0 or pct_peer > 1)

union all

select symbol, 'pe_pct_own_5y' as metric, pe_pct_own_5y
from {{ ref('int_valuation_percentile') }}
where pe_pct_own_5y is not null and (pe_pct_own_5y < 0 or pe_pct_own_5y > 1)
