{{ config(materialized='table') }}

-- Đặt tên KHÁC bảng nguồn dim_industry (177 dòng, do A1 tạo): project không
-- cấu hình schema riêng cho từng tầng nên mọi model dbt materialize vào
-- đúng schema `main` — nơi bảng nguồn dim_industry đang nằm. Một model tên
-- `dim_industry` sẽ chạy CREATE OR REPLACE TABLE main.dim_industry và xoá
-- sạch bảng nguồn đó.
--
-- Nguồn VCI đánh mã cấp 1 dạng '0001' không theo tiền tố, nên chỉ ghép được
-- cấp 2 → 4 bằng tiền tố mã ICB (0500 → 0530 → 0533).
with lv as (select * from {{ ref('stg_industry') }})

select
    l4.icb_code               as icb_code_lv4,
    l4.icb_name               as icb_name_lv4,
    l4.en_icb_name            as en_icb_name_lv4,
    l3.icb_code               as icb_code_lv3,
    l3.icb_name               as icb_name_lv3,
    l2.icb_code               as icb_code_lv2,
    l2.icb_name               as icb_name_lv2,
    l2.en_icb_name            as en_icb_name_lv2
from lv l4
left join lv l3
       on l3.level = 3 and substr(l4.icb_code, 1, 3) = substr(l3.icb_code, 1, 3)
left join lv l2
       on l2.level = 2 and substr(l4.icb_code, 1, 2) = substr(l2.icb_code, 1, 2)
where l4.level = 4
