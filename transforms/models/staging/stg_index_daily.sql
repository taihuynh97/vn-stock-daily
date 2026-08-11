{{ config(materialized='view', tags=['daily']) }}

with deduped as (
    select
        upper(trim(index_code))  as index_code,
        cast(trade_date as date) as trade_date,
        cast(open   as double)   as open,
        cast(high   as double)   as high,
        cast(low    as double)   as low,
        cast(close  as double)   as close,
        cast(volume as bigint)   as volume,
        row_number() over (
            partition by upper(trim(index_code)), cast(trade_date as date)
            order by loaded_at desc
        ) as rn
    from {{ source('warehouse', 'raw_index_daily') }}
    where close is not null
)

-- LƯU Ý: giá trị chỉ số KHÔNG đổi đơn vị (VNINDEX ~1.768 điểm là đúng).
select index_code, trade_date, open, high, low, close, volume
from deduped
where rn = 1
