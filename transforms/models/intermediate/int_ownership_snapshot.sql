{{ config(materialized='table') }}

-- Cô đặc cơ cấu sở hữu theo snapshot MỚI NHẤT mỗi mã.
--
-- total_disclosed_pct là cột BẮT BUỘC, không phải tuỳ chọn: tổng % công bố
-- không bằng 100% (HPG 51,9%, VNM 81,0%, VCB 91,0% — đo 2026-08-16), nên
-- nếu chỉ phơi top1/top5 mà giấu tổng thì người đọc rất dễ suy ra sai
-- "phần còn lại là free float". Đây đúng pattern "một con số cần được phơi
-- kèm bằng chứng đỡ nó" đã dùng bốn lần ở A2 (pe_quarters_used, n_pe,
-- *_weight_coverage, rejected_total).
with sh_latest as (
    select symbol, max(snapshot_date) as snapshot_date
    from {{ ref('stg_shareholder') }}
    group by 1
),

sh as (
    select s.*
    from {{ ref('stg_shareholder') }} s
    join sh_latest l
      on s.symbol = l.symbol and s.snapshot_date = l.snapshot_date
),

ranked as (
    select
        *,
        row_number() over (
            partition by symbol order by share_own_percent desc nulls last
        ) as rn
    from sh
),

sh_agg as (
    select
        symbol,
        max(snapshot_date) as snapshot_date,
        count(*) as n_disclosed,
        sum(share_own_percent) as total_disclosed_pct,
        max(case when rn = 1 then share_own_percent end) as top1_pct,
        sum(case when rn <= 5 then share_own_percent end) as top5_pct
    from ranked
    group by 1
),

of_latest as (
    select symbol, max(snapshot_date) as snapshot_date
    from {{ ref('stg_officer') }}
    group by 1
),

of_agg as (
    select
        o.symbol,
        sum(o.officer_own_percent) as insider_pct
    from {{ ref('stg_officer') }} o
    join of_latest l
      on o.symbol = l.symbol and o.snapshot_date = l.snapshot_date
    group by 1
)

select
    a.symbol,
    a.snapshot_date,
    a.n_disclosed,
    a.total_disclosed_pct,
    a.top1_pct,
    a.top5_pct,
    o.insider_pct
from sh_agg a
left join of_agg o on a.symbol = o.symbol
