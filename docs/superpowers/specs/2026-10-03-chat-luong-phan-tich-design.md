# Thiết kế: Sửa lỗi chất lượng phân tích (nhánh `fix/chat-luong-phan-tich`)

Ngày: 2026-10-03 · Người yêu cầu: chủ dự án · Loại: kiến trúc (chạm ingest, dbt, chấm điểm, MCP, skill)

## 1. Bối cảnh và triệu chứng

Người dùng phản ánh hai điều:

1. Mỗi lần hỏi phân tích, kết quả ra **rất không ổn định** (03/09 chọn IDC, 10/09 chọn ngân hàng,
   12/09 ra rổ 11 mã khác).
2. PNJ được nêu ngày 12/09 ở 38.200 đ; ngày 28/09 PNJ công bố dự kiến lỗ cả năm ~6.271 tỷ, cổ phiếu
   giảm sàn 5 phiên liền về 23.050 đ (02/10).

Yêu cầu: rà soát toàn bộ repo, sửa mọi lỗi ảnh hưởng chất lượng phân tích, và nói rõ hạn chế nền tảng.

**Cách hiểu (đã ghi lại, chưa được người dùng xác nhận vì đang chạy tự động):** thành công nghĩa là
(a) cùng một câu hỏi + cùng dữ liệu cho ra cùng kết quả; (b) số liệu nền đúng; (c) agent không định
giá mã đang có biến cố; (d) mọi giới hạn còn lại được viết ra, không giấu.

## 2. Kết quả rà soát

Đo trên `md:vn_market` ngày 2026-10-03 (giá đến 02/10, tỷ số đến 30/06) và trên bản sao cục bộ.

