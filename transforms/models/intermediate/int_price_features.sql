{{ config(materialized='table', tags=['daily']) }}

-- Mảng Q: mọi chỉ báo (MA, return, volatility, đỉnh/đáy 52 tuần) tính trên
-- adj_close — giá đã điều chỉnh theo int_price_adjustment. Trước mảng Q chúng
-- tính trên close thô, nên một đợt thưởng 300% (TRC 15/09/2026) hiện thành
-- phiên giảm 75%. `close` (thô) vẫn được trả ra để hiển thị giá thật.
--
-- Hệ số của dòng t = tích factor các sự kiện có ex_date > t VÀ ex_date > ngày
-- loaded_at của t. Vế sau: dòng lấy từ Quote.history SAU sự kiện đã được nguồn
-- điều chỉnh sẵn — nhân thêm lần nữa là điều chỉnh hai lần.
with base as (
    select symbol, trade_date, close, volume, turnover_vnd, loaded_at
    from {{ ref('stg_price_daily') }}
    where not is_suspect_price
),

adj as (
    select
        b.symbol,
        b.trade_date,
        exp(coalesce(sum(ln(e.factor)), 0)) as adj_factor
    from base b
    left join {{ ref('int_price_adjustment') }} e
           on e.symbol = b.symbol
          and e.ex_date > b.trade_date
          and e.ex_date > cast(b.loaded_at as date)
    group by 1, 2
),

p as (
    select
        b.symbol, b.trade_date, b.close, b.volume, b.turnover_vnd,
        a.adj_factor,
        b.close * a.adj_factor as adj_close,
        -- Khoảng cách NGÀY DƯƠNG LỊCH tới phiên liền trước cùng mã (không phải
        -- số phiên). Toàn bộ model này tính MA/return/volatility theo SỐ PHIÊN
        -- (rows preceding) chứ không theo ngày lịch, nên lag(close) không phân
        -- biệt được "phiên liền trước cách 1 ngày" với "phiên liền trước cách
        -- 2.460 ngày do mã tạm ngừng giao dịch" (case thật: PTM nghỉ giao dịch
        -- 2018-11-27 → 2025-08-22). Khi giao dịch lại, close/lag(close)-1 sẽ
        -- nhảy hàng nghìn % vì bị hiểu nhầm là biến động của MỘT phiên —
        -- gap_days dùng để rào chắn việc này ở daily_return và các return_*
        -- bên dưới (fix round 1). Ngưỡng 15 ngày: cuối tuần cách nhau 2-3
        -- ngày, Tết dài nhất ~9 ngày, nên 15 phân biệt được nghỉ lễ bình
        -- thường với tạm ngừng giao dịch thật mà không cần bảng lịch lễ.
        date_diff(
            'day',
            lag(trade_date) over (partition by symbol order by trade_date),
            trade_date
        ) as gap_days
    from base b
    join adj a using (symbol, trade_date)
),

pg as (
    select
        *,
        -- TRUE nếu phiên này cách phiên liền trước (cùng mã) hơn 15 ngày.
        -- Tầng sau (chấm điểm, agent hỏi đáp) cần cờ này để biết dòng nào nằm
        -- ngay sau một lần tạm ngừng giao dịch — return/volatility quanh đó
        -- có thể đã bị NULL hoá bởi rào chắn gap_days.
        coalesce(gap_days > 15, false) as has_gap,
        -- daily_return dùng để tính volatility_60d — cần CẢ HAI rào chắn:
        --  1) gap_days <= 15 (fix round 1): không phải phiên ngay sau một lần
        --     tạm ngừng giao dịch dài ngày (case PTM, xem comment gap_days).
        --  2) volume > 0 ở CẢ phiên hiện tại VÀ phiên liền trước (fix round 2):
        --     một phiên volume=0 nghĩa là không có giao dịch thật khớp lệnh,
        --     "close" của nó chỉ là giá tham chiếu còn sót lại — GHÉP HAI GIÁ
        --     THAM CHIẾU tạo suất sinh lời bịa đặt dù gap_days chỉ 1-5 ngày,
        --     nên rào chắn #1 không bắt được lớp lỗi này. Case thật: NSS
        --     đứng giá 3.700 volume=0 hiện tại; giai đoạn 2021 close nhảy qua
        --     lại 7.450↔2.420 mọi phiên đều volume=0 → volatility_60d giả đo
        --     được 1,9471 (194,71%/phiên). ĐỪNG bỏ điều kiện volume này.
        case
            when (gap_days is null or gap_days <= 15)
                 and volume > 0
                 and coalesce(lag(volume) over (partition by symbol order by trade_date), 0) > 0
            then adj_close / nullif(lag(adj_close) over (partition by symbol order by trade_date), 0) - 1
            else null
        end as daily_return
    from p
),

