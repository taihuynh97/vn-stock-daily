{{ config(materialized='table') }}

-- Gốc là dim_symbols, KHÔNG phải stg_company_info. Một mã mới niêm yết có
-- giá ngay từ phiên đầu, nhưng hồ sơ doanh nghiệp chỉ được job HẰNG THÁNG
-- nạp về — nên luôn tồn tại một cửa sổ nhiều tuần trong đó mã đã có giá mà
-- chưa có hồ sơ (case thật: PCB lên sàn 2026-08-12, có giá, VCI CÓ hồ sơ
-- nhưng warehouse chưa kịp nạp). Nếu lấy stg_company_info làm gốc thì mọi
-- mã mới lên sàn đều thành dòng mồ côi trong fct_price_daily và test
-- relationships fail — lặp lại vô hạn, không phải sự cố một lần. dim_symbols
-- là tập cha thật sự của mọi mã có giá, nên dùng làm gốc ở đây.
-- Mã thiếu hồ sơ (DPD/PYU/TAC: nguồn VCI trả rỗng thật, không phải do nạp
-- thiếu) vào bảng với com_class = 'UNKNOWN' và has_profile = false.
with px as (
    -- Phiên mới nhất THEO TỪNG MÃ, không phải phiên mới nhất toàn thị
    -- trường: mã đã ngừng giao dịch sẽ dừng lại ở phiên cuối cùng của nó,
    -- và price_as_of tồn tại chính là để nói ra điều đó thay vì bị NULL hoá
    -- hay ép về phiên mới nhất chung.
    select p.*
    from {{ ref('int_price_features') }} p
    join (select symbol, max(trade_date) as trade_date
          from {{ ref('int_price_features') }} group by 1) m
      using (symbol, trade_date)
),

ind2 as (
    select icb_code, icb_name, en_icb_name from {{ ref('stg_industry') }} where level = 2
),
ind4 as (
    select icb_code, icb_name, en_icb_name from {{ ref('stg_industry') }} where level = 4
)

select
    s.symbol,
    c.company_name,
    c.short_name,
    coalesce(c.exchange, s.exchange) as exchange,
    coalesce(c.com_class, 'UNKNOWN') as com_class,
    c.com_type_code,
    c.is_bank,
    c.icb_code_lv2,
    i2.icb_name    as industry_lv2,
    i2.en_icb_name as industry_lv2_en,
    c.icb_code_lv4,
    i4.icb_name    as industry_lv4,
    c.sector,
    c.market_cap,
    c.issue_share,
    c.free_float_percentage,
    c.foreigner_percentage,
    c.state_percentage,
    c.listed_date,
    c.listing_age_years,
    px.trade_date       as price_as_of,
    px.close            as last_close,
    px.avg_turnover_20d,
    px.avg_turnover_60d,
    px.volatility_60d,
    px.high_52w,
    px.low_52w,
    px.return_1m,
    px.return_3m,
    px.return_12m,
    px.sessions_1y,
    s.is_active,
    (c.symbol is not null) as has_profile
from {{ source('warehouse', 'dim_symbols') }} s
left join {{ ref('stg_company_info') }} c on c.symbol = s.symbol
left join px on px.symbol = s.symbol
left join ind2 i2 on i2.icb_code = c.icb_code_lv2
left join ind4 i4 on i4.icb_code = c.icb_code_lv4
