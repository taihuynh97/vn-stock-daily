-- C2 (fix round 1): OTHERFIN (bảo hiểm/chứng khoán) có giá trị THẬT ở 14/15
-- chỉ tiêu nhóm NONFIN — brief cũ "OTHERFIN chỉ dùng nhóm COMMON" sai. Đo trên
-- production: BH 478/478 (100%) và CK ~1.396/1.402 (99,6%) có roic/
-- current_ratio/ebit khác NULL. Chỉ days_inventory_outstanding thật sự không
-- áp dụng (chứng khoán/bảo hiểm không có hàng tồn kho).
-- Test này canh vùng mù: cả 3 test sentinel/coverage khác đều lọc theo
-- com_class = 'BANK'/'NONFIN'/'UNKNOWN' nên không cái nào chạm tới OTHERFIN —
-- nếu macro applicable_metrics() ngừng cấp nhóm NONFIN cho OTHERFIN (hồi quy),
-- không test nào khác bắt được. Ngưỡng 90% để chừa biên cho vài dòng thiếu
-- dữ liệu nguồn thật (đo được ~99,7%).
select
    count(*) as n_otherfin,
    round(sum(case when roic is not null then 1 else 0 end) * 100.0 / count(*), 1) as roic_pct,
    round(sum(case when current_ratio is not null then 1 else 0 end) * 100.0 / count(*), 1) as current_ratio_pct,
    round(sum(case when ebit is not null then 1 else 0 end) * 100.0 / count(*), 1) as ebit_pct
from {{ ref('stg_financial_ratio') }}
where com_class = 'OTHERFIN'
having
    round(sum(case when roic is not null then 1 else 0 end) * 100.0 / count(*), 1) < 90
    or round(sum(case when current_ratio is not null then 1 else 0 end) * 100.0 / count(*), 1) < 90
    or round(sum(case when ebit is not null then 1 else 0 end) * 100.0 / count(*), 1) < 90
