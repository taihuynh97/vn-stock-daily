{{ config(materialized='table') }}

-- Đếm trên các dòng NĂM (quarter = 5), không phải dòng TTM.
--
-- Fix vòng review toàn nhánh (Important #4): KHÔNG được lọc
-- `dividend_yield is not null` ở đây. Task 8.5 NULL hoá dividend_yield trong
-- 686 "dòng trắng" (is_blank_row — nguồn trả cả bản ghi toàn 0.0 vì không có
-- dữ liệu gì cho kỳ đó), trong đó 497 là dòng NĂM. Bộ lọc cũ khiến đúng những
-- năm đó BIẾN MẤT khỏi model — mà cơ chế cắt chuỗi dưới đây dựa vào SỰ TỒN TẠI
-- của dòng có giá trị <= 0 để chặn. Năm biến mất ⟹ chuỗi được nối liền im lặng
-- qua khoảng trống.
--
-- Đo trên production trước khi sửa: 31 mã đổi dividend_years_consecutive, 5 mã
-- bị THỔI PHỒNG — VOC 0 → 7 năm, BBC 0 → 5, VHI/CEG/HNE 0 → 1 — và 30 mã biến
-- mất hoàn toàn khỏi bảng, 115 mã đổi max_year (đổi luôn cửa sổ 5 năm của
-- dividend_yield_avg_5y). VOC là ca điển hình: năm mới nhất trên sổ (2025) là
-- dòng trắng nên bị loại, bảng tuyên bố "trả cổ tức 7 năm liên tiếp" trong khi
-- kỳ gần nhất có dữ liệu KHÔNG có số liệu cổ tức nào.
--
-- Nghiêm trọng vì dividend_years_consecutive vừa chiếm 30% thành phần điểm cổ
-- tức (scoring_weights.csv, cả ba com_class), vừa là BỘ LỌC CỨNG
-- `dividend_years_min` trong config/scoring_profiles.yml (profile mặc định đòi
-- >= 3 năm) — sai ở cả hai đường.
--
-- Nguyên tắc: một năm mà ta KHÔNG BIẾT có trả cổ tức hay không phải CẮT chuỗi.
-- Không biết ≠ có trả. Giữ dòng lại (kể cả dividend_yield NULL) và để
-- `last_break_year` bên dưới coi NULL là một lần cắt.
with yearly as (
    select symbol, year, dividend_yield
    from {{ ref('stg_financial_ratio') }}
    where quarter = 5
),

latest_year as (
    select symbol, max(year) as max_year from yearly group by 1
),

-- Đánh dấu năm CHẶN chuỗi: vừa năm biết chắc KHÔNG trả cổ tức
-- (dividend_yield <= 0) vừa năm KHÔNG BIẾT (dividend_yield is null, tức dòng
-- trắng của Task 8.5). Tên cũ `last_zero_year` chỉ mô tả vế đầu nên đổi thành
-- `last_break_year` cho khớp ngữ nghĩa mới.
gapped as (
    select
        y.symbol,
        y.year,
        y.dividend_yield,
        l.max_year,
        max(case when y.dividend_yield is null or y.dividend_yield <= 0
                 then y.year end)
            over (partition by y.symbol) as last_break_year
    from yearly y
    join latest_year l using (symbol)
)

select
    symbol,
    -- avg() bỏ qua NULL: năm không biết KHÔNG bị tính là 0 trong trung bình
    -- (NULL ≠ 0 — 0 nghĩa "năm đó không trả", NULL nghĩa "không đo được").
    -- Cửa sổ vẫn neo vào max_year của MỌI dòng năm có trên sổ, kể cả dòng
    -- trắng: đó mới là "5 năm gần nhất" thật, chứ không phải "5 năm gần nhất
    -- CÓ SỐ LIỆU" (định nghĩa cũ lùi cửa sổ về quá khứ mỗi khi kỳ mới nhất
    -- thiếu dữ liệu, làm tỷ suất trông tươi hơn thực tế).
    avg(case when year >= max_year - 4 then dividend_yield end) as dividend_yield_avg_5y,
    -- Số năm liên tiếp có cổ tức, tính lùi từ năm gần nhất. `dividend_yield > 0`
    -- là logic ba trị: NULL > 0 ra NULL nên năm không biết không bao giờ được
    -- ĐẾM — và nhờ last_break_year ở trên nó còn CẮT mọi năm cũ hơn.
    count(*) filter (
        where dividend_yield > 0
          and (last_break_year is null or year > last_break_year)
    ) as dividend_years_consecutive,
    case
        when avg(dividend_yield) is null or avg(dividend_yield) <= 0 then 0.0
        else greatest(0.0, least(1.0,
             1 - stddev_samp(dividend_yield) / nullif(avg(dividend_yield), 0)))
    end as dividend_stability
from gapped
group by symbol
