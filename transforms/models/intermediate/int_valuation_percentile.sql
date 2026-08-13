{{ config(materialized='table') }}

-- Percentile P/E và P/B của kỳ hiện tại SO VỚI CHÍNH MÃ trong 20 quý gần nhất.
-- Chỉ tính trên các quý mà tỷ số có nghĩa (loại quý lỗ và quý P/E dị thường).
with hist as (
    select
        symbol,
        period_end_date,
        year * 4 + quarter as abs_quarter,
        pe,
        pb,
        ps,
        case when pe_meaningful then pe end as pe_valid,
        case when pb_meaningful then pb end as pb_valid
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

ranked as (
    select
        *,
        percent_rank() over (
            partition by symbol order by pe_valid
        ) as pe_pct_all_history,
        percent_rank() over (
            partition by symbol order by pb_valid
        ) as pb_pct_all_history,
        -- Cửa sổ theo LỊCH (`range` trên abs_quarter), không theo dòng: 87% mã
        -- có khoảng trống chuỗi quý nên 20 dòng liền kề có thể trải dài hơn 5 năm.
        count(pe_valid) over (
            partition by symbol
            order by abs_quarter
            range between 19 preceding and current row
        ) as pe_quarters_20,
        count(pb_valid) over (
            partition by symbol
            order by abs_quarter
            range between 19 preceding and current row
        ) as pb_quarters_20
    from hist
)

select
    symbol,
    period_end_date,
    pe,
    pb,
    ps,
    -- Yêu cầu tối thiểu số quý hợp lệ, nếu không percentile không đáng tin.
    case when pe_quarters_20 >= {{ var('own_history_min_quarters') }}
         then pe_pct_all_history end as pe_pct_own_5y,
    case when pb_quarters_20 >= {{ var('own_history_min_quarters') }}
         then pb_pct_all_history end as pb_pct_own_5y,
    pe_quarters_20 as own_quarters_used
from ranked
