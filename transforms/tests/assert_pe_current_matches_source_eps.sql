-- P/E hiện tại phải bằng GIÁ PHIÊN MỚI NHẤT chia cho EPS mà nguồn đã dùng.
--
-- Vì sao có test này (2026-10-05): nguồn tính pe/pb/market_cap của quý mới
-- nhất theo giá TẠI LÚC NẠP (market_cap / number_of_shares_mkt_cap = đúng giá
-- đóng cửa phiên cuối trước loaded_at ở ~88% mã), không phải giá ngày chốt quý.
-- int_valuation_current từng nhân thêm adj_close(now)/adj_close(ngày chốt) →
-- quy đổi giá HAI lần: LPB báo P/E 7,99 trong khi đúng là 10,63.
--
-- EPS nguồn ngầm định = giá ngầm định / pe = (market_cap / số CP) / pe, nên
-- P/E đúng = pe × last_close / giá ngầm định. Chỉ xét mã có thanh khoản
-- (≥ 1 tỷ/phiên) và nguồn thật sự dùng giá phiên gần ngày nạp (lệch < 2%) —
-- mã gần như không giao dịch có giá ngầm định lệch giá đóng cửa vì lý do khác.
--
-- Bỏ mã có GDKHQ SAU ngày nạp (2026-10-18): khi đó model quy đổi theo
-- adj_close (đúng ý đồ — thưởng/chia/quyền mua làm loãng EPS nguồn), còn
-- pe_expected ở đây dùng giá THÔ nên lệch đúng bằng hệ số điều chỉnh. MZG GDKHQ
-- quyền mua 14/10/2026 (tham chiếu 11.550 vs đóng cửa 11.900, lệch 2,94%) làm
-- test fail 3 ngày dù pe_current đúng. Lần nạp tỷ số kế tiếp sau GDKHQ đưa mã
-- trở lại tập kiểm.
with lp as (
    select symbol, max(year * 10 + quarter) as yq
    from {{ source('warehouse', 'raw_financial_ratio') }}
    where period_type = 'quarter' and quarter between 1 and 4
    group by 1
),

src as (
    select r.symbol, r.pe,
           r.market_cap / nullif(r.number_of_shares_mkt_cap, 0) as implied_price,
           cast(r.loaded_at as date) as load_date
    from {{ source('warehouse', 'raw_financial_ratio') }} r
    join lp on lp.symbol = r.symbol and r.year * 10 + r.quarter = lp.yq
    where r.period_type = 'quarter' and r.pe > 0
),

px_load as (
    select s.symbol, arg_max(p.close, p.trade_date) as close_at_load
    from src s
    join {{ ref('fct_price_daily') }} p
      on p.symbol = s.symbol and p.trade_date <= s.load_date
    group by 1
),

adjusted_after_load as (
    select distinct s.symbol
    from src s
    join {{ ref('int_price_adjustment') }} e
      on e.symbol = s.symbol and e.ex_date > s.load_date
),

checked as (
    select sc.symbol, sc.pe_current, sc.last_close, s.pe, s.implied_price,
           s.pe * sc.last_close / s.implied_price as pe_expected
    from {{ ref('mart_stock_scorecard') }} sc
    join src s using (symbol)
    join px_load pl using (symbol)
    where sc.pe_current is not null
      and sc.avg_turnover_20d >= 1e9
      and abs(s.implied_price / pl.close_at_load - 1) < 0.02
      and sc.symbol not in (select symbol from adjusted_after_load)
)

select *
from checked
where abs(pe_current / pe_expected - 1) > 0.02
