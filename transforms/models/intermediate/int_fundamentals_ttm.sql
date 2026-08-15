{{ config(materialized='table') }}

-- Vì pe, ps, pb và market_cap cùng thuộc một dòng (cùng thời điểm giá),
-- phép chia triệt tiêu giá và cho ra chỉ tiêu tuyệt đối.
-- Đối chiếu HPG 2024Q4: 138.855 tỷ doanh thu / 12.021 tỷ LNST — khớp BCTC.
-- Chỉ dùng dòng TTM (quarter 1-4); dòng cả năm (quarter=5) bị loại để chuỗi
-- thời gian không lẫn hai loại kỳ.
with ttm as (
    select
        symbol,
        year,
        quarter,
        period_end_date,
        com_class,
        market_cap,
        number_of_shares_mkt_cap                as shares,
        -- Fix round 1 (coordinator review): ps <= 0 bị NULL hoá TRƯỚC khi
        -- chia — doanh thu ÂM vô nghĩa kinh tế/vô dụng cho định giá (đo
        -- production: 43 dòng ps<0 + 486 dòng ps=0). Ví dụ PTC 2020Q4
        -- ps=-1277: bất động sản hoàn nhập doanh thu do huỷ hợp đồng — có
        -- thật về kế toán nhưng không dùng được ở tầng chấm điểm/định giá.
        -- KHÁC với pe bên dưới: pe âm là HỢP LỆ và PHẢI giữ (doanh nghiệp
        -- lỗ → earnings_ttm âm là kết quả ĐÚNG, đã đối chiếu HPG 2023Q2 =
        -- -1.908 tỷ khớp tuyệt đối). ĐỪNG áp cùng logic `case when > 0` cho
        -- pe để "nhất quán" — điều đó sẽ xoá mất tín hiệu lỗ thật.
        market_cap / nullif(case when ps > 0 then ps end, 0)  as revenue_ttm,
        market_cap / nullif(pe, 0)                            as earnings_ttm,
        -- pb <= 0: vốn chủ sở hữu suy ra ÂM hoặc bằng 0 (mất vốn/sentinel)
        -- — P/B không có nghĩa trong trường hợp này, NULL hoá trước khi
        -- chia, cùng lý do với ps ở trên (khác pe: không có khái niệm "lỗ
        -- vốn chủ" hợp lệ tương tự "lỗ lợi nhuận").
        market_cap / nullif(case when pb > 0 then pb end, 0)  as book_value,
        is_loss_making
    from {{ ref('stg_financial_ratio') }}
    where quarter between 1 and 4
),

-- Fix round 2 (coordinator review, C1): GHÉP THEO LỊCH, KHÔNG DÙNG lag()
-- THEO DÒNG.
--
-- lag(x, 4) lấy dòng cách 4 VỊ TRÍ, chỉ đúng nếu chuỗi quý liền mạch. Thực
-- tế 1.378/1.585 mã (87%) có khoảng trống — riêng 2021 Q2 chỉ 177/1.585 mã
-- báo cáo (kể cả HPG: dòng 2021Q2 vắng mặt trong chính chuỗi TTM của nó).
-- Đo trên production với bản dùng lag(): 53% dòng revenue_yoy LẬT DẤU tăng
-- trưởng, và 62,7% giá trị revenue_cagr_3y lẽ ra phải NULL.
--
-- Ví dụ minh hoạ bằng chính HPG (thiếu 2021 Q2): từ dòng 2021Q4 lùi 4 VỊ TRÍ
-- được 2021Q3 -> 2021Q1 -> 2020Q4 -> 2020Q3, tức chỉ tới 2020Q3 chứ không tới
-- 2020Q4. Khoảng trống nằm TRONG cửa sổ nhìn lại thì kết quả sai; nằm ngoài
-- thì tình cờ đúng. Ghép theo lịch loại bỏ hẳn sự tình cờ đó.
--
-- Không tồn tại kỳ đối chiếu thì kết quả là NULL — đó là câu trả lời ĐÚNG.
-- Task 10 chuẩn hoá lại trọng số khi gặp NULL nên không gây hại.
with_lags as (
    select
        t.*,
        y1.revenue_ttm  as revenue_4q_ago,
        y1.earnings_ttm as earnings_4q_ago,
        y3.revenue_ttm  as revenue_12q_ago,
        y3.earnings_ttm as earnings_12q_ago,
        -- Số quý tuyệt đối, dùng cho cửa sổ theo LỊCH ở dưới.
        t.year * 4 + t.quarter as abs_quarter
    from ttm t
    left join ttm y1
           on y1.symbol = t.symbol and y1.year = t.year - 1 and y1.quarter = t.quarter
    left join ttm y3
           on y3.symbol = t.symbol and y3.year = t.year - 3 and y3.quarter = t.quarter
),

-- Cửa sổ 12 quý phải tính theo LỊCH, không theo 12 dòng liền kề — cùng lý
-- do như trên. `range` trên abs_quarter cho đúng ngữ nghĩa "12 quý gần
-- nhất", bất kể chuỗi có khoảng trống hay không.
with_windows as (
    select
        *,
        sum(case when is_loss_making then 1 else 0 end) over w12 as loss_quarters_raw,
        -- Fix Minor 5.1 (vòng sửa 3) — CƠ SỞ BẰNG CHỨNG của loss_quarters_raw.
        --
        -- `count(is_loss_making)` chứ KHÔNG phải `count(*)`: ta cần số quý THẬT
        -- SỰ BIẾT được lỗ hay lãi, không phải số quý CÓ DÒNG. Hai con số này
        -- khác nhau ở 14 mã trên production, và chênh lệch rơi đúng vào ca nặng
        -- nhất: BLU và HAV có ĐỦ 12 DÒNG trong cửa sổ nhưng 0 quý biết
        -- (is_loss_making NULL cả 12 — hệ quả Task 8.5 NULL hoá
        -- after_tax_profit_margin trong 686 "dòng trắng"). Một cổng dựa trên
        -- count(*) sẽ cho cả hai đi qua và chúng giữ nguyên loss_quarters = 0,
        -- tức điểm an toàn TỐT NHẤT có thể, dựng trên KHÔNG một quan sát nào.
        -- Còn 7 mã nữa cùng cảnh: BXT 11 dòng/0 biết, GTK/GQN/TDN 8/0,
        -- HAW/HUX/HGR 6/0.
        count(is_loss_making) over w12 as loss_quarters_observed
    from with_lags
    window w12 as (
        partition by symbol order by abs_quarter
        range between 11 preceding and current row
    )
),

with_growth as (
    select
        *,
        -- revenue_yoy: rào chắn mốc gốc dương ở đây là RÀO CHẮN CẤU TRÚC, không
        -- phải bản vá dữ liệu. Đã đo trên production trước khi thêm: 0/36.676
        -- dòng có revenue_ttm < 0 — không thể khác, vì revenue_ttm =
        -- market_cap / ps chỉ được tính khi ps > 0 (xem CTE `ttm`) và market_cap
        -- đã nullif(0) ở stg. Nên mệnh đề này KHÔNG đổi một giá trị nào hôm nay
        -- (kiểm chứng: số dòng revenue_yoy non-null trước/sau phải bằng nhau);
        -- nó tồn tại để mệnh đề "mốc gốc phải dương" là bất biến TƯỜNG MINH của
        -- cả bốn chỉ tiêu tăng trưởng, thay vì một sự trùng hợp phải suy ra từ
        -- hai model khác.
        --
        -- Vòng sửa 2 — kiểm lại: revenue_yoy KHÔNG có vấn đề tương tự
        -- earnings_yoy. Không tồn tại ca "lật doanh thu" (dương → âm) vì
        -- revenue_ttm không bao giờ âm theo cấu trúc nêu trên, nên ở đây không
        -- có vế nào để bỏ bớt. Một vế `revenue_4q_ago > 0` là đủ và đúng, khớp
        -- đúng hình thái của earnings_yoy bên dưới.
        case when revenue_4q_ago > 0
             then revenue_ttm / revenue_4q_ago - 1 end  as revenue_yoy,
        -- Fix vòng review toàn nhánh (Important #2): YoY phải chịu CÙNG rào chắn
        -- "mốc gốc dương" như earnings_cagr_3y ngay dưới. Bản cũ
        -- `earnings_ttm / nullif(earnings_4q_ago, 0) - 1` chia cho một mốc ÂM,
        -- làm LẬT DẤU tăng trưởng: lỗ PHÌNH TO đọc thành tăng trưởng đỉnh bảng.
        --
        -- Đo trên production trước khi sửa (kỳ mới nhất, 1.585 mã): 165 mã tính
        -- YoY qua mốc gốc <= 0, trong đó 37 mã ĐANG LỖ mà nhận earnings_yoy
        -- DƯƠNG — TSC lỗ 36 tỷ nhận YoY +93,9 và pct_peer = 1,000, tức ĐỨNG ĐẦU
        -- rổ tăng trưởng của ngành; KVC và ICF cũng 1,000. Chiều ngược lại: 352
        -- mã ĐANG CÓ LÃI nhận YoY âm vì mốc gốc âm. earnings_yoy có
        -- direction = 'higher', trọng số 0,15 trong thành phần tăng trưởng của
        -- cả NONFIN, OTHERFIN lẫn BANK.
        --
        -- Lỗi ranh giới: model này GHI earnings_yoy như một tỉ số đại số (đúng
        -- về số học), còn int_metric_percentile ĐỌC nó như một thang có thứ tự
        -- "cao là tốt". Mỗi bên đọc riêng đều đúng — nên 13 vòng review
        -- từng-task bỏ sót.
        --
        -- VÌ SAO CHỈ MỘT VẾ, TRONG KHI earnings_cagr_3y NGAY DƯỚI CÓ HAI VẾ —
        -- ĐÂY LÀ CHỦ ĐÍCH, KHÔNG PHẢI SÓT (vòng sửa 2).
        --
        -- Bản sửa đầu của vòng này chép nguyên rào chắn của earnings_cagr_3y
        -- (`... and earnings_ttm > 0`) cho "nhất quán". Đó là quá tay: lỗi cần
        -- chữa là MỐC GỐC ÂM, và chỉ `earnings_4q_ago > 0` chữa nó. Với mốc gốc
        -- DƯƠNG, `(hiện tại - gốc) / gốc` luôn xác định và ĐÚNG DẤU kể cả khi
        -- hiện tại âm — doanh nghiệp lật từ lãi sang lỗ cho một YoY âm lớn, là
        -- câu trả lời ĐÚNG và phải nằm bét rổ tăng trưởng.
        --
        -- earnings_cagr_3y thì BUỘC phải có cả hai vế vì nó lấy CĂN BẬC BA:
        -- power(số âm, 1.0/3) không xác định trong miền số thực của DuckDB (ra
        -- NaN). YoY không hề vướng ràng buộc đó — nó chỉ là một phép chia.
        --
        -- Đo trên production khi phát hiện: vế thừa `earnings_ttm > 0` NULL hoá
        -- 1.098 dòng LẬT LÃI → LỖ (toàn bộ 1.098, không sót dòng nào). Ở kỳ mới
        -- nhất có 21 mã lật, trong đó 16 mã VẪN GIỮ growth_score, trung bình
        -- 46,1 — điểm tầm trung cho doanh nghiệp vừa lật sang lỗ. Nguyên nhân:
        -- mart_stock_scorecard loại NULL khỏi MẪU SỐ khi chuẩn hoá lại trọng số,
        -- nên NULL không phải là "phạt", nó là "miễn" — 0,55 trọng số còn lại
        -- (revenue_cagr_3y 0,30 + revenue_yoy 0,15 + growth_consistency 0,10)
        -- vẫn vượt cổng 0,5 và mã đó được chấm trên doanh thu, bỏ qua việc lợi
        -- nhuận vừa sụp. Ví dụ điển hình là nhóm VTJ / SGI / PEN / SDU: đều vừa
        -- lật sang lỗ mà vẫn mang growth_score 84-92 khi earnings_yoy bị NULL,
        -- nay còn 66-74 với YoY âm ở phân vị 0,00-0,08 (gần bét rổ).
        --
        -- Ràng buộc toàn cục của dự án: NULL nghĩa "KHÔNG ĐO ĐƯỢC", không phải
        -- "kém nhất nhóm" (đó là 0). Ở đây ta ĐO ĐƯỢC — nên phải ghi ra số.
        case when earnings_4q_ago > 0
             then earnings_ttm / earnings_4q_ago - 1 end as earnings_yoy,
        -- CAGR 3 năm chỉ có nghĩa khi mốc gốc dương. Vế `... _ttm > 0` ở HAI
        -- dòng dưới là BẮT BUỘC (căn bậc ba của số âm không xác định), khác hẳn
        -- earnings_yoy ở trên — xem ghi chú dài ngay trên đó trước khi "sửa cho
        -- nhất quán".
        case when revenue_12q_ago > 0 and revenue_ttm > 0
             then power(revenue_ttm / revenue_12q_ago, 1.0 / 3) - 1 end as revenue_cagr_3y,
        case when earnings_12q_ago > 0 and earnings_ttm > 0
             then power(earnings_ttm / earnings_12q_ago, 1.0 / 3) - 1 end as earnings_cagr_3y
    from with_windows
),

-- Fix Minor 5.1 (vòng sửa 3): growth_consistency mắc CÙNG lỗ hổng cửa sổ mỏng
-- với loss_quarters_12q, chỉ ở dạng nhẹ hơn. avg() bỏ qua NULL nên nó KHÔNG
-- bịa ra giá trị khi cả cửa sổ đều trống (ra NULL, đúng) — nhưng với ĐÚNG MỘT
-- quan sát dương nó cho ra 1,0, tức "nhất quán tăng trưởng HOÀN HẢO 12 quý"
-- suy từ một quý duy nhất. Đo trên production tại kỳ mới nhất: 416 mã có
-- growth_consistency dựng trên dưới 6 quan sát, 390 mã dưới 4; trong đó 93 mã
-- đạt đúng 1,0 và 15 mã đạt 1,0 từ MỘT quan sát (SSF, TAB, CGL, PDT, SCA...).
-- growth_consistency có scale='direct' + direction='higher' nên 1,0 là điểm
-- tuyệt đối, chiếm 0,10 trọng số tăng trưởng.
--
-- Đây đúng câu mà chính comment cổng chặn của mart_stock_scorecard đã đặt tên:
-- "Tự tin tối đa từ bằng chứng tối thiểu."
--
-- Tách CTE riêng thay vì tính inline ở SELECT cuối để cột đếm quan sát và cột
-- giá trị dùng CHUNG một định nghĩa cửa sổ, không thể lệch nhau khi sửa sau này.
with_consistency as (
    select
        *,
        -- Tính nhất quán tăng trưởng: tỉ lệ quý có YoY doanh thu dương trong 12
        -- quý. Cửa sổ theo LỊCH (`range` trên abs_quarter), không phải 12 dòng
        -- liền kề — cùng lý do với loss_quarters_12q ở trên (fix round 2).
        avg(case when revenue_yoy > 0 then 1.0
                 when revenue_yoy is null then null
                 else 0.0 end) over w12 as growth_consistency_raw,
        count(revenue_yoy) over w12 as growth_consistency_observed
    from with_growth
    window w12 as (
        partition by symbol order by abs_quarter
        range between 11 preceding and current row
    )
)

select
    symbol,
    year,
    quarter,
    period_end_date,
    com_class,
    market_cap,
    shares,
    revenue_ttm,
    earnings_ttm,
    book_value,
    earnings_ttm / nullif(shares, 0) as eps,
    book_value   / nullif(shares, 0) as bvps,
    revenue_yoy,
    earnings_yoy,
    revenue_cagr_3y,
    earnings_cagr_3y,
    -- Fix Minor 5.1 (vòng sửa 3): CỬA SỔ QUÁ MỎNG PHẢI LÀ "KHÔNG ĐO ĐƯỢC",
    -- KHÔNG PHẢI "CHƯA LỖ QUÝ NÀO".
    --
    -- `sum(case when ... then 1 else 0 end)` trên một cửa sổ chỉ có 1-2 quý cho
    -- ra 0, và `loss_quarters_12q` có direction='lower' với trọng số 0,20 trong
    -- thành phần an toàn ⟹ 0 là ĐIỂM TUYỆT ĐỐI. Nghĩa là "không quan sát được
    -- quý nào" đang được đọc thành "chưa lỗ quý nào" — cùng hình thái với bốn
    -- lỗi của vòng review toàn nhánh: một giá trị KHÔNG BIẾT bị suy thành giá
    -- trị CÓ LỢI NHẤT.
    --
    -- Đo trên production tại kỳ mới nhất của mỗi mã, trước khi sửa: 392 mã chỉ
    -- có 4-7 quý (286 mã báo "0 quý lỗ") và 121 mã có dưới 4 quý (74 mã báo
    -- "0 quý lỗ") — tức 360 mã tuyên bố không lỗ quý nào trong khi có dưới 8
    -- quý dữ liệu. ALC có ĐÚNG 2 quý, báo 0 quý lỗ, nhận safety_score 74,2
    -- (trên trung vị); CLI có ĐÚNG 1 quý và được 74,1.
    --
    -- Ngưỡng: nửa cửa sổ (6/12 quý), đặt ở var window_min_observed_quarters —
    -- thống nhất với triết lý "phải đo được ít nhất một nửa" của cổng
    -- weight_coverage >= 0,5 ở mart_stock_scorecard. Đây là con số duy nhất
    -- cần đổi nếu muốn siết/nới chính sách này.
    case when loss_quarters_observed >= {{ var('window_min_observed_quarters') }}
         then loss_quarters_raw end as loss_quarters_12q,
    -- Phơi cơ sở bằng chứng cạnh chính con số, theo đúng tiền lệ đã bốn lần cần
    -- tới trong dự án này: pe_quarters_used (Task 6), n_pe (Task 8),
    -- *_weight_coverage (Task 10), rejected_counts (src/scoring.py). Một con số
    -- không mang theo cỡ mẫu của nó thì không ai kiểm được nó đáng tin tới đâu.
    loss_quarters_observed,
    -- Task 10 fix: is_loss_making đã được tính trong CTE `ttm` (dùng để suy
    -- loss_quarters_12q) và trôi qua with_lags/with_windows/with_growth
    -- (đều select *), nhưng bị rớt khỏi SELECT cuối — không model nào cần đến
    -- tới trước mart_stock_scorecard. Phơi lại nguyên giá trị đã tính, không
    -- đổi công thức nào.
    is_loss_making,
    case when growth_consistency_observed >= {{ var('window_min_observed_quarters') }}
         then growth_consistency_raw end as growth_consistency,
    growth_consistency_observed
from with_consistency
