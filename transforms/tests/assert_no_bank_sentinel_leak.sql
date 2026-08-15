-- LỖI NGHIÊM TRỌNG NHẤT của spec: VCI dùng 0.0 để biểu thị "không áp dụng".
-- 187/187 dòng ngân hàng có roic=0 và current_ratio=0 — nếu để nguyên,
-- mọi ngân hàng bị chấm 0 điểm chất lượng và bị đọc là mất thanh khoản.
-- Sau staging, các chỉ tiêu phi tài chính của ngân hàng PHẢI là NULL.
select symbol, year, quarter, roic, current_ratio, ebit_margin
from {{ ref('stg_financial_ratio') }}
where com_class = 'BANK'
  and (roic is not null or current_ratio is not null or ebit_margin is not null)