| # | Mức | Tầng | Lỗi | Bằng chứng | Xử lý |
|---|---|---|---|---|---|
| C1 | Nghiêm trọng | Ingest | Giá đóng cửa hằng ngày lấy nhầm cột **giá tham chiếu** (`listing.ref_price`) vì `_find()` trả cột đầu tiên chứa *bất kỳ* từ khoá nào ("price"). Từ 07/06/2026 mọi `close` = giá đóng cửa phiên **trước**; ngày GDKHQ còn là giá đã điều chỉnh. | `close` nằm ngoài [low, high]: 0% trước tháng 6, 52,7% tháng 6, 61–63% tháng 7–10. TRC 15/09: close 20.150 < low 21.100. | Sửa ánh xạ + kiểm tra hợp đồng dữ liệu + script sửa lịch sử |
| C2 | Nghiêm trọng | Ingest/dbt | Giá không được điều chỉnh sau chia/thưởng cổ phiếu: lịch sử nạp bù 07/06 đã điều chỉnh tới ngày đó, còn dòng hằng ngày thì không → bước nhảy giả. | 29 mã nhảy ≥16%/phiên trong 11–24/09 (TRC −75%, PHR −47%). Sai `return_*`, `ma*`, `high_52w`, `volatility_60d`. | Lưu `ref_price`; dbt tính hệ số điều chỉnh; nạp lại lịch sử đã điều chỉnh |
| C3 | Nghiêm trọng | Ingest | Phiên ma ngày lễ: `is_trading_day()` chỉ loại T7/CN. | 31/08, 01/09, 02/09 có dòng giá chép lại phiên 28/08. | Dùng ngày giao dịch của bảng giá; xoá phiên ma |
| C4 | Nghiêm trọng | dbt | `loss_quarters_12q`/`is_loss_making` đếm quý có **LNST lũy kế 4 quý âm**, không phải quý lỗ (biên LN của nguồn là TTM). | 103 mã có quý lỗ thật trong 4 quý nhưng ghi 0 (11 mã thanh khoản, gồm PNJ, STB, PLX, EIB). | Thêm lợi nhuận quý thật từ BCTC gốc |
| H1 | Cao | dbt | P/E, P/B, `valuation_band`, `value_score` **đóng băng ở giá ngày chốt quý** (trễ tới ~4,5 tháng). Chia `last_close` cho EPS quý cũ sai khi có thưởng cổ phiếu sau ngày chốt (PHR ngày 12/09 trông rẻ giả). | Scorecard: `pe` theo 30/06, `last_close` theo 02/10. | Định giá hiện tại theo tỷ lệ giá đã điều chỉnh |
| H2 | Cao | Quy trình | Sàng lọc viết SQL tự do mỗi lần, ngưỡng và thước đo đổi theo phiên; skill không dùng `search_stocks`. | 3 phân tích 03–12/09 dùng 3 bộ tiêu chí khác nhau. | Tool sàng lọc tất định `screen_graham` + cấu hình có phiên bản |
| H3 | Cao | Quy trình/dbt | Không có cổng loại trừ biến cố trước khi định giá. | PNJ được chấm 7/7 khi đang có nghĩa vụ mua lại không trần. | `mart_risk_flags` + tool `get_risk_flags` + luật skill |
| H4 | Cao | Skill | Không hỏi lăng kính/kỳ hạn, không ghi lại phân tích để đối chiếu, thiết kế Intake 12/09 chưa từng áp dụng. | Memory + transcript 12/09. | Viết lại phần quy trình của skill |
| H5 | Trung bình | dbt/MCP | Không có chỉ số thị trường ở tầng mart; mã `VNI` là cổ phiếu, dễ nhầm VN-Index. | `raw_index_daily` có VNINDEX/VN30/HNXINDEX từ 2016 nhưng không mart nào dùng. | `fct_index_daily` |
| H6 | Trung bình | dbt | Scorecard không lưu lịch sử → không tái lập được kết quả cũ. | Ghi chú sẵn trong `get_thesis_update`. | Bảng chụp hằng ngày `mart_scorecard_daily` |
| M1 | Trung bình | Nguồn | Sự kiện thưởng cổ phiếu thiếu ngày GDKHQ (TRC 300%, PHR 80%). | `raw_corporate_event.exright_date` NULL. | Không dựa vào sự kiện để điều chỉnh giá (dùng `ref_price`); ghi vào hạn chế |
| M2 | Trung bình | dbt | `market_cap` dùng cho ngưỡng vũ trụ lấy từ hồ sơ DN hằng tháng. | `dim_stock.market_cap` từ `raw_company_info`. | Thêm `market_cap_current` |
| M3 | Thấp | Phân tích cũ | Bản PNJ 12/09 ghi lỗ Q2 −283 tỷ; BCTC gốc ghi −739 tỷ. | `raw_financial_statement` PNJ 2026-q2. | Ghi vào tài liệu hậu kiểm |

Những gì đã kiểm và **không** có lỗi: dữ liệu chỉ số (đúng đơn vị, đủ phiên); đơn vị `value` (triệu đồng);
khối NULL≠0 và rào số âm của tầng chấm điểm; `dbt build` trên DuckDB cục bộ (163 node, 162 PASS,
1 WARN có sẵn, 12,7 giây — lần build cục bộ thật đầu tiên, đóng nợ N14 của A2).

## 3. Vì sao kết quả "không ổn định" — ba nguồn

1. **Quy trình (H2, H4):** agent tự chọn thước đo, ngưỡng và tầng phân loại mỗi lần. Đây là nguồn lớn nhất.
2. **Số liệu sai nhưng trông hợp lệ (C1–C4, H1):** giá lệch một phiên, bước nhảy giả, cột "quý lỗ" đo
   sai, định giá đóng băng — kết quả sàng lọc đổi theo lỗi chứ không theo doanh nghiệp.
3. **Không có trí nhớ có cấu trúc (H6, H4):** không lưu scorecard và kết luận cũ nên không đối chiếu bằng số được.

## 4. Thiết kế sửa

### 4.1 Ingest (`src/ingest_market.py`, `src/warehouse.py`, `src/dq.py`)

- Thay `_find()` bằng `_pick()`: thử ứng viên **theo thứ tự**, khớp chính xác tên cột phẳng trước
  (`match.match_price`), rồi khớp hậu tố (`.match_price`). Không còn khớp chuỗi con tự do.
