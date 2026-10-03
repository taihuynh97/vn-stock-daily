{{ config(materialized='table') }}

-- LNST TỪNG QUÝ đọc thẳng từ BCTC gốc (mảng Q).
--
-- Vì sao cần model này: `is_loss_making`/`loss_quarters_12q` của
-- int_fundamentals_ttm suy từ after_tax_profit_margin của nguồn tỷ số — biên
-- đó là LŨY KẾ 4 QUÝ (TTM). Một quý lỗ nằm giữa ba quý lãi lớn vẫn cho TTM
-- dương: PNJ 2026-Q2 lỗ 739 tỷ (BCTC gốc) nhưng biên TTM +5,6% và
-- loss_quarters_12q = 0. Đo 2026-10-03: 103 mã có quý lỗ thật trong 4 quý gần
-- nhất bị ghi 0 — trong đó có PNJ, STB, PLX, EIB. Bộ lọc "không quý nào lỗ"
-- ngày 12/09 đã để PNJ lọt qua vì cột đó.
--
-- Chọn dòng lợi nhuận theo thứ tự ưu tiên (đo 2026-10-03 trên BCTC quý):
--   1. attributable_to_parent_company — BANK 30/30, NONFIN 1158/1158, OTHERFIN 42/55
--   2. net_profit_attributable_to_shareholders_of_the_group — CTCK (13 mã còn lại)
--   3. net_profit_loss_after_tax, 4. profit_after_tax — dự phòng
-- item_id KHÔNG unique trong một báo cáo (xem B2) → mỗi item_id lấy dòng có
-- row_seq nhỏ nhất. Giá trị 0 đúng tuyệt đối coi là ô trống của nguồn (NULL):
-- lợi nhuận quý bằng đúng 0 đồng là bất khả thi kinh tế, cùng triết lý
-- sentinel 0.0 ở stg_financial_ratio.
with items as (
    select
        symbol,
        cast(left(period_label, 4) as integer)  as year,
        cast(right(period_label, 1) as integer) as quarter,
        item_id,
        row_seq,
        nullif(value, 0) as value,
        case
            when item_id = 'attributable_to_parent_company'                       then 1
            when item_id = 'net_profit_attributable_to_shareholders_of_the_group' then 2
            when item_id = 'net_profit_loss_after_tax'                            then 3
            when item_id = 'profit_after_tax'                                     then 4
        end as prio
    from {{ ref('stg_financial_statement') }}
    where statement_type = 'income_statement'
      and period_type = 'quarter'
      and item_id in ('attributable_to_parent_company',
                      'net_profit_attributable_to_shareholders_of_the_group',
                      'net_profit_loss_after_tax',
                      'profit_after_tax')
      and regexp_matches(period_label, '^\d{4}-q[1-4]$')
),

-- Khử trùng bằng GROUP BY + arg_min, KHÔNG bằng row_number()/QUALIFY: DuckDB
-- 1.5.3 ánh xạ nhầm cột khi lọc theo số thứ tự cửa sổ rồi cắt bớt cột ở bước
-- sau — đo được phép ép kiểu INT của period_label bị áp lên item_id
-- (Conversion Error 'attributable_to_parent_company' → INT32). Phiên bản gộp
-- nhóm cho cùng kết quả và không đi qua đường tối ưu đó.
per_item as (
    select symbol, year, quarter, item_id,
           min(prio)               as prio,
           arg_min(value, row_seq) as value
    from items
    where value is not null
    group by 1, 2, 3, 4
),

q as (
    select symbol, year, quarter,
           arg_min(value, prio)   as net_profit,
           arg_min(item_id, prio) as profit_item_id
    from per_item
    group by 1, 2, 3
),

with_yoy as (
    select
        q.symbol, q.year, q.quarter, q.net_profit, q.profit_item_id,
        last_day(make_date(q.year, q.quarter * 3, 1)) as period_end_date,
        q.year * 4 + q.quarter                        as abs_quarter,
        ly.net_profit                                 as net_profit_same_q_last_year
    from q
    left join q ly
           on ly.symbol = q.symbol and ly.year = q.year - 1 and ly.quarter = q.quarter
),

-- Cột tường minh, không `select *` (cùng lớp lỗi DuckDB 1.5.3 ghi ở per_item).
windowed as (
    select
        symbol, year, quarter, period_end_date, net_profit, profit_item_id,
        net_profit_same_q_last_year,
        (net_profit < 0) as is_loss_quarter,
        sum(case when net_profit < 0 then 1 else 0 end) over w4  as loss_4q_raw,
        count(net_profit)                               over w4  as observed_4q,
        sum(case when net_profit < 0 then 1 else 0 end) over w12 as loss_12q_raw,
        count(net_profit)                               over w12 as observed_12q
    from with_yoy
    window
        w4  as (partition by symbol order by abs_quarter range between 3  preceding and current row),
        w12 as (partition by symbol order by abs_quarter range between 11 preceding and current row)
)

select
    symbol,
    year,
    quarter,
    period_end_date,
    net_profit,
    profit_item_id,
    net_profit_same_q_last_year,
    -- Tăng trưởng cùng kỳ của RIÊNG quý này — chỉ khi cùng kỳ năm trước dương
    -- (chia cho mốc âm vô nghĩa, cùng luật với int_fundamentals_ttm).
    case when net_profit_same_q_last_year > 0
         then net_profit / net_profit_same_q_last_year - 1 end as net_profit_yoy,
    is_loss_quarter,
    -- Có ít nhất một quý quan sát được thì đếm được; 0 quý → NULL (không biết).
    case when observed_4q > 0 then loss_4q_raw end as loss_quarters_4q_actual,
    observed_4q,
    -- Cửa sổ 12 quý: cùng ngưỡng "ít nhất nửa cửa sổ" với loss_quarters_12q cũ.
    -- GIỚI HẠN NGUỒN (đo 2026-10-03): BCTC quý chỉ lưu ~8 kỳ gần nhất mỗi mã
    -- (cửa sổ trượt của B2), nên thực tế cửa sổ này thấy tối đa ~8 quý.
    case when observed_12q >= {{ var('window_min_observed_quarters') }}
         then loss_12q_raw end as loss_quarters_12q_actual,
    observed_12q
from windowed
