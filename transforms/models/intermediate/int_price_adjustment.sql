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

-- Sàn hiện tại của mã — cùng quy tắc dim_stock (hồ sơ DN trước, danh sách mã
-- sau). Không ref dim_stock: dim_stock phụ thuộc int_price_features → vòng lặp.
exch as (
    select s.symbol, coalesce(c.exchange, s.exchange) as exchange
    from {{ source('warehouse', 'dim_symbols') }} s
    left join {{ ref('stg_company_info') }} c on c.symbol = s.symbol
),

p as (
    select
        symbol,
        trade_date,
        close,
        ref_price,
        lag(close)      over w as prev_close,
        lag(trade_date) over w as prev_date,
        lag(case when volume > 0 and value_vnd > 0 then value_vnd / volume end) over w
                               as prev_vwap
    from {{ ref('stg_price_daily') }}
    where not is_suspect_price
    window w as (partition by symbol order by trade_date)
),

-- Giá tham chiếu "bình thường" (không có sự kiện) theo quy chế từng sàn:
--   HOSE, HNX: = giá đóng cửa phiên trước.
--   UPCoM:     = giá BÌNH QUÂN GIA QUYỀN phiên trước, làm tròn bước giá 100 đ.
-- Phát hiện ở bước rà code mảng Q và đo xác nhận: 91,2% dòng UPCoM có giá tham
-- chiếu khớp bình quân phiên trước làm tròn 100 đ (HOSE/HNX chỉ 29–43%, trùng
-- hợp). So UPCoM với giá đóng cửa sẽ sinh "sự kiện" giả gần như mỗi ngày.
-- Phiên trước không khớp lệnh (không có bình quân) → giá đóng cửa của nó (mà
-- tầng ingest đặt bằng giá tham chiếu) — đúng quy chế "không giao dịch thì
-- giữ giá tham chiếu".
based as (
    select
        p.*,
        coalesce(e.exchange, 'UNKNOWN') as exchange,
        case
            when e.exchange = 'UPCOM' and p.prev_vwap > 0
                then round(p.prev_vwap / 100) * 100
            else p.prev_close
        end as ref_base
    from p
    left join exch e using (symbol)
)

select
    b.symbol,
    b.trade_date                 as ex_date,
    b.prev_date,
    b.prev_close,
    b.ref_base,
    b.ref_price,
    b.exchange,
    b.ref_price / b.ref_base     as factor
from based b
join sessions s1 on s1.trade_date = b.trade_date
join sessions s0 on s0.trade_date = b.prev_date
where b.ref_price > 0
  and b.ref_base > 0
  and s1.session_no - s0.session_no = 1
  and (
      -- HOSE/HNX: ngày thường ref = close phiên trước CHÍNH XÁC; ngưỡng 0,05%
      -- chỉ để nuốt sai số dấu phẩy động — mọi lệch đáng kể là sự kiện thật.
      (b.exchange <> 'UPCOM' and abs(b.ref_price / b.ref_base - 1) > 0.0005)
      -- UPCoM: bình quân gia quyền có nhiễu (lệnh thoả thuận, làm tròn) nên
      -- chỉ ghi nhận lệch lớn. Sự kiện nhỏ hơn ngưỡng (cổ tức tiền, cổ tức
      -- cổ phiếu nhỏ) KHÔNG được điều chỉnh — ghi trong docs/han-che-nen-tang.md.
      or (b.exchange = 'UPCOM'
          and abs(b.ref_price / b.ref_base - 1) > {{ var('upcom_adjustment_min_deviation') }})
  )
