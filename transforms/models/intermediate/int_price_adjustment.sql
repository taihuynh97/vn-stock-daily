{{ config(materialized='table', tags=['daily']) }}

-- Sự kiện điều chỉnh giá (chia/thưởng cổ phiếu, cổ tức tiền...) phát hiện từ
-- GIÁ THAM CHIẾU của sàn, không từ bảng sự kiện doanh nghiệp.
--
-- Vì sao không dùng raw_corporate_event: đo 2026-10-03, đợt thưởng 300% của TRC
-- và 80% của PHR (GDKHQ tháng 9) có trong bảng sự kiện nhưng exright_date
-- NULL — điều chỉnh dựa vào sự kiện sẽ bỏ sót đúng những ca gây bước nhảy giả
-- lớn nhất. Giá tham chiếu ngày D do sở giao dịch tính sẵn: ngày thường
-- ref(D) = close(D-1); ngày GDKHQ ref(D) = close(D-1) đã điều chỉnh.
-- factor = ref(D) / close(D-1) chính là hệ số điều chỉnh của sàn.
--
-- Chỉ ghi nhận khi hai dòng là HAI PHIÊN LIÊN TIẾP theo lịch VNINDEX: nếu kho
-- thiếu một phiên của mã (job lỗi), close của dòng trước là của hai phiên
-- trước → ref(D)/close lệch → sự kiện giả. Ngày VNINDEX không có (lỗi nạp chỉ
-- số) → không xác minh được → bỏ qua (thà sót hơn bịa).
with sessions as (
    select trade_date, row_number() over (order by trade_date) as session_no
    from (select distinct trade_date from {{ ref('stg_index_daily') }}
          where index_code = 'VNINDEX')
),

p as (
    select
        symbol,
        trade_date,
        close,
        ref_price,
        lag(close)      over (partition by symbol order by trade_date) as prev_close,
        lag(trade_date) over (partition by symbol order by trade_date) as prev_date
    from {{ ref('stg_price_daily') }}
    where not is_suspect_price
)

select
    p.symbol,
    p.trade_date                as ex_date,
    p.prev_date,
    p.prev_close,
    p.ref_price,
    p.ref_price / p.prev_close  as factor
from p
join sessions s1 on s1.trade_date = p.trade_date
join sessions s0 on s0.trade_date = p.prev_date
where p.ref_price > 0
  and p.prev_close > 0
  and s1.session_no - s0.session_no = 1
  -- Ngưỡng 0,05%: ngày thường ref = close phiên trước CHÍNH XÁC (factor = 1);
  -- mọi lệch đáng kể đều là sự kiện thật. Ngưỡng chỉ để nuốt sai số dấu phẩy động.
  and abs(p.ref_price / p.prev_close - 1) > 0.0005
