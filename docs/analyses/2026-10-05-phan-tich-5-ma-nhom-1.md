# Phân tích Graham 5 mã nhóm 1 (CTG, LPB, FPT, DGW, CTR) — 2026-10-05

**Câu hỏi:** "phân tích hết 5 mã của nhóm 1" (nhóm 1 = qua cổng biến cố + tin sạch, từ
`2026-10-05-sang-loc-tang-truong.md`)

**Phiếu intake:** định giá từng mã · lăng kính `tang_truong` · nắm giữ nhiều năm · phân tích cũ: sàng lọc cùng ngày

**Mốc dữ liệu:** giá 2026-10-02 · BCTC đến 2026-06-30 · phễu `config_version` 2026-10-03.1 ·
lợi suất TPCP 10 năm 4,43–4,59% (TradingView/vietbao, 09/2026) · lãi huy động cao nhất ~7,2%

## Lỗi dữ liệu phát hiện trong lần này — `pe_current` bị quy đổi giá HAI lần

`raw_financial_ratio` của quý mới nhất (nạp 2026-10-04) tính P/E, P/B, market_cap theo **giá phiên 02/10**
(market_cap / số CP = đúng last_close ở cả 10 mã kiểm: CTG, CTR, DGW, FPT, HDB, IDC, LPB, MBB, SHB, VHM).
`int_valuation_current` lại giả định P/E đó là của ngày chốt 30/06 và nhân thêm adj_close(02/10)/adj_close(30/06).

| Mã | pe_current (sai) | P/E đúng (giá 02/10) |
|---|---|---|
| LPB | 7,99 | 10,63 |
| SHB | 3,62 | 4,40 |
| CTG | 5,12 | 5,75 |
| VHM | 6,24 | 6,98 |
| HDB | 8,04 | 7,31 |
| DGW | 13,68 | 12,06 |

Hệ quả: `screen_graham` (bước P/E, P/E×P/B), `get_stock_profile.valuation_current`, `compare_stocks` đều lệch
theo mức biến động giá từ 30/06. Hướng sửa: lấy giá ngầm định của nguồn (market_cap / number_of_shares_mkt_cap)
làm mốc thay vì giá ngày chốt. **Chưa sửa** — chờ người dùng.

Ngoài ra: `fct_price_daily.close` của phiên cũ là giá ĐÃ điều chỉnh bởi nguồn (CTR 74.390 đ ngày 30/06, FPT
65.180,00000000001 — không phải bước giá HOSE), nên `close = adj_close` và kiểm "bước nhảy giá" không bắt được
chia/thưởng. Phương pháp trong file này: EPS = LNST cổ đông mẹ (BCTC gốc) / số CP hiện tại.

## Phương pháp định giá (cố định cho 5 mã)

- EPS chuẩn hoá = TB(EPS 2024, EPS 2025, EPS TTM đến Q2/2026), tất cả chia số CP hiện tại.
- Thấp = số Graham √(22,5 × EPS chuẩn hoá × BVPS). Trung tâm = EPS chuẩn hoá / 7% (lãi huy động/doanh
  nghiệp, ≈14,3×). Cao = EPS chuẩn hoá / 4,6% (TPCP 10 năm, ≈21,7×).
- Công thức 8,5+2g chỉ để chạy ngược (g ngầm định), không dùng làm cận khoảng — g=10 cho 7–10 năm quá lạc quan.
- Ngưỡng biên an toàn = ⅔ giá trị trung tâm.

## Kết quả

| Mã | Giá | EPS chuẩn hoá | P/E TTM | P/B | Thấp – Trung tâm – Cao | Ngưỡng ⅔ | Giá/TT | g ngầm định |
|---|---|---|---|---|---|---|---|---|
| CTG | 29.750 | 4.297 | 5,75 | 1,16 | 49.800 – 61.400 – 93.400 | 40.900 | 0,48 | −0,8% |
| LPB | 40.200 | 3.619 | 10,63 | 2,79 | 34.300 – 51.700 – 78.700 | 34.500 | 0,78 | 1,3% |
| FPT | 62.100 | 4.814 | 11,71 | 2,93 | 47.900 – 68.800 – 104.600 | 45.800 | 0,90 | 2,2% |
| CTR | 71.200 | 4.664 | 13,93 | 4,07 | 42.900 – 66.600 – 101.400 | 44.400 | 1,07 | 3,4% |
| DGW | 45.600 | 2.726 | 12,19 | 2,72 | 32.100 – 38.900 – 59.300 | 26.000 | 1,17 | 4,1% |

Bảng điểm phòng thủ (8 năm thay 10; cổ tức ≥7 năm thay 20): CTG 5/7 (1 N/A ngân hàng, trượt cổ tức) ·
LPB 4/7 (1 N/A; trượt cổ tức, P/E×P/B) · FPT 5/7, 3 nới lỏng (trượt thanh toán 1,56, P/E×P/B 43) ·
CTR 4/7 · DGW 4/7. Bảng điểm chủ động: CTG 4/4 áp dụng · LPB 3/4 · FPT 4/5 · CTR 3/5 · DGW 3/5.

**Xếp loại:**
- CTG — giá dưới cả cận thấp; ứng viên nhà đầu tư chủ động. Rủi ro: lợi nhuận 2025–26 được đẩy bởi chi phí
  dự phòng giảm (dự phòng/dư nợ −1,92% Q3/24 → −0,95% Q2/26; dự trữ/dư nợ 2,21% → 1,61%); đòn bẩy VCSH/TS 6,8%;
  Nhà nước 64,5%; cổ tức tiền thấp (450 đ), giữ lại lợi nhuận qua cổ tức CP.
- LPB — trong khoảng, sát ngưỡng ⅔; luận điểm tăng trưởng yếu đi: LNST 6T/2026 −2,6%, nợ xấu 1,85% (↑),
  dự trữ/nợ xấu ~67%, CASA 6,4%, CIR 35%, VCSH/TS 8,5% → 7,0%. Giá −28% từ đỉnh 24/06, không tìm thấy lý do cụ thể.
- FPT — trong khoảng (0,90 trung tâm) → chưa có biên an toàn; dưới ~45.800 mới có. Chất lượng cao nhất nhóm.
  Từ 2026 FPT Telecom hạch toán theo vốn chủ sở hữu (doanh thu −~20.000 tỷ/năm, LN không đổi).
- CTR — trên trung tâm → ngoài vùng mua.
- DGW — trên trung tâm; lưu chuyển tiền KD 8 năm cộng dồn ~370 tỷ so với LN 3.226 tỷ (2024, 2025 âm);
  biên gộp Q2/26 13,0% (vs 8,5%) chưa chứng minh bền.

**Khác lần trước:** sàng lọc sáng nay ghi P/E LPB 8,0 / CTG 5,1 / DGW 13,7 — đó là `pe_current` lỗi; số đúng
10,6 / 5,75 / 12,1. Không mã nào trong nhóm 1 đổi nhóm vì lỗi này, nhưng LPB trông rẻ hơn thực tế ~25%.

**Nguồn ngoài:** thesaigontimes.vn + cafef.vn (FPT Telecom đổi hạch toán, 03/2026), vnbusiness.vn (FPT Q2),
vietstock.vn (DGW Q2 +167%, 07/2026), nguoiquansat.vn (DGW biên gộp), cafef.vn/cafebiz.vn (LPB mất giá, 02/10/2026),
vietstock.vn (tuần cuối tháng 9), tradingview.com VN10Y + vietbao.vn (lợi suất TPCP), vietstock.vn (CTG tháng 9).
