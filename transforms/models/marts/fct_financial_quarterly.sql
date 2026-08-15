{{ config(materialized='table') }}

select
    f.symbol,
    f.year,
    f.quarter,
    f.period_end_date,
    f.period_type,
    f.com_class,
    f.* exclude (symbol, year, quarter, period_end_date, period_type,
                 com_class, ratio_type, icb_code_lv2, icb_code_lv4),
    t.revenue_ttm,
    t.earnings_ttm,
    t.book_value,
    t.eps,
    t.bvps,
    t.revenue_yoy,
    t.earnings_yoy,
    t.revenue_cagr_3y,
    t.earnings_cagr_3y,
    t.growth_consistency,
    t.loss_quarters_12q,
    q.roe_avg_8q,
    q.roe_stability,
    q.gross_margin_slope_8q
-- Fix vòng review toàn nhánh (Important #3): các cột TTM/chất lượng chỉ được
-- gắn vào DÒNG QUÝ. Bản cũ join `using (symbol, period_end_date)` mà không lọc
-- quarter, trong khi chính stg_financial_ratio.sql (dòng 24-28) đã cảnh báo:
-- dòng NĂM (quarter = 5) và dòng QUÝ 4 CÙNG ra period_end_date = 31/12, nên
-- period_end_date KHÔNG phải khoá một mình. int_fundamentals_ttm và
-- int_quality_metrics chỉ chứa dòng quý ⟹ mọi dòng năm nhặt đúng bản sao của
-- quý 4.
--
-- Đo trên production trước khi sửa — trùng khít từng con số, là bản sao chứ
-- không phải trùng hợp: dòng quý 4 có 10.706 revenue_ttm / 10.816 earnings_ttm
-- / 10.816 eps / 10.518 roe_avg_8q, và dòng NĂM có ĐÚNG 10.706 / 10.816 /
-- 10.816 / 10.518. Mức sai: trên dòng năm, earnings_ttm không khớp
-- market_cap/pe của CHÍNH dòng đó ở 10.200/10.725 dòng (95,1%), sai số tương
-- đối trung vị 25,3%. VCB 2024 dòng năm: pe = 10,3303 và market_cap = 501.340
-- tỷ hàm ý lợi nhuận 48.530 tỷ, nhưng bị gắn 33.831 tỷ (số của quý 4,
-- pe = 14,8188).
--
-- Hướng sửa giữ nguyên HẠT của bảng (vẫn đủ cả dòng quý lẫn dòng năm — test
-- unique_combination_of_columns [symbol, year, quarter] dựa vào đó) và để các
-- cột TTM/chất lượng NULL ở dòng năm. Thà TRỐNG còn hơn gắn số của kỳ khác:
-- NULL nói "kỳ này không có số liệu TTM", một con số sai nói "có, và đây là
-- nó". Mệnh đề `f.quarter between 1 and 4` nằm TRONG điều kiện LEFT JOIN (không
-- phải WHERE) nên không loại dòng năm khỏi kết quả, chỉ chặn nó bắt cặp.
--
-- Dùng điều kiện join tường minh thay cho `using`: int_quality_metrics không có
-- cột quarter (chỉ symbol / period_end_date / com_class) nên không thể ghép
-- theo (symbol, year, quarter) như int_fundamentals_ttm; một dạng thức chung
-- cho cả hai dễ đối chiếu hơn.
from {{ ref('stg_financial_ratio') }} f
left join {{ ref('int_fundamentals_ttm') }} t
       on t.symbol = f.symbol
      and t.period_end_date = f.period_end_date
      and f.quarter between 1 and 4
left join {{ ref('int_quality_metrics') }} q
       on q.symbol = f.symbol
      and q.period_end_date = f.period_end_date
      and f.quarter between 1 and 4