windowed as (
    select
        symbol,
        trade_date,
        close,
        adj_close,
        adj_factor,
        volume,
        has_gap,
        -- MA20/50/200: trung bình động theo SỐ PHIÊN giao dịch (không phải
        -- ngày lịch) — "n preceding" đếm hàng, nên tự động bỏ qua T7/CN/lễ.
        avg(adj_close)  over w20  as ma20,
        avg(adj_close)  over w50  as ma50,
        avg(adj_close)  over w200 as ma200,
        -- turnover_vnd đã được stg_price_daily quy đổi sẵn (coalesce(value_vnd,
        -- close*volume) theo VNĐ) — dùng thẳng, không tính lại close*volume ở đây.
        avg(turnover_vnd) over w20 as avg_turnover_20d,
        avg(turnover_vnd) over w60 as avg_turnover_60d,
        -- Số quan sát daily_return KHÔNG NULL trong cửa sổ 60 phiên (fix round
        -- 2). Dưới ngưỡng price_features_min_valid_sessions, quá ít điểm khiến
        -- stddev_samp nhiễu (mẫu nhỏ) — dùng để NULL hoá volatility_60d và gắn
        -- cờ is_thin_trading ở SELECT cuối, thay vì trả một con số không đáng
        -- tin.
        count(daily_return) over w60 as n_valid_60,
        -- Độ lệch chuẩn mẫu THÔ của suất sinh lời ngày trong cửa sổ 60 phiên —
        -- CHƯA gate theo n_valid_60, việc đó làm ở SELECT cuối (volatility_60d).
        stddev_samp(daily_return) over w60 as volatility_60d_raw,
        -- Biên 52 tuần xấp xỉ bằng 250 phiên giao dịch (52 tuần x ~5 phiên/tuần).
        max(adj_close) over w250   as high_52w,
        min(adj_close) over w250   as low_52w,
        -- Suất sinh lời 1/3/6/12 tháng dùng số phiên xấp xỉ: 21 phiên/tháng
        -- (~252 phiên giao dịch/năm chia 12), nên 1m=21, 3m=63, 6m=126, 12m=250.
        -- CẢNH BÁO: lag(close, N) đếm theo SỐ PHIÊN — nếu trong N phiên gần
        -- nhất có một khoảng trống > 15 ngày (tạm ngừng giao dịch), giá trị lag
        -- này vẫn trả về một con số nhưng suất sinh lời suy ra từ nó vô nghĩa.
        -- Rào chắn thật sự nằm ở max_gap_* bên dưới, áp dụng khi tính return_*
        -- ở SELECT cuối cùng — ĐỪNG bỏ rào chắn đó dù lag() ở đây trông "sạch".
        -- LƯU Ý (fix round 2): return_* KHÔNG áp điều kiện volume>0 như
        -- daily_return — quyết định có chủ đích, vì return_Nm so giá hôm nay
        -- với giá N phiên trước, nếu một trong hai phiên đó volume=0 thì giá
        -- tham chiếu của nó vẫn phản ánh mức giá thị trường công nhận (không
        -- bị cộng dồn nhiễu như daily_return, vốn lặp lại 60 lần trong stddev).
        lag(adj_close, 21)  over (partition by symbol order by trade_date) as close_1m_ago,
        lag(adj_close, 63)  over (partition by symbol order by trade_date) as close_3m_ago,
        lag(adj_close, 126) over (partition by symbol order by trade_date) as close_6m_ago,
        lag(adj_close, 250) over (partition by symbol order by trade_date) as close_12m_ago,
        -- max(gap_days) trong đúng cửa sổ N phiên tương ứng với mỗi return_Nm:
        -- nếu > 15 nghĩa là cửa sổ đó chứa một lần tạm ngừng giao dịch dài
        -- ngày, nên return_Nm ở SELECT cuối phải NULL thay vì trả về một suất
        -- sinh lời bịa đặt.
        max(gap_days) over wgap21  as max_gap_1m,
        max(gap_days) over wgap63  as max_gap_3m,
        max(gap_days) over wgap126 as max_gap_6m,
        max(gap_days) over w250    as max_gap_12m,
        count(*) over (partition by symbol order by trade_date
                       rows between 249 preceding and current row) as sessions_1y
    from pg
    window
        w20  as (partition by symbol order by trade_date rows between 19  preceding and current row),
        w50  as (partition by symbol order by trade_date rows between 49  preceding and current row),
        w60  as (partition by symbol order by trade_date rows between 59  preceding and current row),
        w200 as (partition by symbol order by trade_date rows between 199 preceding and current row),
        w250 as (partition by symbol order by trade_date rows between 249 preceding and current row),
        -- Cửa sổ dùng riêng để kiểm tra gap_days lớn nhất trong đúng N phiên
        -- mà return_Nm nhìn lại — LƯU Ý số "preceding" ở đây là N-1, khác với
        -- w20/w50/w200 (dùng cho MA, "preceding" = N-1 vì đó vốn đã đúng theo
        -- brief). Ví dụ return_1m nhìn lại 21 phiên (current + 20 preceding)
        -- để bao trọn 21 khoảng cách (transition) giữa các phiên liên tiếp.
        wgap21  as (partition by symbol order by trade_date rows between 20  preceding and current row),
        wgap63  as (partition by symbol order by trade_date rows between 62  preceding and current row),
        wgap126 as (partition by symbol order by trade_date rows between 125 preceding and current row)
),

