-- Canh Important #4 của vòng review toàn nhánh: chuỗi năm trả cổ tức bị NỐI
-- LIỀN qua khoảng trống dữ liệu.
--
-- int_dividend_history cắt chuỗi bằng năm gần nhất KHÔNG trả cổ tức. Task 8.5
-- NULL hoá dividend_yield trong 686 "dòng trắng" (497 trong đó là dòng năm),
-- và bộ lọc `dividend_yield is not null` cũ khiến đúng những năm chặn đó biến
-- mất khỏi model. Kết quả đo trước khi sửa: VOC nhảy 0 → 7 năm, BBC 0 → 5,
-- 31 mã đổi chuỗi, 30 mã biến mất hẳn, 115 mã đổi max_year.
--
-- Nguyên tắc bị vi phạm: một năm mà ta KHÔNG BIẾT có trả cổ tức hay không phải
-- CẮT chuỗi. Không biết ≠ có trả.
--
-- Bất biến kiểm ở đây là hệ quả trực tiếp và mạnh nhất của nguyên tắc đó: nếu
-- NĂM MỚI NHẤT trên sổ của một mã không có cổ tức dương (0, âm, hoặc không
-- biết) thì chuỗi "liên tiếp tính lùi từ năm gần nhất" BẮT BUỘC bằng 0. Đây
-- đúng ca VOC (2025 là dòng trắng) mà bản cũ trả về 7.
--
-- Nghiêm trọng vì dividend_years_consecutive vừa chiếm 30% thành phần điểm cổ
-- tức, vừa là bộ lọc cứng `dividend_years_min` của screener.
with yearly as (
    select
        symbol,
        year,
        dividend_yield,
        row_number() over (partition by symbol order by year desc) as rn
    from {{ ref('stg_financial_ratio') }}
    where quarter = 5
)

select d.symbol, d.dividend_years_consecutive, y.year as latest_year_on_record,
       y.dividend_yield as latest_dividend_yield
from {{ ref('int_dividend_history') }} d
join yearly y on y.symbol = d.symbol and y.rn = 1
where d.dividend_years_consecutive > 0
  and coalesce(y.dividend_yield, 0) <= 0
