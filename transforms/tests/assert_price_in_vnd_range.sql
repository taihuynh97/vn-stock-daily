-- Bắt LỆCH ĐƠN VỊ, không bắt "cổ phiếu giá thấp".
--
-- Bản đầu dùng sàn tuyệt đối 100 VNĐ, nhưng chạy thật trên production cho
-- thấy nó đo sai thứ: 1.682 dòng (0,13%) bị bắt đều là cổ phiếu penny THẬT —
-- DKC/VLP/VNX là vỏ công ty gần chết, khối lượng 1-5 cổ phiếu/phiên, giá
-- 30-900 VNĐ suốt 828 phiên. Đó là dữ liệu đúng.
--
-- Dấu hiệu thật của lệch đơn vị là ĐỨT GÃY: cùng một mã có cả dòng dưới
-- 100 VNĐ lẫn dòng trên 1.000 VNĐ. Ví dụ HPG nếu quên nhân 1000 ở phần
-- backfill sẽ có dòng 21,85 nằm cạnh dòng 21.850 — lỗi này đã xảy ra thật,
-- xem scripts/fix_backfill_units.py. Mã penny thật thì mọi phiên đều thấp.
--
-- Chặn trên vẫn giữ tuyệt đối: không cổ phiếu VN nào vượt 5 triệu VNĐ.
with per_symbol as (
    select
        symbol,
        count(*) filter (where close < 100)      as n_duoi_100,
        count(*) filter (where close > 1000)     as n_tren_1000,
        count(*) filter (where close > 5000000)  as n_qua_lon
    from {{ ref('stg_price_daily') }}
    group by symbol
)
select symbol, n_duoi_100, n_tren_1000, n_qua_lon
from per_symbol
where (n_duoi_100 > 0 and n_tren_1000 > 0)
   or n_qua_lon > 0