ytd as (
    select
        symbol,
        year(trade_date) as yr,
        min_by(adj_close, trade_date) as close_year_open
    from p
    group by 1, 2
)

select
    w.symbol,
    w.trade_date,
    w.close,
    w.adj_close,
    w.adj_factor,
    w.volume,
    w.has_gap,
    -- TRUE khi cửa sổ 60 phiên có ít hơn price_features_min_valid_sessions
    -- (30) quan sát daily_return hợp lệ — tầng sau cần biết VÌ SAO
    -- volatility_60d là NULL (thanh khoản quá mỏng), chứ không chỉ biết rằng
    -- nó NULL. Cùng lý do tồn tại như has_gap.
    w.n_valid_60 < {{ var('price_features_min_valid_sessions') }} as is_thin_trading,
    w.ma20,
    w.ma50,
    w.ma200,
    w.avg_turnover_20d,
    w.avg_turnover_60d,
    -- volatility_60d chỉ tin được khi có đủ price_features_min_valid_sessions
    -- (30) quan sát daily_return hợp lệ trong cửa sổ 60 phiên — dưới ngưỡng
    -- này NULL hoá thay vì trả một độ lệch chuẩn tính trên vài điểm (mẫu nhỏ
    -- khiến stddev_samp tự nó nhiễu, xem case NSS/fix round 2 report).
    case when w.n_valid_60 >= {{ var('price_features_min_valid_sessions') }}
         then w.volatility_60d_raw
         else null end as volatility_60d,
    w.high_52w,
    w.low_52w,
    w.sessions_1y,
    case when w.max_gap_1m  > 15 then null
         else w.adj_close / nullif(w.close_1m_ago,  0) - 1 end as return_1m,
    case when w.max_gap_3m  > 15 then null
         else w.adj_close / nullif(w.close_3m_ago,  0) - 1 end as return_3m,
    case when w.max_gap_6m  > 15 then null
         else w.adj_close / nullif(w.close_6m_ago,  0) - 1 end as return_6m,
    case when w.max_gap_12m > 15 then null
         else w.adj_close / nullif(w.close_12m_ago, 0) - 1 end as return_12m,
    w.adj_close / nullif(y.close_year_open, 0) - 1 as return_ytd,
    w.adj_close / nullif(w.high_52w, 0) - 1    as pct_from_high_52w
from windowed w
left join ytd y
       on y.symbol = w.symbol and y.yr = year(w.trade_date)
