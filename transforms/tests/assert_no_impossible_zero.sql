-- C1 (fix round 1): sentinel 0.0 còn sót theo trục THỨ HAI — kỳ báo cáo, không
-- chỉ com_class. Đo trên production (md:vn_market, raw_financial_ratio):
--   car:  100% dòng BANK quý 1/3/4 = 0 chính xác (223/224, 199/199, 204/204);
--         quý 2 chỉ 49.3%, quý năm 12.6% — mất sạch vốn tự có là bất khả thi
--         với một ngân hàng đang hoạt động.
--   debt_to_equity: 0% ở quý 1-4 nhưng 100% (207/207) ở dòng NĂM của BANK —
--         không huy động đồng nào là bất khả thi. Với NONFIN, 0 là giá trị
--         THẬT (DN không vay nợ) nên KHÔNG được nullif toàn cục — chỉ khoanh
--         vùng BANK trong model.
--   average_cost_of_financing: 0 tập trung ở nhóm ngân hàng nhỏ/mới thiếu dữ
--         liệu nguồn (EVF 39/40=97.5%, KLB 38/42=90.5%...) trong khi 16/29
--         ngân hàng lớn (VCB, BID, CTG, MBB...) không có dòng nào = 0 — chi
--         phí huy động vốn bằng 0 chính xác là bất khả thi với bất kỳ ngân
--         hàng nào đang hoạt động.
-- Ba cột này đã được stg_financial_ratio.sql nullif() theo đúng phạm vi trên.
-- Test này bắt hồi quy nếu nullif bị xoá/sai lệch phạm vi.
select 'car' as metric, symbol, year, quarter, car as value
from {{ ref('stg_financial_ratio') }}
where com_class = 'BANK' and car = 0

union all

select 'debt_to_equity', symbol, year, quarter, debt_to_equity
from {{ ref('stg_financial_ratio') }}
where com_class = 'BANK' and debt_to_equity = 0

union all

select 'average_cost_of_financing', symbol, year, quarter, average_cost_of_financing
from {{ ref('stg_financial_ratio') }}
where com_class = 'BANK' and average_cost_of_financing = 0

-- V7 (Task 8.5): trục sentinel THỨ BA — 7 chỉ tiêu COMMON (áp dụng cho MỌI
-- com_class, không khoanh vùng như ba cột phía trên) mà 0 bất khả thi kinh
-- tế. Nặng nhất là roe: 1.661 dòng roe=0 trên production trước khi sửa,
-- toàn bộ ở NONFIN — ví dụ APT/JOS/HLA đang lỗ (roa<0) mà roe=0 là vô nghĩa,
-- 95,3% số dòng còn lại (ngoài 686 dòng "trắng") có debt_per_equity<0 hoặc
-- pb=0 làm chứng. Sáu cột còn lại (pe/pb/ps/ev_to_ebitda/price_to_cash_flow/
-- market_cap) cùng lý do "giá hoặc mẫu số bằng 0" — xem comment nullif() của
-- từng cột trong stg_financial_ratio.sql.

union all

select 'roe', symbol, year, quarter, roe
from {{ ref('stg_financial_ratio') }}
where roe = 0

union all

select 'pe', symbol, year, quarter, pe
from {{ ref('stg_financial_ratio') }}
where pe = 0

union all

select 'pb', symbol, year, quarter, pb
from {{ ref('stg_financial_ratio') }}
where pb = 0

union all

select 'ps', symbol, year, quarter, ps
from {{ ref('stg_financial_ratio') }}
where ps = 0

union all

select 'ev_to_ebitda', symbol, year, quarter, ev_to_ebitda
from {{ ref('stg_financial_ratio') }}
where ev_to_ebitda = 0

union all

select 'price_to_cash_flow', symbol, year, quarter, price_to_cash_flow
from {{ ref('stg_financial_ratio') }}
where price_to_cash_flow = 0

union all

select 'market_cap', symbol, year, quarter, market_cap
from {{ ref('stg_financial_ratio') }}
where market_cap = 0
