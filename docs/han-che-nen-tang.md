# Hạn chế nền tảng ảnh hưởng tới phân tích

Cập nhật: 2026-10-03 (mảng Q — sửa lỗi chất lượng phân tích). Số đo trên `md:vn_market`
và bản sao cục bộ cùng ngày.

Tài liệu này dành cho hai người đọc:

- **Bạn**, để biết kết luận của agent đứng trên nền dữ liệu nào và chỗ nào nền đó mỏng.
- **Agent phân tích** (skill `graham-fundamental-analysis`, MCP `vn-stock-analysis`), để biết
  phải nói gì khi một kết luận chạm vào giới hạn.

Mỗi mục có bốn phần: hạn chế, bằng chứng, ảnh hưởng tới phân tích, và agent phải làm gì.

## Tóm tắt

| # | Hạn chế | Ảnh hưởng lớn nhất | Mảng Q đã giảm nhẹ? |
|---|---|---|---|
| 1 | Tin tức chỉ có 5 mã danh mục | Không thấy biến cố của mã ứng viên mới | Một phần: cổng biến cố bắt buộc tìm tin web |
| 2 | Tỷ số quý trễ 1–4,5 tháng | Mã đang khủng hoảng trông rẻ giả | Một phần: định giá theo giá hiện tại + cổng biến cố |
| 3 | BCTC gốc: 8 quý, 8 năm | Không chạy được các bài kiểm 10 năm của Graham | Không |
| 4 | Doanh thu/LNST ở mart là số suy ra | Sai số khi cần chính xác tuyệt đối | Không (đã ghi chú từ A2) |
| 5 | Sở hữu chụp hằng tháng; cửa sổ 50 sự kiện | Bán ra của nội bộ giữa hai lần chụp có thể bị sót | Một phần: cờ đăng ký bán |
| 6 | Không có vĩ mô ngoài tỷ giá | Không neo được ngưỡng E/P, không đọc được chu kỳ lãi suất | Không |
| 7 | Không có dự phóng, kế hoạch kinh doanh, đồng thuận | Không biết doanh nghiệp tự dự báo gì | Không |
| 8 | Một nguồn duy nhất (VCI qua vnstock) | Lỗi nguồn đi thẳng vào phân tích | Một phần: hợp đồng OHLC, test dữ liệu |
| 9 | Giá điều chỉnh phụ thuộc giá tham chiếu | Sót sự kiện nếu kho thiếu phiên quanh ngày GDKHQ | Mới thêm ở mảng Q |
| 10 | Khối ngoại chưa có lịch sử | Không phân tích được dòng vốn ngoại | Bắt đầu lưu từ ngày merge |
| 11 | CAR ngân hàng NULL toàn kho | Không đánh giá được an toàn vốn ngân hàng | Không |
| 12 | Hạ tầng: dung lượng, thời gian job | Dữ liệu có thể cũ khi job gãy | Không |
| 13 | Khung phân tích không dự báo giá ngắn hạn | Câu hỏi "tuần này mua gì" không trả lời được | Đã viết thành luật |

## 1. Tin tức chỉ có cho 5 mã trong danh mục

**Bằng chứng.** `raw_news` chỉ nạp HPG, IDV, MLS, PHP, VNR (`config/portfolio.yml`), cửa sổ 50 tin/mã.

**Ảnh hưởng.** Agent không thấy tin của bất kỳ mã ứng viên nào. Ngày 12/09/2026, PNJ được
phân tích mà không đọc diễn biến tháng 7–9 trong kho, vì kho không có tin PNJ.

**Agent phải làm.** Với mọi mã lọt vòng cuối, tìm tin web 90 ngày gần nhất và dẫn nguồn kèm ngày.
Nói rõ khi không tìm được.

