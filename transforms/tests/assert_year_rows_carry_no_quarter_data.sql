-- Canh Important #3 của vòng review toàn nhánh: dòng NĂM thừa hưởng toàn bộ số
-- liệu suy ra của QUÝ 4.
--
-- stg_financial_ratio.sql (dòng 24-28) đã cảnh báo: dòng năm (quarter = 5) và
-- dòng quý 4 CÙNG ra period_end_date = 31/12, nên period_end_date không phải
-- khoá một mình. fct_financial_quarterly bản cũ join
-- `using (symbol, period_end_date)` vào int_fundamentals_ttm /
-- int_quality_metrics — hai model CHỈ chứa dòng quý — nên mọi dòng năm nhặt
-- đúng bản sao của quý 4. Đo trước khi sửa: dòng quý 4 và dòng năm có TRÙNG
-- KHÍT 10.706 revenue_ttm / 10.816 earnings_ttm / 10.816 eps / 10.518
-- roe_avg_8q. Trên dòng năm, earnings_ttm lệch market_cap/pe của CHÍNH dòng đó
-- ở 95,1% dòng, trung vị 25,3% (VCB 2024 hàm ý 48.530 tỷ, bị gắn 33.831 tỷ).
--
-- Test này KHÔNG bị test unique_combination_of_columns [symbol, year, quarter]
-- thay thế được: join sai vẫn 1:1, không nhân dòng, nên khoá vẫn duy nhất.
select symbol, year, quarter, period_type
from {{ ref('fct_financial_quarterly') }}
where quarter = 5
  and coalesce(
        revenue_ttm, earnings_ttm, book_value, eps, bvps,
        revenue_yoy, earnings_yoy, revenue_cagr_3y, earnings_cagr_3y,
        growth_consistency, cast(loss_quarters_12q as double),
        roe_avg_8q, roe_stability, gross_margin_slope_8q
      ) is not null
