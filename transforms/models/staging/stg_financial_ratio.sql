{{ config(materialized='view') }}

with joined as (
    select
        f.*,
        -- KHÔNG mặc định 'NONFIN' (khoản nợ N2 từ A1). Một ngân hàng thiếu dòng
        -- trong raw_company_info mà bị gán NONFIN sẽ giữ nguyên cụm sentinel 0.0
        -- của nhóm NONFIN (roic=0, current_ratio=0) như GIÁ TRỊ THẬT, đồng thời
        -- NULL hoá NIM/NPL/CAR thật của nó → bị chấm điểm chất lượng bét bảng.
        -- Và assert_no_bank_sentinel_leak KHÔNG bắt được, vì nó lọc
        -- `where com_class='BANK'` — mã bị phân loại nhầm đã trượt khỏi phạm vi test.
        coalesce(c.com_class, 'UNKNOWN') as com_class,
        c.icb_code_lv2,
        c.icb_code_lv4
    from {{ source('warehouse', 'raw_financial_ratio') }} f
    left join {{ ref('stg_company_info') }} c using (symbol)
),

cleaned as (
    select
        symbol,
        year,
        quarter,
        period_type,
        ratio_type,
        com_class,
        icb_code_lv2,
        icb_code_lv4,
        -- quarter 1-4 = TTM kết thúc tại quý đó; quarter 5 = cả năm.
        case
            when quarter between 1 and 4
                then last_day(make_date(year, quarter * 3, 1))
            else make_date(year, 12, 31)
        end as period_end_date
        {{ applicable_metrics() }}
    from joined
    where year is not null and quarter is not null
)

select
    * exclude (cir, average_cost_of_financing),
    -- Nguồn trả CIR và chi phí vốn theo quy ước dấu ÂM (VCB: cir = -0,4098).
    abs(cir)                       as cir,
    abs(average_cost_of_financing) as average_cost_of_financing,
    -- Cờ ngữ nghĩa tài chính: P/E âm khi lỗ, P/E rất lớn khi lãi sát 0.
    (pe < 0)                       as is_loss_making,
    (pe > 0 and pe < 200)          as pe_meaningful,
    (pb > 0 and pb < 30)           as pb_meaningful
from cleaned
