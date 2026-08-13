-- Phép thử trực tiếp cho lỗi sentinel: ngân hàng PHẢI có quality_score.
-- Nếu sentinel chưa được khử, mọi ngân hàng sẽ có quality_score NULL hoặc 0.
select count(*) as n_banks_scored
from {{ ref('mart_stock_scorecard') }}
where com_class = 'BANK' and quality_score is not null and quality_score > 0
having count(*) < 20
