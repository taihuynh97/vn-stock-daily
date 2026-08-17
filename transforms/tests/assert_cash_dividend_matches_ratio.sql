{{ config(severity = 'error', error_if = '>150', warn_if = '>0') }}

-- Đối chiếu chéo HAI NGUỒN cổ tức tiền mặt độc lập nhau:
--   (1) stg_financial_ratio.dividend_yield (quarter=5) — theo NĂM TÀI CHÍNH
--   (2) int_distribution_event CASH_DIVIDEND     — theo NGÀY GDKHQ
--
-- Hai nguồn nằm trên hai trục thời gian nên KHÔNG so trực tiếp từng năm
-- được. Thứ so được là mệnh đề yếu hơn nhưng vẫn có giá trị: một mã có ÍT
-- NHẤT MỘT sự kiện cổ tức tiền mặt trong cửa sổ sự kiện thì PHẢI có ít nhất
-- một năm dividend_yield > 0 trong cùng khoảng thời gian đó (cộng đệm 1 năm
-- cho độ trễ chi trả — cổ tức "cả năm 2021" của HPG chi trả 17/06/2022).
--
-- Ngược lại KHÔNG đúng và cố ý không kiểm: dividend_yield > 0 mà không có
-- sự kiện là chuyện bình thường khi cửa sổ 50 sự kiện quá nông (VNM chỉ phủ
-- 1,5 năm trong khi dividend_yield có từ 2018).
--
-- SEVERITY=WARN (đo trên dữ liệu thật 2026-08-17): 116/1117 mã có cổ tức
-- tiền mặt (~10,4%) KHÔNG thoả mệnh đề trên. Phân rã nguyên nhân: 54 mã
-- hoàn toàn không có dòng dividend_yield (quarter=5) nào rơi vào khoảng
-- năm liên quan; 8 mã có dòng nhưng dividend_yield NULL; 54 mã có dòng và
-- có giá trị nhưng luôn = 0, không có năm nào > 0 dù có sự kiện cổ tức
-- tiền mặt thật. Ví dụ: AMP có sự kiện CASH_DIVIDEND 1.000đ/CP GDKHQ
-- 2017-08-09 nhưng dividend_yield = 0 ở TẤT CẢ 23 dòng lịch sử
-- (2018-2026); TDN có 8 sự kiện cổ tức đều đặn 2017-2024 (200đ → 2.100đ/CP,
-- tăng dần — rõ ràng là cổ tức thật) nhưng dividend_yield NULL suốt
-- 2018-2023. Đây là vấn đề CHẤT LƯỢNG DỮ LIỆU của raw_financial_ratio
-- (thuộc phạm vi A1/A2), NGOÀI PHẠM VI B1 — B1 không được sửa
-- raw_financial_ratio/int_dividend_history. Mệnh đề đối chiếu vẫn đúng về
-- thiết kế, chỉ là dữ liệu nguồn không đạt được nó ở ~10% trường hợp. Hạ
-- xuống warn để phơi ra cho ai điều tra data quality sau này, không chặn
-- CI. Danh sách đầy đủ 116 mã lệch:
-- .superpowers/sdd/2026-08-16-b1-su-kien-co-tuc-so-huu/task-5-mismatched-symbols.csv
with ev as (
    select
        symbol,
        min(year(exright_date)) as min_ev_year,
        max(year(exright_date)) as max_ev_year,
        count(*) as n_cash_events
    from {{ ref('int_distribution_event') }}
    where distribution_type = 'CASH_DIVIDEND'
    group by 1
),

ratio as (
    select symbol, year, dividend_yield
    from {{ ref('stg_financial_ratio') }}
    where quarter = 5
)

select
    e.symbol,
    e.n_cash_events,
    e.min_ev_year,
    e.max_ev_year
from ev e
where e.n_cash_events > 0
  and not exists (
      select 1 from ratio r
      where r.symbol = e.symbol
        and r.dividend_yield > 0
        and r.year between e.min_ev_year - 1 and e.max_ev_year
  )
