{{ config(materialized='table') }}

-- Percentile của từng chỉ tiêu trong NHÓM TƯƠNG ĐƯƠNG.
-- Ưu tiên nhóm hẹp (cùng com_class + cùng ngành ICB lv2); nếu nhóm quá nhỏ
-- thì lùi về cùng com_class toàn thị trường. peer_basis ghi lại lựa chọn đó
-- để agent nói rõ "rẻ hơn ngành" là so với bao nhiêu mã.
with base as (
    select
        symbol,
        com_class,
        coalesce(icb_code_lv2, 'UNKNOWN') as icb_code_lv2,
        metric,
        value
    from {{ ref('int_metric_long') }}
    -- Loại mã chưa xác định được loại hình khỏi MỌI rổ percentile (nợ N2 từ A1).
    -- Chúng thiếu dòng trong raw_company_info nên không biết áp bộ chỉ tiêu nào;
    -- để lẫn vào rổ sẽ làm lệch percentile của cả nhóm.
    where com_class <> 'UNKNOWN'
),

sized as (
    select
        *,
        count(*) over (partition by metric, com_class, icb_code_lv2) as n_sector,
        count(*) over (partition by metric, com_class)               as n_class
    from base
),

chosen as (
    select
        *,
        case when n_sector >= {{ var('peer_min_size') }}
             then 'com_class+icb_lv2' else 'com_class' end as peer_basis,
        case when n_sector >= {{ var('peer_min_size') }}
             then n_sector else n_class end                as peer_count
    from sized
),

ranked as (
    select
        *,
        percent_rank() over (
            partition by metric, com_class, icb_code_lv2 order by value
        ) as pct_sector,
        percent_rank() over (
            partition by metric, com_class order by value
        ) as pct_class
    from chosen
)

select
    symbol,
    com_class,
    icb_code_lv2,
    metric,
    value,
    peer_basis,
    peer_count,
    case
        when peer_count < {{ var('peer_hard_min') }} then null
        when peer_basis = 'com_class+icb_lv2'        then pct_sector
        else pct_class
    end as pct_peer
from ranked
