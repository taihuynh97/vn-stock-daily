{{ config(materialized='view') }}

-- Ban lãnh đạo + tỉ lệ sở hữu, snapshot theo ngày. Cùng cảnh báo ngữ nghĩa
-- như stg_shareholder: đây là phần ĐÃ CÔNG BỐ, không phải toàn bộ.
select
    symbol,
    officer_name,
    officer_position,
    officer_own_percent,
    officer_own_quantity,
    update_date,
    snapshot_date
from {{ source('warehouse', 'raw_officer') }}
where officer_name is not null