- Ánh xạ VCI: close=`match.match_price`, open=`match.open_price`, high=`match.highest`,
  low=`match.lowest`, volume=`match.accumulated_volume`, value=`match.accumulated_value`,
  ref_price=`listing.ref_price`, trading_date=`listing.trading_date`, và 4 cột khối ngoại
  `match.foreign_{buy,sell}_{volume,value}`.
- Mã không khớp lệnh trong phiên (match_price rỗng/0, volume 0): close = ref_price, volume 0.
- Ngày giao dịch lấy từ bảng giá; nếu khác ngày chạy → ngày nghỉ → không ghi (sửa C3 tận gốc).
- `dq.assert_ohlc_consistent()`: nếu >5% dòng có khớp lệnh mà close ngoài [low, high] → ném lỗi.
  Lớp lỗi C1 đã chạy im lặng 4 tháng; từ nay nó làm đỏ job.
- `raw_price_daily` thêm cột `ref_price`, `foreign_buy_volume`, `foreign_sell_volume`,
  `foreign_buy_value`, `foreign_sell_value` bằng `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  (idempotent, chạy trong `init_schema`). Khối ngoại chỉ lưu ở tầng raw, chưa mô hình hoá — lý do:
  dữ liệu bảng giá không nạp bù được, ngày nào không lưu là mất.

### 4.2 Script sửa lịch sử `scripts/repair_price_history.py`

- Với mỗi mã: gọi `Quote.history` từ ngày đầu tiên đang có tới hôm nay (giá đã điều chỉnh tới hôm nay),
  ghi đè open/high/low/close/volume; **giữ** `value` và cột khối ngoại đang có; `ref_price` = NULL cho
  dòng sửa; `loaded_at` = thời điểm sửa (đây là "mốc điều chỉnh" mà dbt dùng).
- Xoá phiên ma: dòng có `trade_date` không có trong lịch phiên VNINDEX (`raw_index_daily`).
- Mặc định `--dry-run`; tham số `--db`, `--symbols`, `--limit`. Tôn trọng `_throttle()` (60 lượt/phút).
- **Chạy trên production là bước sau merge** (mục 7), không chạy từ nhánh.

### 4.3 dbt

- `stg_price_daily`: thêm `ref_price`, khối ngoại, `loaded_at`, cờ `is_ohlc_inconsistent`.
- `int_price_adjustment` (mới): sự kiện điều chỉnh = phiên D có `ref_price(D) / close(phiên trước) ≠ 1`
  (lệch > 0,05%). Hệ số của dòng t = tích các hệ số có ngày D > max(t, ngày của `loaded_at` dòng t)
  — dòng nạp bù sau sự kiện đã được nguồn điều chỉnh nên không nhân lần hai.
- `int_price_features`/`fct_price_daily`: MA, return, volatility, đỉnh/đáy 52 tuần tính trên
  `adj_close`; giữ `close` gốc để hiển thị; thêm `adj_close`, `ref_price`, khối ngoại.
- `int_quarterly_profit` (mới): LNST quý thật từ BCTC gốc, ưu tiên
  `attributable_to_parent_company` → `net_profit_attributable_to_shareholders_of_the_group` →
  `net_profit_loss_after_tax` → `profit_after_tax`. Tính `loss_quarters_4q_actual`,
  `loss_quarters_12q_actual`, `latest_quarter_profit`, `latest_quarter_profit_yoy`.
- `fct_financial_quarterly`: thêm các cột trên; mô tả lại `loss_quarters_12q` là "số quý có LNST
  lũy kế 4 quý âm" (giữ tên để không vỡ truy vấn cũ).
- `int_valuation_current` (mới): `price_ratio = adj_close(phiên mới nhất) / adj_close(phiên cuối cùng
  ≤ ngày chốt quý)`; `pe_current = pe_quý × price_ratio`, tương tự `pb_current`, `market_cap_current`;
  `pe_pct_own_5y_current` = phân vị của `pe_current` trong 20 quý của chính mã.
- `int_metric_long` lấy `pe`/`pb` hiện tại; scorecard dùng phân vị hiện tại → `value_score` phản ánh giá
  hôm nay. Scorecard trả cả hai bộ (`pe` theo quý, `pe_current` hôm nay).
- Chấm điểm `safety`: thay `loss_quarters_12q` bằng `loss_quarters_12q_actual` (trọng số giữ 0,20).
- `mart_risk_flags` (mới), mỗi mã một dòng, mỗi cờ có mức:
  - nghiêm trọng: `lo_quy_gan_day` (quý lỗ thật trong 4 quý), `loi_nhuan_quy_giam_manh`
    (quý gần nhất < 50% cùng kỳ năm trước, khi cùng kỳ dương);
  - cảnh báo: `gia_giam_sau` (cách đỉnh 52 tuần ≤ −40%, trên giá điều chỉnh), `pha_loang_von`
    (phát hành riêng lẻ/quyền mua/chuyển đổi/chào bán rộng rãi trong 365 ngày hoặc sắp tới),
    `noi_bo_dang_ky_ban` (DDIND/DDINS/DDRP "Đăng kí Bán" trong 90 ngày), `ty_so_cu` (tỷ số > 150 ngày).
  - `risk_gate`: `cho_bctc_ke_tiep` nếu có cờ nghiêm trọng; `doc_tin_truoc` nếu chỉ có cảnh báo; `qua`.
- `fct_index_daily` (mới): VNINDEX/VN30/HNXINDEX kèm return 1m/3m/6m/12m/YTD.
- `mart_scorecard_daily` (mới, incremental, khoá `snapshot_date+symbol`): chụp các cột chính mỗi lần build.
- Test dữ liệu mới: OHLC nhất quán cho dòng mới; không có bước nhảy giá điều chỉnh vượt biên độ sàn
  mà không giải thích được (warn); lợi nhuận quý khớp BCTC; risk gate đủ phủ.

### 4.4 Chấm điểm / sàng lọc (`src/scoring.py`, `config/`)

- Khoá `require` mới `exclude_recent_loss_quarters` (dùng `loss_quarters_4q_actual`), bật cho cả 3 profile.
- Vũ trụ dùng `market_cap_current` khi có.
- `config/graham_screen.yml` (mới, có `version`): hai lăng kính.
  - `gia_tri`: vũ trụ (vốn hoá ≥1.000 tỷ, GTGD ≥2 tỷ, DQ ≥60, HOSE/HNX) → có lãi TTM và 0 quý lỗ thật
    trong 12 quý → `pe_current` ∈ (0, 15] → `pe_current × pb_current` ≤ 22,5 (⇔ giá ≤ số Graham)
    → cổ tức ≥5 năm liên tiếp → NONFIN: thanh toán hiện hành ≥1,5 → biên an toàn: tích ≤ 10
    (⇔ giá ≤ ⅔ số Graham). Xếp theo `pe×pb` tăng dần.
  - `tang_truong`: vũ trụ (≥2.000 tỷ, ≥3 tỷ) → có lãi như trên → ROE 8 quý ≥15% và độ bền ≥0,6 →
    CAGR LN 3 năm ≥10% và doanh thu ≥5% → độ đều tăng trưởng ≥0,6 → `pe_current` ≤ 25.
    Xếp theo điểm tổng hợp profile `quality_growth`.
  - Mọi bước đếm số mã còn lại; xếp hạng có khoá phụ `symbol` để kết quả tất định.

### 4.5 MCP (`mcp_server/`)

- Tool mới `screen_graham(lens, limit)`: chạy phễu ở 4.4, tách kết quả thành `phan_tich_tiep` và
  `cho` theo `risk_gate`, trả `config_version`, đếm từng bước, VN-Index 1m/3m làm mốc, `as_of`.
- Tool mới `get_risk_flags(symbol)`.
- `get_stock_profile`: thêm định giá hiện tại, lỗ quý thật, risk gate.
- `run_sql`: liệt kê `fct_index_daily`, `mart_risk_flags`, `mart_scorecard_daily`.
- `instructions.md`: luật mới — dùng `pe_current`, không tự chia giá cho EPS, VN-Index ở
  `fct_index_daily`, mã có `risk_gate ≠ qua` không được đưa khoảng giá trị.
- Tổng tool: 13 → 15.

### 4.6 Skill `graham-fundamental-analysis`

- **Bước Intake** (bắt buộc, trước mọi lời gọi dữ liệu trừ đọc phân tích cũ): dạng câu hỏi, lăng kính
  (giá trị / tăng trưởng — hỏi nếu không rõ), kỳ hạn nắm giữ, phễu. Xác nhận bằng một câu hỏi.
- Sàng lọc **chỉ** qua `screen_graham`; SQL tự do chỉ để đào sâu một mã, không để xếp hạng.
- **Cổng biến cố** trước Bước 5: `get_risk_flags` + tìm tin web cho từng mã vòng cuối (kho tin chỉ có 5 mã).
  Có nghĩa vụ tiềm tàng không trần hoặc `risk_gate ≠ qua` → "chưa định giá được", không chấm 7/7.
- Kỳ hạn: nói rõ khung này không dự báo giá 1–4 tuần.
- Không xếp "một mã tốt nhất"; trả rổ.
- Ghi mỗi phân tích vào `docs/analyses/YYYY-MM-DD-<chủ-đề>.md` (lăng kính, `config_version`, as_of,
  danh sách, ngưỡng) để lần sau đối chiếu bằng số.
- Mục "Giới hạn nền tảng" trỏ tới `docs/han-che-nen-tang.md`.

### 4.7 Tài liệu

- `docs/han-che-nen-tang.md`: mọi hạn chế còn lại, ảnh hưởng tới phân tích ra sao, cách agent phải nói.
- `docs/Q-ket-qua-va-no-ky-thuat.md`: kết quả nghiệm thu nhánh này, theo khuôn các mảng trước.

## 5. Ngoài phạm vi (ghi vào hạn chế)

Lịch sử BCTC chỉ 8 năm; không có lợi suất TPCP/CPI/lãi suất; không có dự phóng/đồng thuận;
tin tức chỉ 5 mã; sở hữu chụp hằng tháng; cửa sổ 50 sự kiện; CAR NULL; một nguồn VCI không đối chiếu;
`first_seen_at`; dung lượng MotherDuck; job monthly vượt trần GitHub Actions; khối ngoại chưa có lịch sử.

## 6. Kiểm thử và nghiệm thu

- pytest: ánh xạ bảng giá (DataFrame giả cột VCI thật, gồm trường hợp không khớp lệnh và ngày lễ),
  `assert_ohlc_consistent`, logic sửa lịch sử trên DuckDB tạm, tool MCP mới, khoá `require` mới.
- dbt: build toàn DAG trên bản sao cục bộ sau khi chạy script sửa cho một rổ mã thật (TRC, PHR, PNJ,
  REE, FPT, HPG, DGC, VNM, MBB, …): không còn bước nhảy giả; `pe_current` của PHR/TRC hợp lý;
  PNJ có `risk_gate = cho_bctc_ke_tiep`.
- Đối chiếu trước/sau: so scorecard nhánh main và nhánh này trên cùng dữ liệu (bao nhiêu mã đổi
  `value_score` > 10 điểm, ví dụ cụ thể).
- Tất định: gọi `screen_graham` hai lần → kết quả giống hệt.

## 7. Triển khai sau merge (người dùng quyết định)

1. Merge PR → job daily dùng ánh xạ mới, thêm cột (ALTER idempotent).
2. Chạy `python scripts/repair_price_history.py --db md:vn_market` (bỏ `--dry-run`), ~30 phút.
3. Chạy workflow `dbt build`.
Trước bước 2, dữ liệu giá từ 07/06 vẫn lệch một phiên; dbt mới không làm tệ hơn.
Rủi ro: script ghi đè ~1,3 triệu dòng giá; giảm thiểu bằng dry-run, chạy thử trên bản sao, giữ `value`.
