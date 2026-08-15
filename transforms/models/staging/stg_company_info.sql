{{ config(materialized='view') }}

select
    symbol,
    company_name,
    short_name,
    exchange,
    com_type_code,
    is_bank,
    -- Phân loại quyết định bộ chỉ tiêu nào áp dụng và so sánh trong nhóm nào.
    -- Nguồn chính là com_type_code — trường phân loại trực tiếp của VCI:
    -- CT = công ty thường, NH = ngân hàng, BH = bảo hiểm, CK = chứng khoán.
    -- Xác minh khi triển khai A1: VCB=NH, VNR=BH, SHS=CK, HPG/VNM/IDV/PHP=CT.
    -- Cách này sạch hơn suy từ `sector`; is_bank/sector chỉ còn là phương án
    -- dự phòng khi com_type_code thiếu.
    case
        when com_type_code = 'NH'                          then 'BANK'
        when com_type_code in ('BH', 'CK')                 then 'OTHERFIN'
        when com_type_code = 'CT'                          then 'NONFIN'
        when is_bank or sector = 'Banks'                   then 'BANK'
        when sector in ('Insurance', 'Financial Services') then 'OTHERFIN'
        else 'NONFIN'
    end                                       as com_class,
    icb_code_lv2,
    icb_code_lv4,
    sector,
    market_cap,
    issue_share,
    free_float_percentage,
    foreigner_percentage,
    maximum_foreign_percentage,
    state_percentage,
    avg_match_value_1m,
    avg_match_volume_1m,
    highest_price_1y,
    lowest_price_1y,
    listed_date,
    date_diff('year', listed_date, current_date) as listing_age_years
from {{ source('warehouse', 'raw_company_info') }}
