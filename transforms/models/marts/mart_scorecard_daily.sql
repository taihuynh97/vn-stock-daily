{{ config(
    materialized='incremental',
    unique_key=['snapshot_date', 'symbol'],
    incremental_strategy='delete+insert'
) }}

-- Ảnh chụp scorecard mỗi lần build (mảng Q). mart_stock_scorecard bị ghi đè
-- mỗi ngày nên không tái lập được "hôm 12/09 điểm của PNJ là bao nhiêu" — phân
-- tích cũ không đối chiếu được bằng số. Khoá = ngày phiên mới nhất của THỊ
-- TRƯỜNG (không phải price_as_of từng mã: mã tạm ngừng mang ngày cũ, sẽ ghi đè
-- ảnh chụp cũ). Build lại cùng ngày thay thế ảnh chụp của ngày đó.
with snap as (
    select max(price_as_of) as snapshot_date from {{ ref('mart_stock_scorecard') }}
)
select
    snap.snapshot_date,
    s.symbol,
    s.com_class,
    s.last_close,
    s.price_as_of,
    s.ratio_as_of,
    s.value_score, s.quality_score, s.growth_score, s.dividend_score, s.safety_score,
    s.pe_current, s.pb_current, s.valuation_band_current,
    s.loss_quarters_4q_actual,
    s.risk_gate,
    s.data_quality_score,
    current_timestamp as built_at
from {{ ref('mart_stock_scorecard') }} s
cross join snap
