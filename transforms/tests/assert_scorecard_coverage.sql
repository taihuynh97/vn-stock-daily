-- Phải chấm được ít nhất 1.400 mã với >= 3 trong 5 điểm thành phần.
-- Review vòng 1 (Minor #5): giá trị thật đo được là 1.552 và brief nêu sàn
-- an toàn là 1.400. Ngưỡng 800 cũ không bắt được sự cố nào cho tới khi mất
-- gần một nửa độ phủ — quá lỏng để có tác dụng canh hồi quy.
select count(*) as n_qualified
from {{ ref('mart_stock_scorecard') }}
where (case when value_score    is not null then 1 else 0 end
     + case when quality_score  is not null then 1 else 0 end
     + case when growth_score   is not null then 1 else 0 end
     + case when dividend_score is not null then 1 else 0 end
     + case when safety_score   is not null then 1 else 0 end) >= 3
having count(*) < 1400
