-- Không điểm thành phần nào được tồn tại khi đo được dưới một nửa trọng số.
-- Đây là test canh trực tiếp cho lỗi "van luôn mở": trước khi sửa, 617 cặp
-- (mã, thành phần) có điểm mà trọng số đo được < 0,5 — trong đó 442 ở thành
-- phần tăng trưởng, tệ nhất là điểm 100/100 dựng trên đúng 10% trọng số.
select symbol, 'value' as component, value_score, value_weight_coverage
from {{ ref('mart_stock_scorecard') }}
where value_score is not null and value_weight_coverage < 0.5
union all
select symbol, 'quality', quality_score, quality_weight_coverage
from {{ ref('mart_stock_scorecard') }}
where quality_score is not null and quality_weight_coverage < 0.5
union all
select symbol, 'growth', growth_score, growth_weight_coverage
from {{ ref('mart_stock_scorecard') }}
where growth_score is not null and growth_weight_coverage < 0.5
union all
select symbol, 'dividend', dividend_score, dividend_weight_coverage
from {{ ref('mart_stock_scorecard') }}
where dividend_score is not null and dividend_weight_coverage < 0.5
union all
select symbol, 'safety', safety_score, safety_weight_coverage
from {{ ref('mart_stock_scorecard') }}
where safety_score is not null and safety_weight_coverage < 0.5
