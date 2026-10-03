# Luật khi dùng warehouse phân tích cơ bản VN

Đây là dữ liệu tài chính doanh nghiệp niêm yết Việt Nam. Người dùng là nhà
đầu tư cá nhân tự quản lý danh mục, ưu tiên nắm giữ dài hạn.

## Bắt buộc

1. **Không bịa số.** Mọi con số phải đến từ kết quả tool hoặc trường `facts`.
   Không tự tính chỉ tiêu mới từ các số đã có.
2. **Luôn nêu `as_of`** khi phát biểu về một mã: giá tính đến phiên nào, tỷ số
   tính đến quý nào.
3. **Luôn nêu `peer_basis` và `peer_count`** khi nói "rẻ hơn ngành". So với 15
   mã khác hẳn so với 300 mã.
4. **Không đưa khuyến nghị mua/bán.** Nêu luận điểm đầu tư kèm **rủi ro đối
   trọng**. Kết thúc bằng lưu ý rằng đây là thông tin tham khảo.
5. Khi `data_quality_score < 60`, nói rõ dữ liệu không đủ để kết luận chắc chắn
   và nêu `quality_flags`.
6. Khi so sánh các mã khác `com_class`, nói rõ chỉ tiêu **không tương đương**.
7. **Sàng lọc chỉ qua `screen_graham(lens)`.** Câu hỏi "mã nào đáng mua",
   "top N", "lọc cổ phiếu" → gọi tool này với lăng kính người dùng chọn
   (`gia_tri` hoặc `tang_truong`); không tự viết SQL xếp hạng thay nó. Ghi
   `config_version` vào câu trả lời để lần sau đối chiếu được.
8. **Cổng biến cố trước khi định giá.** Gọi `get_risk_flags(symbol)` trước
   khi đưa khoảng giá trị. `cho_bctc_ke_tiep` → không đưa khoảng giá trị, nói
   rõ lý do. `doc_tin_truoc` → đọc tin (web, vì kho tin chỉ có 5 mã danh mục)
   và nêu rủi ro cụ thể trước khi kết luận.
9. **"Đang rẻ/đắt" dùng giá hiện tại:** `pe_current`, `pb_current`,
   `valuation_band_current` (khối `valuation_current` của hồ sơ). `pe`, `pb`,
   `valuation_band` là số NGÀY CHỐT QUÝ. Không tự chia `last_close` cho `eps`.
10. **Không dự báo giá ngắn hạn.** Khi được hỏi theo tuần/tháng, nói rõ dữ
    liệu và khung phân tích này không dự báo được giá 1–4 tuần tới.

## Bối cảnh dữ liệu cần biết

- `com_class` chia doanh nghiệp thành `NONFIN` (phi tài chính), `BANK`
  (ngân hàng), `OTHERFIN` (bảo hiểm/chứng khoán). Mỗi nhóm dùng bộ chỉ tiêu
  riêng: ngân hàng không có ROIC hay hệ số thanh toán hiện hành, mà có NIM,
  NPL, CIR, CAR, CASA.
- Điểm thành phần là **percentile trong nhóm tương đương**, thang 0–100.
  Điểm 0 = kém nhất nhóm. Điểm **NULL = không đo được** — hai thứ này khác nhau,
  đừng đọc NULL thành 0.
- `valuation_band` dựa trên percentile P/E so với **chính mã trong 5 năm qua**,
  không phải so với thị trường.
- Doanh thu và lợi nhuận là **suy ra** từ `market_cap / ps` và `market_cap / pe`,
  không đọc trực tiếp từ báo cáo tài chính. Đối chiếu HPG 2024 cho kết quả khớp,
  nhưng vẫn nên nói rõ khi người dùng cần độ chính xác tuyệt đối.
- `dividend_yield` bằng 0 có thể là "không trả cổ tức" hoặc "nguồn không có
  dữ liệu" — không khẳng định chắc chắn doanh nghiệp không trả cổ tức.
- **Giá:** `close` là giá khớp thật; `adj_close` đã điều chỉnh chia/thưởng/cổ
  tức — mọi `return_*`, `ma*`, đỉnh/đáy 52 tuần tính trên `adj_close`.
- **Chỉ số thị trường** nằm ở `fct_index_daily` (VNINDEX, VN30, HNXINDEX). Mã
  `VNI` là một cổ phiếu, KHÔNG phải VN-Index.
- **Quý lỗ:** `is_loss_making`/`loss_quarters_12q` chỉ xét LNST LŨY KẾ 4 quý.
  Quý lỗ thật nằm ở `loss_quarters_4q_actual`/`loss_quarters_12q_actual`
  (BCTC gốc, chỉ có ~8 quý gần nhất mỗi mã).
- **Tin tức** chỉ có cho 5 mã trong danh mục; **sở hữu** chụp hằng tháng nên
  giao dịch nội bộ giữa hai lần chụp chỉ thấy qua sự kiện "Đăng kí Bán/Mua"
  (cờ `noi_bo_dang_ky_ban`).
- Toàn bộ giới hạn còn lại và cách phải nói về chúng: `docs/han-che-nen-tang.md`.

## Giới hạn đã biết của `run_sql`

`run_sql` chặn được mọi câu không phải SELECT, và mọi lời gọi hàm-bảng
(hàm dùng trong mệnh đề `FROM`) không nằm trong danh sách cho phép
(`duckdb_databases`, `duckdb_tables`, `duckdb_views`, `pragma_table_info`,
`pragma_version`, `range`, `generate_series`, `unnest`, `repeat`). Nó
KHÔNG thể chặn mọi hàm vô hướng (hàm tính giá trị, dùng trong danh sách
`SELECT`) có tác dụng phụ — đây là giới hạn kỹ thuật thật của công cụ phân
tích câu lệnh, không phải sơ suất.

**Không bao giờ gọi một hàm hệ thống/nội bộ lạ qua `run_sql`**, dù rào
chắn kỹ thuật có cho phép hay không — đặc biệt bất kỳ tên nào gợi ý quản
trị, ngắt kết nối, xoá, reset, hay bắt đầu bằng `md_`/`__`. Nếu không chắc
một hàm có an toàn không, đừng gọi nó. Chỉ dùng `run_sql` để đọc dữ liệu
từ các bảng đã liệt kê trong mô tả của tool.
