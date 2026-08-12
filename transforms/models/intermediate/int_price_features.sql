{{ config(materialized='table', tags=['daily']) }}

with p as (
    select
        symbol, trade_date, close, volume, turnover_vnd,
        -- Suất sinh lời ngày, tính sẵn ở đây thay vì lồng trực tiếp lag() over(...)
        -- vào bên trong stddev_samp(...) over w60 bên dưới. Lý do: chuẩn SQL (và
        -- DuckDB cụ thể) không cho phép lồng window function bên trong tham số
        -- của một window function khác ("window function calls cannot be
        -- nested") — công thức gốc trong brief bị lỗi cú pháp này. Tách bước ở
        -- đây giữ nguyên công thức toán học (close hôm nay / close hôm trước - 1)
        -- chỉ khác cách viết SQL để tránh lồng window function.
        close / nullif(lag(close) over (partition by symbol order by trade_date), 0) - 1
            as daily_return
    from {{ ref('stg_price_daily') }}
    where not is_suspect_price
),

windowed as (
    select
        symbol,
        trade_date,
        close,
        volume,
        -- MA20/50/200: trung bình động theo SỐ PHIÊN giao dịch (không phải
        -- ngày lịch) — "n preceding" đếm hàng, nên tự động bỏ qua T7/CN/lễ.
        avg(close)  over w20  as ma20,
        avg(close)  over w50  as ma50,
        avg(close)  over w200 as ma200,
        -- turnover_vnd đã được stg_price_daily quy đổi sẵn (coalesce(value_vnd,
        -- close*volume) theo VNĐ) — dùng thẳng, không tính lại close*volume ở đây.
        avg(turnover_vnd) over w20 as avg_turnover_20d,
        avg(turnover_vnd) over w60 as avg_turnover_60d,
        -- Biến động 60 phiên: độ lệch chuẩn mẫu của suất sinh lời ngày (daily_return,
        -- tính sẵn ở CTE p) trong cửa sổ 60 phiên gần nhất.
        stddev_samp(daily_return) over w60 as volatility_60d,
        -- Biên 52 tuần xấp xỉ bằng 250 phiên giao dịch (52 tuần x ~5 phiên/tuần).
        max(close) over w250       as high_52w,
        min(close) over w250       as low_52w,
        -- Suất sinh lời 1/3/6/12 tháng dùng số phiên xấp xỉ: 21 phiên/tháng
        -- (~252 phiên giao dịch/năm chia 12), nên 1m=21, 3m=63, 6m=126, 12m=250.
        lag(close, 21)  over (partition by symbol order by trade_date) as close_1m_ago,
        lag(close, 63)  over (partition by symbol order by trade_date) as close_3m_ago,
        lag(close, 126) over (partition by symbol order by trade_date) as close_6m_ago,
        lag(close, 250) over (partition by symbol order by trade_date) as close_12m_ago,
        count(*) over (partition by symbol order by trade_date
                       rows between 249 preceding and current row) as sessions_1y
    from p
    window
        w20  as (partition by symbol order by trade_date rows between 19  preceding and current row),
        w50  as (partition by symbol order by trade_date rows between 49  preceding and current row),
        w60  as (partition by symbol order by trade_date rows between 59  preceding and current row),
        w200 as (partition by symbol order by trade_date rows between 199 preceding and current row),
        w250 as (partition by symbol order by trade_date rows between 249 preceding and current row)
),

ytd as (
    select
        symbol,
        year(trade_date) as yr,
        min_by(close, trade_date) as close_year_open
    from p
    group by 1, 2
)

select
    w.symbol,
    w.trade_date,
    w.close,
    w.volume,
    w.ma20,
    w.ma50,
    w.ma200,
    w.avg_turnover_20d,
    w.avg_turnover_60d,
    w.volatility_60d,
    w.high_52w,
    w.low_52w,
    w.sessions_1y,
    w.close / nullif(w.close_1m_ago,  0) - 1 as return_1m,
    w.close / nullif(w.close_3m_ago,  0) - 1 as return_3m,
    w.close / nullif(w.close_6m_ago,  0) - 1 as return_6m,
    w.close / nullif(w.close_12m_ago, 0) - 1 as return_12m,
    w.close / nullif(y.close_year_open, 0) - 1 as return_ytd,
    w.close / nullif(w.high_52w, 0) - 1        as pct_from_high_52w
from windowed w
left join ytd y
       on y.symbol = w.symbol and y.yr = year(w.trade_date)
