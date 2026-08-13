-- Percentile định giá chỉ có ý nghĩa khi CHÍNH kỳ đó có tỷ số hợp lệ. Gate cũ
-- chỉ xét SỐ QUÝ hợp lệ trong cửa sổ 20 quý, không xét chính dòng hiện tại có
-- pe_meaningful/pb_meaningful hay không — hậu quả: kỳ lỗ nặng (P/E âm hàng
-- nghìn) vẫn được gán một con số percentile trông "hợp lệ" trong [0,1].
-- Mọi dòng có pe_pct_own_5y/pb_pct_own_5y khác NULL phải join được với
-- stg_financial_ratio và có pe_meaningful/pb_meaningful = true ở đúng kỳ đó.
select v.symbol, v.period_end_date, v.pe, v.pe_pct_own_5y, 'pe' as metric
from {{ ref('int_valuation_percentile') }} v
join {{ ref('stg_financial_ratio') }} f
  on f.symbol = v.symbol
 and f.period_end_date = v.period_end_date
 and f.quarter between 1 and 4
where v.pe_pct_own_5y is not null and not f.pe_meaningful

union all

select v.symbol, v.period_end_date, v.pb, v.pb_pct_own_5y, 'pb' as metric
from {{ ref('int_valuation_percentile') }} v
join {{ ref('stg_financial_ratio') }} f
  on f.symbol = v.symbol
 and f.period_end_date = v.period_end_date
 and f.quarter between 1 and 4
where v.pb_pct_own_5y is not null and not f.pb_meaningful
