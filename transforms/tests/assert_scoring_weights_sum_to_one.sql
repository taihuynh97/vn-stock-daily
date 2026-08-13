-- Cổng chặn ở `gated` so trọng số dùng được với TỔNG trọng số định nghĩa. Nếu
-- một nhóm (com_class, component) không tổng bằng 1,0 thì ngưỡng 0,5 mang
-- nghĩa khác đi mà không ai nhận ra. Test này khoá bất biến đó lại.
select com_class, component, sum(weight) as total_weight
from {{ ref('scoring_weights') }}
group by 1, 2
having abs(sum(weight) - 1.0) > 0.001
