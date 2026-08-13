-- Fix vòng sửa 1 (Task 8.5, phát hiện Critical): canh LỚP LỖI "alias trùng
-- tên phân giải về cột raw", không chỉ ba trường hợp đã vá hôm nay.
--
-- `pb_meaningful` cũ viết `(pb > 0 and pb < 30)` NGAY TRONG CÙNG select đang
-- khai báo lại `nullif(pb, 0) as pb` — alias `pb` trùng tên cột nguồn khiến
-- DuckDB phân giải `pb` trần về cột THÔ (trước nullif), không phải giá trị
-- đã NULL hoá. Hậu quả: 1.797 dòng pb=0 (đã NULL đúng ở output pb) lại nhận
-- pb_meaningful = false ("chắc chắn không có nghĩa") thay vì NULL ("không
-- biết") — CHÍNH lớp lỗi Task 8.5 tồn tại để diệt, chỉ đổi từ trục số 0 sang
-- trục boolean. `is_loss_making` (đọc after_tax_profit_margin) mắc lỗi
-- tương tự với 686 dòng "trắng" (Nhóm C). Đã sửa gốc bằng cách tách CTE
-- `nulled` (mọi NULL hoá) khỏi bậc suy diễn cờ (đọc từ `nulled`, không đọc
-- lại `cleaned`) — xem stg_financial_ratio.sql.
--
-- Bất biến kiểm ở đây: một cờ boolean suy từ cột X phải NULL ("không biết")
-- CHÍNH XÁC khi X là NULL, không được suy ra false/true "chắc chắn" từ một
-- giá trị mà chính pipeline coi là không biết. Test fail khi vỡ bất biến ở
-- BẤT KỲ cờ suy diễn nào trong tương lai, không chỉ ba cờ hôm nay — miễn là
-- cờ mới cũng được thêm vào danh sách UNION dưới đây.
select 'pe_meaningful' as flag, symbol, year, quarter, pe as source_value, pe_meaningful as flag_value
from {{ ref('stg_financial_ratio') }}
where (pe is null) != (pe_meaningful is null)

union all

select 'pb_meaningful', symbol, year, quarter, pb, pb_meaningful
from {{ ref('stg_financial_ratio') }}
where (pb is null) != (pb_meaningful is null)

union all

select 'is_loss_making', symbol, year, quarter, after_tax_profit_margin, is_loss_making
from {{ ref('stg_financial_ratio') }}
where (after_tax_profit_margin is null) != (is_loss_making is null)
