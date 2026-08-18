{{ config(materialized='table') }}

-- CẢNH BÁO ĐỒNG BỘ (Important #6, final review C1): phép gộp trong file này
-- được CÀI ĐẶT LẠI MỘT LẦN NỮA, độc lập, bằng Python tại
-- `mcp_server/tools.py::_ownership_change` — vì C1 cần so sánh sở hữu giữa
-- HAI mốc thời gian, còn model này cố ý chỉ giữ snapshot MỚI NHẤT nên không
-- dùng lại được. Hai bản phải cho cùng kết quả khi xét cùng một snapshot_date.
--
-- Nếu sửa công thức gộp ở đây — sum(share_own_percent), cách tính top1_pct /
-- top5_pct, cách chọn snapshot_date của cổ đông và của officer, hay cách xử
-- lý NULL — PHẢI sửa tương ứng ở _ownership_change. KHÔNG có test tự động
-- nào bắt được sự lệch pha này: test đối chiếu duy nhất
-- (test_ownership_change_khop_int_ownership_snapshot) so với một dòng VIẾT
-- TAY trong fixture, không chạy model này, nên nó vẫn xanh khi 2 bản đã lệch.
-- Chặn được thật sự thì cần `dbt build` trong CI — nợ kỹ thuật đã biết.
--
-- Cô đặc cơ cấu sở hữu theo snapshot MỚI NHẤT mỗi mã.
--
-- total_disclosed_pct là cột BẮT BUỘC, không phải tuỳ chọn: tổng % công bố
-- không bằng 100% (HPG 51,9%, VNM 81,0%, VCB 91,0% — đo 2026-08-16), nên
-- nếu chỉ phơi top1/top5 mà giấu tổng thì người đọc rất dễ suy ra sai
-- "phần còn lại là free float". Đây đúng pattern "một con số cần được phơi
-- kèm bằng chứng đỡ nó" đã dùng bốn lần ở A2 (pe_quarters_used, n_pe,
-- *_weight_coverage, rejected_total).
with sh_latest as (
    select symbol, max(snapshot_date) as snapshot_date
    from {{ ref('stg_shareholder') }}
    group by 1
),

sh as (
    select s.*
    from {{ ref('stg_shareholder') }} s
    join sh_latest l
      on s.symbol = l.symbol and s.snapshot_date = l.snapshot_date
),

ranked as (
    select
        *,
        row_number() over (
            partition by symbol order by share_own_percent desc nulls last
        ) as rn
    from sh
),

sh_agg as (
    select
        symbol,
        max(snapshot_date) as snapshot_date,
        count(*) as n_disclosed,
        sum(share_own_percent) as total_disclosed_pct,
        max(case when rn = 1 then share_own_percent end) as top1_pct,
        sum(case when rn <= 5 then share_own_percent end) as top5_pct
    from ranked
    group by 1
),

of_latest as (
    select symbol, max(snapshot_date) as snapshot_date
    from {{ ref('stg_officer') }}
    group by 1
),

-- officer_snapshot_date (I1, fix round cuối): sh_agg.snapshot_date là ngày
-- snapshot của CỔ ĐÔNG, không phải của officer. Hai ngày này có thể lệch
-- nhau nếu một mã lỗi fetch ở lần chạy monthly này cho MỘT TRONG HAI nguồn
-- nhưng không phải cả hai (fetch_shareholders/fetch_officers đều bọc
-- `except Exception: continue` theo từng mã). get_ownership từng dùng
-- snapshot_date (của cổ đông) để lọc CẢ stg_officer — khi lệch, officers
-- trả về rỗng trong khi insider_pct (tính đúng từ ngày khác) vẫn có số.
-- Phơi thêm officer_snapshot_date để tầng gọi lọc đúng ngày của từng bảng,
-- thay vì âm thầm dùng chung một ngày cho cả hai.
of_agg as (
    select
        o.symbol,
        l.snapshot_date as officer_snapshot_date,
        sum(o.officer_own_percent) as insider_pct
    from {{ ref('stg_officer') }} o
    join of_latest l
      on o.symbol = l.symbol and o.snapshot_date = l.snapshot_date
    group by 1, 2
)

select
    a.symbol,
    a.snapshot_date,
    a.n_disclosed,
    a.total_disclosed_pct,
    a.top1_pct,
    a.top5_pct,
    o.insider_pct,
    o.officer_snapshot_date
from sh_agg a
left join of_agg o on a.symbol = o.symbol
