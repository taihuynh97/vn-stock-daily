{{ config(materialized='view') }}

-- Làm sạch nhẹ raw_financial_statement — không tính lại gì, không JOIN
-- com_class (cột đó không có ở tầng này, xem Global Constraints của plan).
-- Ai cần lọc theo loại hình DN thì JOIN dim_stock USING (symbol) ở tầng
-- gọi model này.
select
    symbol,
    statement_type,
    period_type,
    period_label,
    row_seq,
    item_id,
    item_vi,
    item_en,
    value
from {{ source('warehouse', 'raw_financial_statement') }}
