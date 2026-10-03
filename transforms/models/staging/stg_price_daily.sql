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
        -- Mảng Q: ref_price + khối ngoại chỉ có ở dòng bảng giá ghi SAU khi sửa
        -- ánh xạ cột (NULL ở dòng lịch sử/nạp bù). loaded_at là "mốc điều
        -- chỉnh" mà int_price_adjustment dùng: dòng lấy từ Quote.history SAU
        -- một sự kiện đã được nguồn điều chỉnh cho sự kiện đó.
        cast(ref_price as double)            as ref_price,
        cast(foreign_buy_volume  as bigint)  as foreign_buy_volume,
        cast(foreign_sell_volume as bigint)  as foreign_sell_volume,
        cast(foreign_buy_value   as double)  as foreign_buy_value,
        cast(foreign_sell_value  as double)  as foreign_sell_value,
        loaded_at,
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
    ref_price,
    foreign_buy_volume,
    foreign_sell_volume,
    foreign_buy_value,
    foreign_sell_value,
    loaded_at,
    -- TRUE khi phiên có khớp lệnh mà close nằm ngoài [low, high] — dấu hiệu
    -- ánh xạ cột sai (lỗi mảng Q: close = giá tham chiếu từ 07/06/2026).
    coalesce(volume > 0 and high is not null and low is not null
             and (close > high * 1.0001 or close < low * 0.9999), false)
                                               as is_ohlc_inconsistent,
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
