{{ config(severity='warn') }}
-- Mảng Q: sau điều chỉnh giá, biến động một phiên trên adj_close phải nằm trong
-- biên độ sàn. Ngưỡng theo sàn:
--   HOSE ±7%, HNX ±10% (phiên đầu niêm yết/giao dịch lại ±20%/±30%) → 16% chỉ
--   bắt BƯỚC NHẢY GIẢ do chưa điều chỉnh. Trước mảng Q: TRC −75%, PHR −47%.
--   UPCoM ±15% tính từ giá BÌNH QUÂN phiên trước (không phải giá đóng cửa),
--   phiên đầu ±40% → đóng cửa-đóng cửa >16% có thể là thật (đo trên bản sao đã
--   sửa: 85 dòng 16–48%, toàn UPCoM). Chỉ báo khi > 45%.
-- Mức warn: phiên đầu sau tạm ngừng là thật; số dòng tăng đột biến mới là tín hiệu.
with r as (
    select f.symbol, f.trade_date, f.adj_close,
           lag(f.adj_close) over w as prev_adj,
           lag(f.volume)    over w as prev_volume,
           f.volume,
           date_diff('day', lag(f.trade_date) over w, f.trade_date) as gap_days
    from {{ ref('fct_price_daily') }} f
    where f.trade_date >= current_date - interval '120 days'
    window w as (partition by f.symbol order by f.trade_date)
)
select r.symbol, d.exchange, r.trade_date, r.prev_adj, r.adj_close,
       r.adj_close / r.prev_adj - 1 as ret
from r
left join {{ ref('dim_stock') }} d using (symbol)
where r.prev_adj > 0
  and r.volume > 0 and r.prev_volume > 0
  and r.gap_days <= 15
  and abs(r.adj_close / r.prev_adj - 1)
      > case when d.exchange = 'UPCOM' then 0.45 else 0.16 end
