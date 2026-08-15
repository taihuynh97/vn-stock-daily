{{ config(materialized='view') }}

-- Bảng ICB phẳng, một dòng mỗi mã ngành. Việc ghép phân cấp nằm ở mart
-- dim_industry — nguồn VCI dùng mã cấp 1 dạng '0001' không theo tiền tố,
-- nên chỉ ghép được cấp 2→4 bằng tiền tố mã.
select
    trim(icb_code)    as icb_code,
    trim(icb_name)    as icb_name,
    trim(en_icb_name) as en_icb_name,
    cast(level as integer) as level
from {{ source('warehouse', 'dim_industry') }}
where icb_code is not null
