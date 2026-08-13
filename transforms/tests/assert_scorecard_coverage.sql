-- Phải chấm được ít nhất 800 mã với >= 3 trong 5 điểm thành phần.
select count(*) as n_qualified
from {{ ref('mart_stock_scorecard') }}
where (case when value_score    is not null then 1 else 0 end
     + case when quality_score  is not null then 1 else 0 end
     + case when growth_score   is not null then 1 else 0 end
     + case when dividend_score is not null then 1 else 0 end
     + case when safety_score   is not null then 1 else 0 end) >= 3
having count(*) < 800
