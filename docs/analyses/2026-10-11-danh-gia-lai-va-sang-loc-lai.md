# Đánh giá lại bài CTG & FPT + sàng lọc lại (tăng trưởng) — 2026-10-11

**Câu hỏi:** "đánh giá lại bài phân tích đầu tư gần nhất của bạn, và cùng phân tích lại xem thì những cổ phiếu đáng
đầu tư có thay đổi không? ngoài lề là mình có hỏi thăm ý kiến vài người bạn hay có đầu tư, thì họ nói FPT luôn không
đáng đầu tư vì luôn đắt?"

**Phiếu intake:** sàng lọc lại + đánh giá lại · lăng kính `tang_truong` (người dùng chọn, giữ như 05/10) · nhiều năm ·
đọc trước: 3 file ngày 2026-10-05

**Mốc dữ liệu:** giá 2026-10-09 · BCTC 2026-06-30 (kho chưa có quý 3) · phễu `config_version` 2026-10-03.1 ·
VN-Index 1.735,09 (1 tháng −5,1%, 3 tháng −5,7%)

## Sửa lỗi trước khi sàng lọc
`int_valuation_current` neo giá theo ngày NẠP tỷ số thay vì ngày chốt quý (nhánh `fix/pe-current-neo-ngay-nap`,
test `assert_pe_current_matches_source_eps`: RED 231 mã lệch >2% → GREEN). Đo: 1.388/1.568 mã có giá ngầm định của
nguồn khớp giá đóng cửa phiên trước ngày nạp; 237 khớp giá ngày chốt. `dbt build --select int_valuation_current+`
lên production 2026-10-11: 28/28 PASS. pytest 450 passed, 2 xfailed. **Chưa merge** — job hằng ngày chạy từ main sẽ
build lại logic cũ.

## Phễu
| Bước | 05/10 | 11/10 |
|---|---|---|
| vu_tru | 135 | 139 |
| co_lai | 110 | 112 |
| roe_ben | 41 | 43 |
| tang_truong | 23 | 24 |
| deu_dan | 20 | 21 |
| pe_tran | 20 | 21 → 19 phân tích tiếp + 2 chờ |

Rổ: 18 mã cũ giữ nguyên + **TNG** (mới: vốn hoá vượt 2.000 tỷ, giá 16.600 → 18.300). Chờ: BFC, CTS (không đổi).
Thay đổi cổng: VHM, SIP chuyển `qua` (cờ nội bộ hết hạn); HAH thêm đăng ký bán nội bộ; MBB 2 đăng ký bán (tới 04/11);
SHB giảm 44% từ đỉnh. HDB 28.000 → 22.400 ngày 09/10 là giao dịch không hưởng quyền thưởng 25% (không phải sập giá).

## Đánh giá lại bài 05/10 (CTG & FPT)
1. **Sai phương pháp chính:** dùng cùng hệ số 14,3× (EPS ÷ 7%) cho ngân hàng đòn bẩy ~15 lần và công ty công nghệ.
   Thước đo thứ hai — P/E trung vị 8 năm của chính mã (CTG 8,98; FPT 17,40; P/E nguồn cuối năm 2018–2025):

   | Mã | Giá 09/10 | EPS ÷ 7% | Giá/… | P/E trung vị × EPS | Giá/… | Ngưỡng ⅔ (trung vị) | Số Graham |
   |---|---|---|---|---|---|---|---|
   | CTG | 29.500 | 61.400 | 48% | 38.600 | 76% | 25.700 | 49.800 |
   | FPT | 57.900 | 68.800 | 84% | 83.800 | 69% | 55.800 | 47.900 |

   CTG vẫn rẻ nhưng biên an toàn ~24% chứ không ~52%; kịch bản dự phòng 2% × P/E trung vị = 26.400 < giá → hết biên.
2. **Sai sự thật:** bài viết "P/E 11,7 thấp hơn mọi P/E cuối năm 2018–2025 (11,0–24,0)" — năm 2019 là 11,0. Nay P/E
   10,9 thì đúng là thấp nhất.
3. Bậc 1 của CTG ("dưới 40.900") dựa trên thước đo lạc quan; theo thước đo lịch sử, ngưỡng ⅔ là 25.700.
4. Đứng vững: không có biến cố làm gãy luận điểm; FPT 8 tháng LNTT 7.648 tỷ (+17,5%, CafeF 06/10) — giá giảm vì dòng
   tiền (khối ngoại bán ròng >14.700 tỷ từ đầu năm), không vì kinh doanh.

## "FPT luôn đắt"
- Đúng theo tiêu chí phòng thủ của Graham: P/E × P/B cuối năm 2018–2025 = 28,3 / 27,1 / 76,3 / 139,9 / 68,1 / 132,9 /
  123,8 / 47,8 — chưa năm nào ≤ 22,5; nay 29,7. Giá 57.900 vẫn cao hơn số Graham 47.900 21%.
- Đúng với người mua ở P/E cao: mua cuối 2024 (P/E ~28) → −50% giá điều chỉnh; cuối 2023 (P/E ~18) → −8% trong khi
  VN-Index +54%; cuối 2025 (P/E ~17) → −33%.
- Không còn đúng theo P/E: 10,9 là thấp nhất cửa sổ dữ liệu, trong khi EPS 2018–2025 tăng 20%/năm.

**Nguồn ngoài:** CafeF 06/10/2026 (FPT giảm 10 phiên, 8 tháng LNTT 7.648 tỷ); CafeF 08/10 (FPT chấm dứt chuỗi giảm).
