{{ config(materialized='table', tags=['daily']) }}

-- Chỉ số thị trường ở tầng mart (mảng Q). Trước đây raw_index_daily có đủ
-- VNINDEX/VN30/HNXINDEX từ 2016 nhưng không mart nào dùng, và mã `VNI` trong
-- fct_price_daily là MỘT CỔ PHIẾU — từng bị nhầm là VN-Index khi so sánh.
-- Số phiên lùi giống int_price_features (21/63/126/250). Chỉ số không có sự
-- kiện điều chỉnh nên dùng close trực tiếp.
select
    index_code,
    trade_date,
    open, high, low, close, volume,
    close / nullif(lag(close, 21)  over w, 0) - 1 as return_1m,
    close / nullif(lag(close, 63)  over w, 0) - 1 as return_3m,
    close / nullif(lag(close, 126) over w, 0) - 1 as return_6m,
    close / nullif(lag(close, 250) over w, 0) - 1 as return_12m,
    close / nullif(first_value(close) over (partition by index_code, year(trade_date)
                                            order by trade_date), 0) - 1 as return_ytd
from {{ ref('stg_index_daily') }}
window w as (partition by index_code order by trade_date)
