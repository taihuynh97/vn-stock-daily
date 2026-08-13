{{ config(materialized='table') }}

with hist as (
    select
        symbol,
        period_end_date,
        year * 4 + quarter as abs_quarter,
        pe,
        pb,
        ps,
        case when pe_meaningful then pe end as pe_valid,
        case when pb_meaningful then pb end as pb_valid
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

-- Fix round 1: percent_rank() KHÔNG nhận khung cửa sổ (ROWS/RANGE) — đây là
-- rank function theo chuẩn SQL, luôn xếp hạng trên TOÀN BỘ partition bất kể
-- có khai báo frame hay không. Bản gốc (chép nguyên brief) gọi
-- `percent_rank() over (partition by symbol order by pe_valid)` mà không có
-- frame nào, nên nó xếp hạng trên TOÀN BỘ lịch sử của mã chứ không phải 20
-- quý như tên biến `pe_pct_own_5y` ngụ ý. Đo trên production: ANV kỳ
-- 2026-06-30 model cũ cho 0,1875, đúng 20 quý phải là 0,0588 (1 dòng nhỏ hơn
-- / 17 = 18 quý hợp lệ - 1); sai lệch trung bình đo trên 16.154 dòng là 0,124,
-- 47,8% dòng lệch > 0,10.
--
-- Sửa bằng self-join giới hạn đúng 20 quý LỊCH (abs_quarter, không phải số
-- dòng), rồi tự tính percent_rank bằng công thức chuẩn:
--   percent_rank = (số phần tử NHỎ HƠN giá trị hiện tại) / (số phần tử hợp lệ - 1)
-- Công thức này tương đương RANK()-1 chia cho (n-1) — đúng ngữ nghĩa
-- percent_rank kể cả khi có giá trị trùng nhau (tie).
ranked as (
    select
        h.symbol,
        h.period_end_date,
        h.abs_quarter,
        h.pe,
        h.pb,
        h.ps,
        h.pe_valid,
        h.pb_valid,
        count(w.pe_valid) as pe_quarters_20,
        count(w.pb_valid) as pb_quarters_20,
        count(*) filter (where w.pe_valid < h.pe_valid)::double
            / nullif(count(w.pe_valid) - 1, 0) as pe_pct_win,
        count(*) filter (where w.pb_valid < h.pb_valid)::double
            / nullif(count(w.pb_valid) - 1, 0) as pb_pct_win
    from hist h
    left join hist w
           on w.symbol = h.symbol
          and w.abs_quarter between h.abs_quarter - 19 and h.abs_quarter
    group by 1, 2, 3, 4, 5, 6, 7, 8
)

select
    symbol,
    period_end_date,
    pe,
    pb,
    ps,
    -- Gán percentile CHỈ KHI: (a) chính kỳ này có P/E có nghĩa — bản gốc
    -- thiếu điều kiện này nên gán phân vị cho 1.113 dòng P/E vô nghĩa (ví dụ
    -- PMG 2024-03-31: pe = -9.126,13 vẫn nhận percentile = 0,839), và
    -- (b) đủ số quý hợp lệ (>= own_history_min_quarters) trong cửa sổ 20 quý.
    case when pe_valid is not null
              and pe_quarters_20 >= {{ var('own_history_min_quarters') }}
         then pe_pct_win end as pe_pct_own_5y,
    case when pb_valid is not null
              and pb_quarters_20 >= {{ var('own_history_min_quarters') }}
         then pb_pct_win end as pb_pct_own_5y,
    pe_quarters_20 as own_quarters_used
from ranked
