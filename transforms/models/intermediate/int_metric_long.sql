{{ config(materialized='table') }}

{% set metric_list = all_metrics() %}

{#
  RÀO CHẮN "SỐ ÂM KHÔNG PHẢI LÀ RẺ" — fix vòng review toàn nhánh (Critical #1).

  Model này viết ở Task 5, TRƯỚC khi bài học pe_meaningful được rút ra ở Task 6,
  nên nó unpivot thẳng 44 cột thô. Ba consumer khác của stg_financial_ratio đã
  áp cờ đó (int_valuation_percentile, mart_sector_snapshot, test
  assert_percentile_only_on_meaningful_periods) — chỉ đường int_metric_long →
  int_metric_percentile → mart_stock_scorecard là không.

  Hậu quả đo trên production: scoring_weights.csv gán direction = 'lower' cho
  pe / pb / ev_to_ebitda / debt_to_equity, nên số ÂM là số NHỎ NHẤT trong rổ →
  percent_rank ≈ 0 → mart_stock_scorecard đảo chiều thành adj = 1 - pct ≈ 1,0,
  tức điểm gần tuyệt đối. KSH có pe = -419 và nhận value_score 99,3. DAC có
  debt_to_equity = -7,91 (⟺ VỐN CHỦ ÂM, đã mất sạch vốn) và nhận quality_score
  81,6 — sát ngân hàng chất lượng nhất thị trường MBB (83,2). 247 dòng pe âm +
  255 ev_to_ebitda âm + 90 debt_to_equity âm còn ô nhiễm cả rổ: 1.193/1.266 mã
  LÀNH MẠNH bị đẩy lên bậc phân vị cao hơn, tức trông ĐẮT hơn thực tế.

  Nguyên tắc: với một tỷ số mà MẪU SỐ có thể âm (lợi nhuận, giá trị sổ sách,
  doanh thu, EBITDA, dòng tiền, vốn chủ), giá trị âm KHÔNG nghĩa là "rẻ" — nó
  nghĩa là "không áp dụng được". Phải NULL để không lọt vào rổ tính phân vị.
  NULL ≠ 0: NULL bị loại khỏi cả tử số lẫn mẫu số ở cổng weight_coverage của
  mart_stock_scorecard, còn 0 nghĩa là "kém nhất nhóm".

  Chiều NGƯỢC LẠI cũng là lỗi và TUYỆT ĐỐI không được mắc: roe, roa, roic, các
  biên lợi nhuận, revenue_yoy, earnings_yoy, gross_margin_slope_8q, ebit,
  ebitda, loans_growth, deposit_growth, equity_to_liabilities... có
  direction = 'higher' nên số âm nằm ĐÚNG chỗ ở đáy thang — NULL hoá chúng là
  XOÁ DỮ LIỆU THẬT (doanh nghiệp lỗ / vốn chủ âm phải bị xếp bét, không phải
  "không đo được" rồi thoát khỏi mẫu số).

  Ranh giới `>= 0` vs `> 0` được chọn theo TỪNG cột, không đồng loạt:
    - debt_to_equity / debt_per_equity dùng `>= 0` vì 0 là giá trị THẬT
      (doanh nghiệp không vay nợ — đo được 11 dòng debt_to_equity = 0 và 364
      dòng debt_per_equity = 0 ở NONFIN). `> 0` sẽ xoá đúng nhóm ít nợ nhất.
    - pe/pb/ps/ev_to_ebitda/price_to_cash_flow dùng `> 0` (qua cờ hoặc trực
      tiếp): 0 ở các cột này đã được stg_financial_ratio nullif từ Task 8.5 vì
      bất khả thi kinh tế, nên `> 0` không xoá dữ liệu thật nào.

  Tham chiếu cột đều QUALIFIED (`r.pe` chứ không phải `pe` trần) để loại hẳn
  lớp lỗi "alias trùng tên phân giải về cột thô" đã xảy ra ở
  stg_financial_ratio (xem comment CTE `nulled` ở đó): ở đây alias đích trùng
  tên cột nguồn (`... as pe`), đúng tình huống đã sinh lỗi.
#}
{% set metric_guard = {
    'pe':                 'case when r.pe_meaningful then r.pe end',
    'pb':                 'case when r.pb_meaningful then r.pb end',
    'ps':                 'case when r.ps > 0 then r.ps end',
    'ev_to_ebitda':       'case when r.ev_to_ebitda > 0 then r.ev_to_ebitda end',
    'price_to_cash_flow': 'case when r.price_to_cash_flow > 0 then r.price_to_cash_flow end',
    'debt_to_equity':     'case when r.debt_to_equity >= 0 then r.debt_to_equity end',
    'debt_per_equity':    'case when r.debt_per_equity >= 0 then r.debt_per_equity end'
} %}

-- Kỳ tỷ số mới nhất của mỗi mã (chỉ dòng TTM).
with latest_period as (
    select symbol, max(period_end_date) as period_end_date
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
    group by 1
),

ratio_latest as (
    select f.*
    from {{ ref('stg_financial_ratio') }} f
    join latest_period p using (symbol, period_end_date)
    where f.quarter between 1 and 4
),

-- (1) 44 chỉ tiêu gốc → dạng long. UNPIVOT của DuckDB tự bỏ giá trị NULL.
-- Dùng cú pháp UNPIVOT chuẩn SQL (đặt sau FROM) vì nó lồng được trong CTE.
-- Cột nào có trong `metric_guard` (xem comment đầu file) được thay bằng biểu
-- thức rào chắn TRƯỚC khi unpivot — NULL do rào chắn sinh ra bị chính UNPIVOT
-- loại, nên giá trị vô nghĩa không bao giờ tới được rổ percentile.
ratio_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from (
        select r.symbol, r.com_class, r.icb_code_lv2
               {%- for m in metric_list %}
               , {{ metric_guard.get(m, 'r.' ~ m) }} as {{ m }}
               {%- endfor %}
        from ratio_latest r
    )
    unpivot (value for metric in ({{ metric_list | join(', ') }}))
),

-- (2) Chỉ tiêu suy ra ở kỳ mới nhất.
fund_latest as (
    select f.symbol, f.com_class, c.icb_code_lv2,
           f.revenue_yoy, f.earnings_yoy, f.revenue_cagr_3y,
           f.earnings_cagr_3y, f.growth_consistency,
           cast(f.loss_quarters_12q as double) as loss_quarters_12q
    from {{ ref('int_fundamentals_ttm') }} f
    join latest_period p using (symbol, period_end_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

fund_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from fund_latest
    unpivot (value for metric in (
        revenue_yoy, earnings_yoy, revenue_cagr_3y, earnings_cagr_3y,
        growth_consistency, loss_quarters_12q))
),
-- Mảng Q: số quý lỗ THẬT (BCTC gốc) trong 12 quý, lấy ở quý BCTC mới nhất của
-- mã — thay loss_quarters_12q (đếm TTM âm) trong thành phần safety.
-- com_class/icb lấy từ stg_company_info như các khối khác.
profit_long as (
    select qp.symbol, c.com_class, c.icb_code_lv2,
           'loss_quarters_12q_actual' as metric,
           cast(qp.loss_quarters_12q_actual as double) as value
    from {{ ref('int_quarterly_profit') }} qp
    join (select symbol, max(period_end_date) as period_end_date
          from {{ ref('int_quarterly_profit') }} group by 1) m
      using (symbol, period_end_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

qual_latest as (
    select q.symbol, q.com_class, c.icb_code_lv2,
           q.roe_avg_8q, q.roe_stability, q.gross_margin_slope_8q
    from {{ ref('int_quality_metrics') }} q
    join latest_period p using (symbol, period_end_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

qual_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from qual_latest
    unpivot (value for metric in (
        roe_avg_8q, roe_stability, gross_margin_slope_8q))
),

div_latest as (
    select d.symbol, c.com_class, c.icb_code_lv2,
           d.dividend_yield_avg_5y,
           cast(d.dividend_years_consecutive as double) as dividend_years_consecutive,
           d.dividend_stability
    from {{ ref('int_dividend_history') }} d
    left join {{ ref('stg_company_info') }} c using (symbol)
),

div_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from div_latest
    unpivot (value for metric in (
        dividend_yield_avg_5y, dividend_years_consecutive, dividend_stability))
),

-- (3) Chỉ tiêu giá ở phiên mới nhất.
price_latest as (
    select p.symbol, c.com_class, c.icb_code_lv2,
           p.avg_turnover_20d, p.volatility_60d,
           cast(c.listing_age_years as double) as listing_age_years,
           c.free_float_percentage
    from {{ ref('int_price_features') }} p
    join (
        select symbol, max(trade_date) as trade_date
        from {{ ref('int_price_features') }} group by 1
    ) m using (symbol, trade_date)
    left join {{ ref('stg_company_info') }} c using (symbol)
),

price_long as (
    select symbol, com_class, icb_code_lv2, metric, value
    from price_latest
    unpivot (value for metric in (
        avg_turnover_20d, volatility_60d, listing_age_years,
        free_float_percentage))
)

select symbol, com_class, icb_code_lv2, lower(metric) as metric, value
from (
    select * from ratio_long
    union all select * from fund_long
    union all select * from profit_long
    union all select * from qual_long
    union all select * from div_long
    union all select * from price_long
)
where value is not null
  and isfinite(value)