**Hướng sửa.** Mở rộng `raw_news` cho rổ ứng viên (tốn lượt gọi API; cần brainstorm, xem nợ #3 của mảng D).

## 2. Tỷ số tài chính trễ so với giá

**Bằng chứng.** Tỷ số theo quý (`fct_financial_quarterly`) mới nhất là 30/06/2026 trong khi giá
đã đến 02/10/2026. Quý 3 thường có sau 20–45 ngày kể từ cuối quý, và job weekly mới kéo về.

**Ảnh hưởng.** Trước mảng Q, P/E, P/B, vùng định giá và `value_score` đứng yên ở giá ngày
chốt quý. Mảng Q quy đổi sang giá hiện tại (`pe_current`), nhưng **lợi nhuận vẫn là 4 quý đến
ngày chốt**. Doanh nghiệp đang gặp biến cố vì thế trông rẻ giả: PNJ có P/E hiện tại khoảng 2,2
và "thấp hơn 100% lịch sử" ngay khi đang lỗ nặng.

**Agent phải làm.** Luôn nêu hai mốc ngày (giá và tỷ số). Gọi `get_risk_flags` trước khi định
giá. Mã có `risk_gate = cho_bctc_ke_tiep` không được đưa khoảng giá trị.

**Quy ước cần biết.** `pe_current` = P/E ngày chốt × tỷ lệ giá đã điều chỉnh. Cổ tức tiền trả sau
ngày chốt nằm trong tỷ lệ đó, nên P/E hiện tại hơi cao hơn thực tế, lệch cỡ tỷ suất cổ tức.

## 3. Độ sâu lịch sử BCTC gốc

**Bằng chứng.** BCTC quý gốc: 1.142 mã có đúng 8 quý gần nhất (cửa sổ trượt của B2). BCTC năm:
1.229 mã có 8 năm (2018–2025). Chuỗi tỷ số thì dài hơn: 34 quý từ 2018-Q1.

**Ảnh hưởng.** Các bài kiểm 10 năm của Graham (lợi nhuận dương 10 năm, tăng trưởng EPS 10 năm,
cổ tức 20 năm) không chạy đầy đủ được. Đếm quý lỗ thật chỉ thấy tối đa khoảng 8 quý dù cột tên là
`loss_quarters_12q_actual`.

**Agent phải làm.** Ghi "đạt — nới từ 10 xuống 8 năm" thay vì "đạt". Không bao giờ chấm một bài
kiểm 10 năm trên 5 năm dữ liệu mà không nói.

## 4. Doanh thu và lợi nhuận ở mart là số suy ra

**Bằng chứng.** `revenue_ttm = market_cap / ps`, `earnings_ttm = market_cap / pe`
(`int_fundamentals_ttm`). Đối chiếu HPG khớp, nhưng đây là số lũy kế 4 quý suy từ bội số.

**Ảnh hưởng.** Đủ dùng cho xếp hạng và tăng trưởng. Không đủ cho công thức Graham cần số chính xác.

**Agent phải làm.** Công thức Graham chỉ tính từ dòng BCTC gốc (`get_financial_statement`). Lỗ
quý dùng `loss_quarters_*_actual` (đọc từ BCTC gốc), không dùng `is_loss_making` (TTM).

## 5. Sở hữu và sự kiện doanh nghiệp

**Bằng chứng.** Cổ đông và ban lãnh đạo chụp hằng tháng (`raw_shareholder`, `raw_officer`).
Nguồn sự kiện chỉ trả 50 sự kiện gần nhất mỗi mã. Đợt thưởng 300% của TRC và 80% của PHR tháng
9/2026 có trong bảng sự kiện nhưng thiếu ngày GDKHQ.

**Ảnh hưởng.** Giao dịch của người nội bộ giữa hai lần chụp không hiện ở `get_ownership`. Ngày
04/09/2026, hai người nhà lãnh đạo PNJ đăng ký bán tổng 25 triệu cổ phiếu; tin này có trong bảng
sự kiện nhưng không bước phân tích nào đọc.

**Agent phải làm.** Đọc cờ `noi_bo_dang_ky_ban` và `pha_loang_von` trong `get_risk_flags`.
Không dùng bảng sự kiện để suy ra số cổ phiếu hay điều chỉnh giá.

## 6. Không có dữ liệu vĩ mô ngoài tỷ giá

**Bằng chứng.** Kho chỉ có tỷ giá VCB (mảng D). CPI, lãi suất, tăng trưởng tín dụng, lợi suất
trái phiếu Chính phủ không có — nguồn đầy đủ (WiFeed) thu phí.

**Ảnh hưởng.** Ngưỡng E/P ≥ lợi suất trái phiếu và giá trị theo sức sinh lời không neo được bằng
dữ liệu trong kho.

**Agent phải làm.** Tìm lợi suất TPCP 10 năm trên web, ghi nguồn và ngày. Không tìm được thì nói
bài kiểm E/P không neo được, không tự đoán lãi suất.

## 7. Không có dự phóng, kế hoạch kinh doanh hay đồng thuận

**Bằng chứng.** Không bảng nào chứa kế hoạch lợi nhuận năm, dự phóng của công ty chứng khoán
hay điều chỉnh kế hoạch. Ví dụ: PNJ hạ kế hoạch 2026 từ lãi 3.409 tỷ xuống lỗ 6.271 tỷ ngày
28/09 — kho không có thông tin này.

**Agent phải làm.** Graham vốn không dựa vào dự phóng, nhưng agent phải tìm trên web các điều
chỉnh kế hoạch gần đây của mã vòng cuối.

## 8. Một nguồn dữ liệu duy nhất

**Bằng chứng.** Mọi dữ liệu đi qua vnstock (VCI). vnstock bị gỡ khỏi PyPI khoảng 25/09/2026, chuyển
sang index riêng. Lỗi ánh xạ cột bảng giá (mảng Q) làm 52–63% dòng giá hằng ngày sai suốt 4 tháng
mà không job nào báo.

**Ảnh hưởng.** Không có nguồn thứ hai để đối chiếu. Lỗi nguồn hoặc lỗi ánh xạ đi thẳng vào phân tích.

**Đã giảm nhẹ.** Hợp đồng OHLC ở tầng ingest làm đỏ job khi >5% dòng có close ngoài [low, high];
hai test dbt dạng cảnh báo theo dõi bước nhảy giá và OHLC.

## 9. Giá điều chỉnh dựa vào giá tham chiếu

**Bằng chứng.** Từ mảng Q, sự kiện điều chỉnh được phát hiện bằng `ref_price(D) / close(phiên trước)`.
Lịch sử trước ngày chạy script sửa được nguồn điều chỉnh sẵn.

**Ảnh hưởng.** Nếu kho thiếu đúng phiên trước ngày GDKHQ (job lỗi), sự kiện đó không được phát
hiện và giá trước đó không được điều chỉnh. Test `assert_adjusted_returns_within_limits` sẽ báo.

**Agent phải làm.** Khi một mã có lợi suất bất thường, kiểm `fct_price_daily.adj_factor` và lịch
sử phân phối trước khi kết luận.

## 10. Khối ngoại chưa có lịch sử

**Bằng chứng.** Bảng giá có khối lượng và giá trị mua/bán của nhà đầu tư nước ngoài; mảng Q bắt
đầu lưu vào `raw_price_daily` từ lần chạy đầu tiên sau merge. Không nạp bù được.

**Ảnh hưởng.** Chưa phân tích được dòng vốn ngoại. Sau vài tháng lưu mới có chuỗi đủ dài.

## 11. CAR của ngân hàng NULL toàn kho

**Ảnh hưởng.** Không đánh giá được an toàn vốn ngân hàng từ kho. Agent nói rõ thay vì bỏ qua.

## 12. Hạ tầng

- **Dung lượng MotherDuck free tier:** khoảng 8,6/10 GB (ghi nhận 25/08/2026). Khi đầy, job ingest gãy trước.
- **Job monthly BCTC:** đo 767 phút, vượt trần 360 phút của GitHub Actions — BCTC có thể chưa được làm mới.
- **Không có `first_seen_at`:** không phân biệt "kỳ BCTC mới công bố" với "kỳ được nạp lại".

**Agent phải làm.** Nêu `ratio_as_of` và tuổi tỷ số; cờ `ty_so_cu` bật khi tỷ số quá 150 ngày.

## 13. Giới hạn của chính khung phân tích

- **Không dự báo giá ngắn hạn.** Câu hỏi "tuần này mua gì" không trả lời được bằng phân tích cơ
  bản. Agent phải nói điều này trước, rồi trả lời câu hỏi dài hạn.
- **Điểm thành phần là phân vị trong nhóm.** Điểm cao là tương đối so với nhóm, không phải tuyệt
  đối; nhóm nhỏ thì phân vị nhiễu. Luôn nêu `peer_basis` và `peer_count`.
- **`dividend_yield = 0` mơ hồ.** Có thể là không trả hoặc nguồn thiếu số liệu.
- **Đánh giá một phương pháp bằng giá hai tuần của một mã là nhiễu.** Rổ 8 mã còn lại của ngày
  12/09 đi ngang thị trường (−0,5% so với trung vị −1,2%, 11–24/09). Cú giảm của PNJ là do luận
  điểm sai, không phải do nhiễu — hai chuyện phải tách bạch khi hậu kiểm.
