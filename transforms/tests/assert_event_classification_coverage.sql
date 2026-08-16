-- Canh parser xuống cấp âm thầm. Ngưỡng 5% chọn từ mẫu khảo sát thật:
-- 564 sự kiện / 12 mã (2026-08-16) cho 0 dòng chưa phân loại (33/33 ISS
-- khớp một trong bốn mẫu tiêu đề), nên 5% là biên rất rộng — vượt qua
-- nghĩa là nguồn đã đổi format thật, không phải nhiễu.
--
-- Mở mẫu từ 1 mã (HPG) lên 12 mã đã lộ thêm 5 event_code chưa từng thấy
-- (AGMR, EGME, MOVE, NLIS, SUSP), nên gặp code lạ là chuyện chắc chắn xảy
-- ra — nhánh UNKNOWN_CODE tồn tại để nuốt chúng an toàn, còn test này để
-- báo khi số lượng vượt mức chấp nhận được.
with tally as (
    select
        count(*) as n_total,
        count(*) filter (
            where distribution_type in ('ISS_KHAC', 'UNKNOWN_CODE')
        ) as n_unclassified
    from {{ ref('stg_corporate_event') }}
)
select
    n_total,
    n_unclassified,
    n_unclassified::double / nullif(n_total, 0) as pct_unclassified
from tally
where n_total > 0
  and n_unclassified::double / n_total > 0.05
