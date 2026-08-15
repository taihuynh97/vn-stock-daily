{{ config(materialized='view', tags=['daily']) }}

with deduped as (
    select
        upper(trim(symbol))      as symbol,
        cast(trade_date as date) as trade_date,
        cast(open   as double)   as open,
        cast(high   as double)   as high,
        cast(low    as double)   as low,
        cast(close  as double)   as close,
        cast(volume as bigint)   as volume,
        cast(value  as double)   as value_raw,
        row_number() over (
            partition by upper(trim(symbol)), cast(trade_date as date)
            order by loaded_at desc
        ) as rn
    from {{ source('warehouse', 'raw_price_daily') }}
    where close is not null
      and close > 0
)

select
    symbol,
    trade_date,
    open,
    high,
    low,
    close,
    volume,
    -- raw_price_daily.value tính bằng TRIỆU VNĐ trong khi giá tính bằng VNĐ.
    -- Xác minh HPG 2026-08-07: volume 13.018.100 x close 21.850 = 284 tỷ,
    -- còn value = 287.111,73 → hệ số 1e6.
    value_raw * 1e6                            as value_vnd,
    close * volume                             as turnover_proxy_vnd,
    -- value_vnd chỉ có từ 2026-06-07 (dòng backfill qua Quote.history đều NULL),
    -- nên dùng close*volume làm phương án thay thế cho lịch sử dài.
    coalesce(value_raw * 1e6, close * volume)  as turnover_vnd,
    (open is not null and high is not null and low is not null) as has_ohlc,
    (value_raw is not null)                    as has_value,
    (close < 100 or close > 5000000)           as is_suspect_price
from deduped
where rn = 1
