{{ config(materialized='view') }}

-- Cổ đông ĐÃ CÔNG BỐ, snapshot theo ngày.
--
-- NGỮ NGHĨA QUAN TRỌNG (đo 2026-08-16): tổng share_own_percent KHÔNG bằng
-- 100% — HPG 51,9% (66 dòng), VNM 81,0% (93), VCB 91,0% (29). Đây là danh
-- sách cổ đông đã công bố ở nhiều quy mô (có cả dòng 0,0002%), không phải
-- chỉ cổ đông lớn >5%. Phần thiếu là cổ đông không công bố và KHÔNG đồng
-- nghĩa free float — dim_stock.free_float_percentage là con số khác, từ
-- nguồn khác. Mọi tầng dùng bảng này phải phơi total_disclosed_pct chứ
-- không để người đọc tự suy ra "100% trừ đi".
select
    symbol,
    share_holder,
    quantity,
    share_own_percent,
    update_date,
    snapshot_date
from {{ source('warehouse', 'raw_shareholder') }}
where share_holder is not null
