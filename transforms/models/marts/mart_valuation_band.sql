{{ config(materialized='table') }}

select
    v.symbol,
    v.period_end_date,
    d.com_class,
    d.icb_code_lv2,
    d.industry_lv2,
    v.pe,
    v.pb,
    v.ps,
    v.pe_pct_own_5y,
    v.pb_pct_own_5y,
    v.pe_quarters_used,
    v.pb_quarters_used,
    -- Nhãn vùng định giá dựa trên percentile lịch sử CỦA CHÍNH MÃ.
    -- NULL khi chưa đủ 12 quý hợp lệ — không đoán bừa.
    case
        when v.pe_pct_own_5y is null  then null
        when v.pe_pct_own_5y < 0.20   then 'rất rẻ'
        when v.pe_pct_own_5y < 0.40   then 'rẻ'
        when v.pe_pct_own_5y < 0.60   then 'hợp lý'
        when v.pe_pct_own_5y < 0.80   then 'đắt'
        else                               'rất đắt'
    end as valuation_band
from {{ ref('int_valuation_percentile') }} v
left join {{ ref('dim_stock') }} d using (symbol)
