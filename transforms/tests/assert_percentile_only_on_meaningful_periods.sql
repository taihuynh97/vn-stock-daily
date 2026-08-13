-- Percentile định giá chỉ có ý nghĩa khi CHÍNH kỳ đó có tỷ số hợp lệ. Gate cũ
-- chỉ xét SỐ QUÝ hợp lệ trong cửa sổ 20 quý, không xét chính dòng hiện tại có
-- pe_meaningful/pb_meaningful hay không — hậu quả: kỳ lỗ nặng (P/E âm hàng
-- nghìn) vẫn được gán một con số percentile trông "hợp lệ" trong [0,1].
-- Mọi dòng có pe_pct_own_5y/pb_pct_own_5y khác NULL phải join được với
-- stg_financial_ratio và có pe_meaningful/pb_meaningful = true ở đúng kỳ đó.
--
-- Dùng coalesce(..., false) = false thay vì `not f.pe_meaningful`: cột
-- pe_meaningful/pb_meaningful có thể là NULL (không chỉ true/false) khi
-- chính pe/pb gốc là NULL — `not NULL` = NULL nên lọt qua WHERE (bẫy logic
-- 3-trị đã khiến lần đếm thủ công trước đó bỏ sót 7/1.120 dòng vi phạm).
select v.symbol, v.period_end_date, v.pe, v.pe_pct_own_5y, 'pe_meaningful' as metric
from {{ ref('int_valuation_percentile') }} v
join {{ ref('stg_financial_ratio') }} f
  on f.symbol = v.symbol
 and f.period_end_date = v.period_end_date
 and f.quarter between 1 and 4
where v.pe_pct_own_5y is not null and coalesce(f.pe_meaningful, false) = false

union all

select v.symbol, v.period_end_date, v.pb, v.pb_pct_own_5y, 'pb_meaningful' as metric
from {{ ref('int_valuation_percentile') }} v
join {{ ref('stg_financial_ratio') }} f
  on f.symbol = v.symbol
 and f.period_end_date = v.period_end_date
 and f.quarter between 1 and 4
where v.pb_pct_own_5y is not null and coalesce(f.pb_meaningful, false) = false

union all

-- own_quarters_used (fix round 2, phát hiện bởi reviewer): mọi dòng có
-- pe_pct_own_5y/pb_pct_own_5y khác NULL phải có ĐÚNG cột số quý của CHÍNH
-- chỉ tiêu đó >= own_history_min_quarters. Đây chính là mệnh đề mà nếu có
-- từ đầu sẽ bắt được lỗi cột own_quarters_used dùng chung cho cả pe và pb
-- (UDC 2024-12-31: pb_pct_own_5y = 0,8889 hợp lệ nhưng cột metadata dùng
-- chung lại báo own_quarters_used = 0, vì đó là số quý của PE chứ không
-- phải PB).
select symbol, period_end_date, pe, pe_pct_own_5y, 'pe_quarters_used' as metric
from {{ ref('int_valuation_percentile') }}
where pe_pct_own_5y is not null and pe_quarters_used < {{ var('own_history_min_quarters') }}

union all

select symbol, period_end_date, pb, pb_pct_own_5y, 'pb_quarters_used' as metric
from {{ ref('int_valuation_percentile') }}
where pb_pct_own_5y is not null and pb_quarters_used < {{ var('own_history_min_quarters') }}
