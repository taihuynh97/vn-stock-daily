-- Canh Critical #1 của vòng review toàn nhánh: giá trị ÂM ở một chỉ tiêu
-- "càng thấp càng tốt" được chấm là TỐT NHẤT thị trường.
--
-- mart_stock_scorecard đảo chiều các chỉ tiêu direction = 'lower' bằng
-- `adj = 1 - pct_peer`. Số âm là số nhỏ nhất trong rổ ⟹ percent_rank ≈ 0 ⟹
-- adj ≈ 1,0, tức điểm gần tuyệt đối. Trước khi sửa: KSH có pe = -419,14 và
-- nhận value_score 99,3; DAC có debt_to_equity = -7,91 (⟺ vốn chủ sở hữu ÂM)
-- và nhận quality_score 81,6, sát ngân hàng chất lượng nhất thị trường MBB
-- (83,2). Đo được 599 dòng vi phạm: ev_to_ebitda 255 · pe 247 · debt_to_equity
-- 90 · pb 2.
--
-- Test canh ĐÚNG đường sinh điểm: join theo (com_class, metric) y hệt CTE
-- `weighted` của mart_stock_scorecard, nên nó chỉ đỏ khi một giá trị âm thật
-- sự chảy được vào một điểm thành phần.
--
-- KHÔNG lọc `pct_peer is not null`: một giá trị âm lọt vào rổ còn Ô NHIỄM
-- percentile của MỌI mã cùng rổ (trước khi sửa, 1.193/1.266 mã lành mạnh bị
-- đẩy lên bậc phân vị cao hơn, tức trông đắt hơn thực tế) — kể cả khi bản thân
-- nó không nhận được pct_peer.
--
-- Chiều NGƯỢC LẠI (direction = 'higher') cố ý nằm ngoài phạm vi: roe_avg_8q,
-- roic, các biên lợi nhuận, revenue_yoy, earnings_yoy, gross_margin_slope_8q,
-- loans_growth... ÂM là giá trị THẬT và nằm đúng chỗ ở đáy thang. Bắt chúng ở
-- đây sẽ đẩy người sửa tới chỗ NULL hoá dữ liệu thật — đúng lỗi ngược lại.
select p.symbol, p.com_class, p.metric, p.value, p.pct_peer
from {{ ref('int_metric_percentile') }} p
join {{ ref('scoring_weights') }} w
  on w.com_class = p.com_class and w.metric = p.metric
where w.direction = 'lower'
  and p.value < 0
