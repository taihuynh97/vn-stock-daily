# Thiết kế: nạp rải sự kiện DN + BCTC quý (nhánh `feat/nap-rai-nhip-cham`)

Ngày 2026-10-05 · Người dùng đồng ý hướng "giãn nhịp + chạy rải" trong hội thoại cùng ngày.
Tiếp nối [2026-10-04-bctc-chon-loc-design.md](2026-10-04-bctc-chon-loc-design.md).

## Vấn đề (đã đo 04–05/10)

- Nguồn `iq.vietcap.com.vn` (sự kiện DN, BCTC) chỉ chịu ~100–150 lệnh mỗi đợt, rồi bắt đầu treo từng lệnh.
  Tình trạng này xảy ra cả sau một đêm nghỉ và cả trên IP GitHub. Endpoint tỷ số thì không bị.
- BCTC chọn lọc vẫn cần ~1.700+ lệnh/tuần, sự kiện ~600 lệnh. Gọi dồn trong một job thì luôn bị bóp.

## Thiết kế

1. **Hạn mức mỗi lần chạy.**
   - `EVENTS_MAX_SYMBOLS`: `SourceBreaker(max_symbols=…)` dừng sau N mã thành công.
   - `STATEMENTS_MAX_CALLS`: `fetch_financial_statements(max_calls=…)` dừng trước mã kế tiếp khi đã đủ số lệnh.
   - Khi dừng vì hạn mức, lý do ghi là `du_han_muc`, `etl_load_log` ghi `ok` (dừng đúng kế hoạch, không phải lỗi).
2. **Mã cũ nhất trước cho sự kiện.**
   - Bảng mới `source_fetch_log(dataset, symbol, fetched_at)` ghi mã đã tải thành công.
   - `_order_by_fetch_age` xếp mã chưa từng tải lên đầu, các mã còn lại theo lần tải tăng dần.
   - BCTC đã có thứ tự riêng (`statement_freshness` + `statement_probe`).
3. **Workflow `warehouse-trickle`.**
   - Chạy 3 lần/ngày: 06:07, 11:07 và 19:07 giờ VN.
   - Mỗi lần: nhịp 5 giây, ≤50 mã sự kiện, ≤70 lệnh BCTC, ngân sách 35 phút.
   - Lệnh chạy: `--only events,statements`. Không chạy dbt; job ngày build lại cả DAG.
   - Nhóm concurrency riêng. Không dùng chung nhóm với job ngày/tuần/tháng: GitHub chỉ giữ 1 lần chờ mỗi nhóm, nên lần chờ mới sẽ huỷ lần chờ cũ.
4. **Job tuần/tháng bỏ sự kiện + BCTC quý** (`--only`). BCTC năm vẫn để ở job tháng.

## Ước tính

| | Mỗi ngày | Một vòng |
|---|---|---|
| Sự kiện (599 mã ≥500 tỷ + danh mục) | 150 mã | ~4 ngày |
| BCTC quý (~1.600 lần dò + tải đủ khi có kỳ mới) | ≤210 lệnh | ~8–10 ngày ngoài mùa BCTC |
| Phút GitHub Actions | ~3 × 15 phút = ~45 phút | ~1.350 phút/tháng |

Repo private có 2.000 phút/tháng, trong đó job ngày và job tuần cũng dùng. Job tuần giờ ngắn hơn nhiều, nhưng tổng phút cần theo dõi ở tháng đầu.
Nếu vượt, có thể giảm xuống 2 lần/ngày hoặc chuyển repo public (phải xử lý lịch sử giá vốn danh mục trước).

## Theo dõi sau khi merge

- Đọc `notes` trong `etl_load_log` của 3–5 lần chạy đầu. Nếu hay gặp `nguon_treo` trước khi đủ hạn mức, hạ hạn mức xuống.
  Nếu luôn đạt `du_han_muc` nhanh, có thể nâng dần.
