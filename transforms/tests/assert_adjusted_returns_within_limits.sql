{{ config(severity='warn') }}
-- Mảng Q: sau điều chỉnh giá, biến động một phiên trên adj_close phải nằm trong
-- biên độ sàn (HOSE ±7%, HNX ±10%, UPCoM ±15%; phiên đầu sau niêm yết/giao dịch
-- lại có thể ±20–40%). Ngưỡng 16% chỉ bắt BƯỚC NHẢY GIẢ do chưa điều chỉnh —
-- trước mảng Q, 29 mã vi phạm trong hai tuần 11–24/09/2026. Mức warn: một vài
-- ca phiên đầu sau tạm ngừng là thật; số dòng tăng đột biến mới là tín hiệu.
with r as (
    select symbol, trade_date, adj_close,
           lag(adj_close) over (partition by symbol order by trade_date) as prev_adj,
           lag(volume)    over (partition by symbol order by trade_date) as prev_volume,
           volume,
           date_diff('day', lag(trade_date) over (partition by symbol order by trade_date),
                     trade_date) as gap_days
    from {{ ref('fct_price_daily') }}
    where trade_date >= current_date - interval '120 days'
)
select symbol, trade_date, prev_adj, adj_close, adj_close / prev_adj - 1 as ret
from r
where prev_adj > 0
  and volume > 0 and prev_volume > 0
  and gap_days <= 15
  and abs(adj_close / prev_adj - 1) > 0.16
