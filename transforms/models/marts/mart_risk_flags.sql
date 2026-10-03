{{ config(materialized='table') }}

-- Cổng biến cố (mảng Q): mỗi mã một dòng, liệt kê tín hiệu cho thấy số liệu quá
-- khứ có thể KHÔNG còn đại diện — khi đó không được định giá theo Graham.
--
-- Bài học gốc: PNJ ngày 12/09/2026 được chấm 7/7 tiêu chí phòng thủ trong khi
-- (a) quý 2/2026 đã lỗ 739 tỷ trên BCTC gốc, (b) hai người nhà lãnh đạo đã đăng
-- ký bán 25 triệu cổ phiếu (công bố 04/09) — cả hai đều CÓ SẴN trong kho nhưng
-- không bước nào kiểm. 16 ngày sau PNJ công bố dự kiến lỗ cả năm ~6.271 tỷ.
--
-- Mức độ:
--   nghiem_trong → risk_gate = 'cho_bctc_ke_tiep': chưa định giá được.
--   canh_bao     → risk_gate = 'doc_tin_truoc'  : phải đọc tin trước khi kết luận.
-- Cửa sổ thời gian tính từ current_date (cùng quy ước mart_data_quality).
with stocks as (
    select symbol from {{ ref('dim_stock') }}
),

profit as (
    select q.symbol, q.period_end_date, q.net_profit, q.net_profit_yoy,
           q.loss_quarters_4q_actual
    from {{ ref('int_quarterly_profit') }} q
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('int_quarterly_profit') }} group by 1) m
      using (symbol, period_end_date)
),

px as (
    select p.symbol, p.pct_from_high_52w
    from {{ ref('int_price_features') }} p
    join (select symbol, max(trade_date) as trade_date
          from {{ ref('int_price_features') }} group by 1) m
      using (symbol, trade_date)
),

-- Phát hành làm pha loãng / gọi vốn: riêng lẻ, quyền mua, chuyển đổi trái
-- phiếu, chào bán rộng rãi. KHÔNG tính thưởng/cổ tức bằng cổ phiếu (không đổi
-- giá trị) và ESOP (nhỏ, thường niên).
dilution as (
    select symbol,
           count(*) as n_events,
           max(coalesce(exright_date, record_date, issue_date, public_date)) as last_date
    from {{ ref('stg_corporate_event') }}
    where event_code = 'ISS'
      and regexp_matches(lower(event_title_vi),
                         'riêng lẻ|quyền mua|chuyển đổi|rộng rãi|chào bán')
      and coalesce(exright_date, record_date, issue_date, public_date)
          >= current_date - interval 365 day
    group by 1
),

-- Đăng ký BÁN của người nội bộ (DDIND), cổ đông lớn/tổ chức liên quan (DDINS)
-- và người có liên quan (DDRP) còn hiệu lực hoặc kết thúc trong 90 ngày.
insider_sell as (
    select symbol,
           count(*) as n_events,
           max(coalesce(end_date, start_date, public_date)) as last_date
    from {{ ref('stg_corporate_event') }}
    where event_code in ('DDIND', 'DDINS', 'DDRP')
      and regexp_matches(event_title_vi, 'Đăng k[íý] Bán')
      and coalesce(end_date, start_date, public_date) >= current_date - interval 90 day
    group by 1
),

dq as (
    select symbol, ratio_age_days from {{ ref('mart_data_quality') }}
),

