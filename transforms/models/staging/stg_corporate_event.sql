{{ config(materialized='view') }}

-- Phân loại HAI TẦNG: `event_code` (có cấu trúc, tin được) làm tầng chính;
-- chỉ đọc tiêu đề tự do cho nhánh ISS, nơi event_code KHÔNG đủ phân biệt.
--
-- VÌ SAO KHÔNG DÙNG CỘT `category` CỦA NGUỒN: khảo sát 564 sự kiện / 12 mã
-- (2026-08-16) cho thấy nguồn gán TOÀN BỘ 33 dòng ISS vào
-- category='DIVIDEND', trong đó 9 dòng là "Phát hành cho CBCNV" (ESOP) và
-- 5 dòng "Phát hành riêng lẻ". Hai loại này PHA LOÃNG cổ đông hiện hữu —
-- tác động kinh tế NGƯỢC DẤU với phân phối. Tin `category` là đếm pha loãng
-- thành cổ tức. Giữ nguyên cột nguồn dưới tên `category_source` để truy vết,
-- nhưng KHÔNG dùng nó để suy diễn gì.
--
-- Nguyên tắc fail-closed: không khớp mẫu nào thì gán nhãn "không biết"
-- (ISS_KHAC / UNKNOWN_CODE) và is_distribution = false. Không đoán.
with typed as (
    select
        id,
        symbol,
        event_code,
        event_name_vi,
        event_title_vi,
        category as category_source,
        action_type_vi,
        exercise_ratio,
        value_per_share,
        public_date,
        issue_date,
        start_date,
        end_date,
        record_date,
        exright_date,
        listing_date,
        payout_date,
        ingested_at,
        lower(coalesce(event_title_vi, '')) as _title
    from {{ source('warehouse', 'raw_corporate_event') }}
),

classified as (
    select
        *,
        case
            when event_code = 'DIV' then 'CASH_DIVIDEND'
            when event_code = 'ISS' and _title like '%cổ tức bằng cổ phiếu%'
                then 'STOCK_DIVIDEND'
            when event_code = 'ISS' and _title like '%cổ phiếu thưởng%'
                then 'BONUS_SHARE'
            when event_code = 'ISS' and (
                     _title like '%cbcnv%' or _title like '%cbnv%'
                     or _title like '%esop%')
                then 'ESOP'
            when event_code = 'ISS' and _title like '%riêng lẻ%'
                then 'PRIVATE_PLACEMENT'
            when event_code = 'ISS' then 'ISS_KHAC'
            when event_code in ('DDIND', 'DDINS', 'DDRP') then 'INSIDER_TRADING'
            when event_code in ('AGME', 'AGMR', 'EGME') then 'SHAREHOLDER_MEETING'
            when event_code in ('AIS', 'OTHE', 'MOVE', 'NLIS', 'SUSP') then 'OTHER'
            else 'UNKNOWN_CODE'
        end as distribution_type
    from typed
)

-- Suy diễn cờ ở SELECT NGOÀI, không cùng bậc với case sinh ra
-- distribution_type: bài học A2 (`pb_meaningful` viết cùng bậc với nullif
-- khiến alias phân giải về cột raw, 1.797 dòng sai).
select
    id,
    symbol,
    event_code,
    event_name_vi,
    event_title_vi,
    category_source,
    action_type_vi,
    exercise_ratio,
    value_per_share,
    public_date,
    issue_date,
    start_date,
    end_date,
    record_date,
    exright_date,
    listing_date,
    payout_date,
    ingested_at,
    distribution_type,
    distribution_type in ('CASH_DIVIDEND', 'STOCK_DIVIDEND', 'BONUS_SHARE')
        as is_distribution
from classified
