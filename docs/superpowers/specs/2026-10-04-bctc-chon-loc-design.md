# Thiết kế: nạp BCTC chọn lọc + ngân sách thời gian (nhánh `feat/bctc-chon-loc`)

Ngày 2026-10-04 · Người dùng đã đồng ý hướng này trong hội thoại cùng ngày.

## Vấn đề (đã đo, PR #12 + workflow diagnose-api)

- Job `warehouse-weekly` bị huỷ ở bước nạp dữ liệu mọi tuần từ 05/09; dbt của job tuần chưa từng chạy.
- Tỷ số và sự kiện mất ~30 phút mỗi bước (nhịp 1,05 giây, đúng thiết kế).
- BCTC quý gọi ~4.800 lần (1.600 mã × 3 báo cáo). Từ GitHub mỗi lần ~5 giây → ~7 giờ > trần 6 giờ.
- **Gọi song song bị nguồn chặn:** trên GitHub, 5 luồng cho 55/90 lần hết thời gian chờ, 7,7 lần/phút —
  chậm hơn tuần tự (~12 lần/phút). Không thể tăng tốc từng lần gọi.
- Nguồn còn treo theo đợt: 30 giây/lần thử, vnstock thử tới 3 lần.
- Job luôn bắt đầu lại từ mã đầu danh sách nên mã cuối không bao giờ được làm mới.

## Thiết kế

### 1. Dò trước, tải đủ khi cần (`ingest_market.fetch_financial_statements`, tham số `known`)

Với mỗi mã, gọi `income_statement` trước. Gọi tiếp `balance_sheet` + `cash_flow` chỉ khi:
- mã chưa có BCTC trong kho, hoặc
- kỳ mới nhất nguồn trả về MỚI HƠN kỳ đã lưu (so chuỗi `YYYY-qN`), hoặc
- lần tải đủ gần nhất cũ hơn `refresh_days` (mặc định 90) — để bắt điều chỉnh số liệu.

Lần dò lỗi hoặc dò rỗng (nguồn không có BCTC) → không gọi hai báo cáo còn lại của mã đó. `known=None` giữ hành vi cũ (tải đủ 3 báo cáo).

### 2. Mã cũ nhất đi trước (`warehouse.statement_freshness` + `build_warehouse`)

Mã chưa từng có BCTC đứng đầu, sau đó xếp theo lần dò gần nhất tăng dần. Lần chạy bị dừng giữa
chừng thì lần sau tự làm tiếp phần cũ nhất — đây là phần "xoay vòng" tối thiểu, không cần bảng mới:
mốc thời gian lấy từ `ingested_at` của chính `raw_financial_statement`.

### 3. Ngân sách thời gian (`INGEST_BUDGET_MINUTES`)

`build_warehouse` tính hạn chót từ lúc bắt đầu. Trước mỗi giai đoạn và trước mỗi mã BCTC, quá hạn thì
dừng, ghi `etl_load_log` trạng thái `partial` kèm lý do, và thoát bình thường. Workflow tuần/tháng đặt
270 phút và chạy các bước dbt với `if: !cancelled()` — dbt luôn chạy trên dữ liệu đã có.

### 4. Tạm nghỉ khi nguồn treo

Sau 5 lần gọi lỗi liên tiếp: nghỉ `STATEMENT_PAUSE_SECONDS` (mặc định 180). Sau 3 lần nghỉ mà vẫn lỗi
liên tiếp: dừng bước BCTC (`stop_reason = nguon_treo`). Mục tiêu: không bị nguồn phạt nặng hơn.

## Ước tính

| Thời điểm | Lần gọi BCTC | Thời gian trên GitHub |
|---|---|---|
| Ngoài mùa báo cáo | ~1.600 lần dò + ít mã đến hạn 90 ngày | ~2,7 giờ |
| Mùa báo cáo (nhiều mã có kỳ mới) | + 2 lần/mã có kỳ mới | có thể vượt ngân sách → tuần sau làm tiếp |

## Số đo production 04/10/2026 (ước tính lần chạy tuần tới)

1.603 mã hoạt động: 316 chưa có BCTC trong kho (phần lớn nguồn không có), 55 quá 90 ngày chưa tải đủ,
1.232 chỉ cần dò. Ước tính ~1.700–2.350 lần gọi BCTC (~2,9–3,9 giờ) + tỷ số và sự kiện ~1 giờ.
Lần chạy đầu có thể chạm ngân sách 270 phút; khi đó tuần sau làm tiếp từ mã cũ nhất.

## Ngoài phạm vi

Song song hoá (đã bác bỏ bằng số đo); tách workflow BCTC riêng; chuyển nơi chạy. Xem lại sau khi có
số đo của 2–3 lần chạy tuần với log thời gian thực.

## Kiểm thử

- `fetch_financial_statements` với `known`: mã mới → 3 lần gọi; kỳ mới → 3; không đổi và còn hạn → 1;
  quá 90 ngày → 3; dò lỗi → 1 lần gọi, không gọi tiếp; quá hạn chót → dừng, `stopped_early`.
- Tạm nghỉ: 5 lỗi liên tiếp gọi `sleep`; vượt số lần nghỉ → dừng với `nguon_treo`.
- `statement_freshness` + thứ tự: mã chưa có đứng đầu, rồi theo lần dò tăng dần.
- `build_warehouse`: quá ngân sách trước giai đoạn → bỏ qua có ghi log `partial`.