flags as (
    select
        s.symbol,
        coalesce(p.loss_quarters_4q_actual >= 1, false)                  as lo_quy_gan_day,
        -- net_profit_yoy chỉ có khi cùng kỳ năm trước dương; quý lỗ sau một
        -- quý lãi cho yoy < -1 nên cũng rơi vào đây.
        coalesce(p.net_profit_yoy < -0.5, false)                          as loi_nhuan_quy_giam_manh,
        coalesce(x.pct_from_high_52w <= -0.4, false)                      as gia_giam_sau,
        d.symbol is not null                                              as pha_loang_von,
        i.symbol is not null                                              as noi_bo_dang_ky_ban,
        coalesce(q.ratio_age_days > 150, true)                            as ty_so_cu,
        (p.symbol is null or p.period_end_date < current_date - interval 200 day)
                                                                          as khong_co_bctc_quy,
        p.period_end_date as profit_as_of,
        p.loss_quarters_4q_actual, p.net_profit_yoy,
        x.pct_from_high_52w,
        d.n_events as n_dilution_events, d.last_date as dilution_last_date,
        i.n_events as n_insider_sell_events, i.last_date as insider_sell_last_date,
        q.ratio_age_days
    from stocks s
    left join profit p using (symbol)
    left join px x using (symbol)
    left join dilution d using (symbol)
    left join insider_sell i using (symbol)
    left join dq q using (symbol)
),

listed as (
    select
        *,
        list_filter([
            {'code': 'lo_quy_gan_day', 'severity': 'nghiem_trong', 'on': lo_quy_gan_day,
             'text': 'Có ' || cast(loss_quarters_4q_actual as varchar)
                     || ' quý lỗ trong 4 quý BCTC gần nhất (đến '
                     || strftime(profit_as_of, '%d/%m/%Y') || ')'},
            {'code': 'loi_nhuan_quy_giam_manh', 'severity': 'nghiem_trong', 'on': loi_nhuan_quy_giam_manh,
             'text': 'LNST quý ' || strftime(profit_as_of, '%d/%m/%Y') || ' giảm '
                     || printf('%.0f', -net_profit_yoy * 100) || '% so với cùng kỳ'},
            {'code': 'gia_giam_sau', 'severity': 'canh_bao', 'on': gia_giam_sau,
             'text': 'Giá điều chỉnh thấp hơn đỉnh 52 tuần '
                     || printf('%.0f', -pct_from_high_52w * 100)
                     || '% — thị trường đang định giá lại, đọc tin trước'},
            {'code': 'pha_loang_von', 'severity': 'canh_bao', 'on': pha_loang_von,
             'text': cast(n_dilution_events as varchar)
                     || ' đợt phát hành riêng lẻ/quyền mua/chuyển đổi trong 12 tháng (gần nhất '
                     || strftime(dilution_last_date, '%d/%m/%Y') || ')'},
            {'code': 'noi_bo_dang_ky_ban', 'severity': 'canh_bao', 'on': noi_bo_dang_ky_ban,
             'text': cast(n_insider_sell_events as varchar)
                     || ' đăng ký bán của người nội bộ/cổ đông lớn trong 90 ngày (hiệu lực tới '
                     || strftime(insider_sell_last_date, '%d/%m/%Y') || ')'},
            {'code': 'ty_so_cu', 'severity': 'canh_bao', 'on': ty_so_cu,
             'text': 'Tỷ số tài chính mới nhất đã '
                     || coalesce(cast(ratio_age_days as varchar), '?') || ' ngày'},
            {'code': 'khong_co_bctc_quy', 'severity': 'canh_bao', 'on': khong_co_bctc_quy,
             'text': 'Không có BCTC quý trong 200 ngày gần đây — không kiểm được quý lỗ'}
        ], f -> f.on) as active
    from flags
)

select
    symbol,
    case
        when len(list_filter(active, f -> f.severity = 'nghiem_trong')) > 0 then 'cho_bctc_ke_tiep'
        when len(active) > 0                                               then 'doc_tin_truoc'
        else 'qua'
    end                                                        as risk_gate,
    len(list_filter(active, f -> f.severity = 'nghiem_trong')) as n_severe,
    len(list_filter(active, f -> f.severity = 'canh_bao'))     as n_warn,
    to_json(list_transform(active, f -> {'code': f.code, 'severity': f.severity, 'text': f.text}))
                                                               as flags,
    lo_quy_gan_day, loi_nhuan_quy_giam_manh, gia_giam_sau, pha_loang_von,
    noi_bo_dang_ky_ban, ty_so_cu, khong_co_bctc_quy,
    profit_as_of,
    current_date                                               as flags_as_of
from listed
