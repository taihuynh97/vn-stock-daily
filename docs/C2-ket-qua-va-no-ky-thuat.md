# C2 — Kết quả nghiệm thu & Nợ kỹ thuật

> Hoàn tất 2026-08-19, merge vào `main` qua PR #8 (`feat/c2-canh-bao-su-kien`,
> commit merge `e0a5ac9`) ngày 2026-08-20. Tài liệu này giữ lại những gì git
> log không nói được: **vì sao** các quyết định được đưa ra, và **những gì
> còn nợ**. Nhật ký đầy đủ từng task từng nằm ở
> `.superpowers/sdd/2026-08-19-c2-canh-bao-su-kien/progress.md` (git-ignored,
> đã xoá sau khi review cuối sạch theo quy trình subagent-driven-development
> — git log là bản ghi chính thức).

---

## 1. Tóm tắt C2

C2 (cảnh báo theo sự kiện DN) hoàn thành qua **2 task**, cộng 1 vòng final
review toàn nhánh (model Opus) và 1 vòng sửa cuối cùng cho 3 Important.

| Hạng mục | Kết quả |
|---|---|
| Task | 2/2 |
| Script mới | 1 — `alert_events.py` (root, cùng cấp `main.py`/`build_warehouse.py`) |
| Bảng warehouse mới | 1 — `alert_sent_log` (MotherDuck, khoá `event_id`) |
| Workflow GitHub Actions mới | 1 — `.github/workflows/event-alerts.yml` |
| pytest sau vòng sửa cuối | 334 passed, 2 xfailed |

Phạm vi: 5 mã trong `config/portfolio.yml` (HPG, IDV, MLS, PHP, VNR). Nguồn
sự kiện: `stg_corporate_event` (đã có từ B1, không ingest gì mới). Chống
lặp tin bằng MotherDuck (`alert_sent_log`), KHÔNG tái dùng SQLite cục bộ
của hệ thống bot cũ (`src/storage.py`, tự nhận "best-effort" trong docstring
vì phụ thuộc GitHub Actions cache dễ mất). Không đụng
`main.py`/`digest.py`/`signals.py`/`screener.py`/`storage.py`/`daily.yml` —
chạy song song hoàn toàn.

**C2 là nhánh ĐẦU TIÊN trong lịch sử dự án có tác dụng phụ thật ra bên
ngoài warehouse** (có thể gửi tin Telegram thật) — khác mọi nhánh trước
(A1-C1) vốn chỉ đọc dữ liệu. Điều này chi phối toàn bộ cách nghiệm thu Task
2 (xem mục 2).

---

## 2. Sự cố production thật khi nghiệm thu — đã xử lý minh bạch, đã sửa tận gốc

Lần chạy `alert_events.py` ĐẦU TIÊN trên production (Task 2, nghiệm thu)
bị **ngắt giữa chừng do timeout hạ tầng** (không phải lỗi thiết kế) — batch
ghi `alert_sent_log` dừng lại giữa chừng ở mã VNR, để lại **8/50 sự kiện**
đã ghi log thay vì đủ 50. 4 mã còn lại (HPG, IDV, MLS, PHP) đã seed đầy đủ
trước khi bị ngắt.

**Vì sao đây là vấn đề nghiêm trọng nếu không phát hiện:** cơ chế
`split_symbols_by_seed_status` coi 1 mã là "đã seed" chỉ cần có ÍT NHẤT 1
dòng trong `alert_sent_log` — mã VNR bị seed dở dang (8 dòng) vẫn được coi
là "đã xong". Nếu chạy lần 2 mà không xử lý, 42 sự kiện VNR còn lại (2019-
2026, cổ tức/AGM/phát hành...) sẽ bị hiểu nhầm là "sự kiện MỚI" và **gửi
thật vào Telegram** — đúng lỗi mà toàn bộ C2 được sinh ra để tránh.

**Cách phát hiện & xử lý (đúng tinh thần "dừng lại khi nghi ngờ" đã áp
dụng xuyên suốt dự án):**
1. Implementer phát hiện qua đối chiếu số dòng trước/sau, lập luận đúng qua
   code path rằng lần chạy đầu KHÔNG gửi gì (an toàn), nhưng ĐÚNG lúc đó
   dừng lại, KHÔNG chạy tiếp lần 2 dù được nhắc — đúng chỉ dẫn "DỪNG NGAY,
   đừng tự ý sửa cho êm".
2. Controller tự kiểm chứng độc lập (đối chiếu trực tiếp `alert_sent_log`
   trên production), xác nhận đúng chẩn đoán, rồi hoàn tất seed dở dang
   bằng cách gọi TRỰC TIẾP hàm `mark_events_alerted` (không qua
   `alert_events.main()`/`notify.send` — không có tin nào được gửi trong
   bước xử lý này).
3. Lần chạy thứ 2 (sau khi đã hoàn tất seed) được xác nhận: không gửi gì,
   đúng thiết kế.

**Đã sửa TẬN GỐC ở final review** (không chỉ vá triệu chứng lần này):
`mark_events_alerted` từng dùng `con.executemany(...)` — DUY NHẤT hàm ghi
hàng loạt trong `src/warehouse.py` dùng pattern này, khác mọi hàm khác
(`insert_corporate_events`, `upsert_shareholders`, `upsert_prices`...) đều
dùng `con.register(df) + 1 câu INSERT...SELECT` (DuckDB chạy atomic,
all-or-nothing). Đã sửa `mark_events_alerted` sang đúng idiom chung — nếu
bị ngắt giữa chừng LẦN SAU, KHÔNG dòng nào được ghi (mã đó vẫn đúng trạng
thái "chưa seed", lần chạy kế tiếp tự làm lại đúng, không cần can thiệp
tay). Có test hồi quy xác nhận đúng hành vi atomic
(`test_mark_events_alerted_that_bai_giua_chung_khong_ghi_dong_nao`).

**Bài học chung:** đây là ví dụ thứ N trong dự án về "chỉ lộ ra khi chạy
thật quy mô production, không lộ ra khi đọc code/chạy test trên fixture" —
nhưng lần này khác các lần trước (B1/B2/C1) ở chỗ hậu quả tiềm tàng KHÔNG
chỉ là dữ liệu sai trong warehouse, mà là **hành động thật hướng ra ngoài**
(tin nhắn tới điện thoại người dùng). Quy trình "dừng lại — kiểm chứng độc
lập — sửa tận gốc, không chỉ vá triệu chứng" đã hoạt động đúng.

---

## 3. Sửa khác ở final review — rò rỉ giá trị kỹ thuật vào tin nhắn thật (lần thứ 2 cùng lớp lỗi)

`format_message` từng dùng trực tiếp `e['event_title_vi']` — cột này CÓ
THỂ NULL (không có `NOT NULL` trong DDL `raw_corporate_event`, và chính
`stg_corporate_event.sql` tự phòng thủ bằng `coalesce(event_title_vi, '')`
trong logic riêng của nó). Sự kiện NULL title in ra literal `"HPG — None"`
vào tin nhắn thật.

**Đây là lần THỨ HAI trong C2 gặp đúng lớp lỗi này** — lần đầu (Task 1, fix
round 1) là `pandas.NaT` rò rỉ vào cột NGÀY; lần này là `None` rò rỉ vào
cột VĂN BẢN. Cả 2 đều là biến thể của "giá trị NULL từ DuckDB đi qua
pandas rồi in thẳng vào tin nhắn/output mà không qua kiểm NULL đúng cách" —
cùng lớp lỗi mà B2 final review từng đặt tên `data_quality.truncated`
convention, và B1 từng gặp với `"NaT"` string ở tầng đọc.

Đã sửa: fallback `event_title_vi → event_name_vi → placeholder tiếng Việt`.

**Khuyến nghị final review (chưa làm, backlog):** grep toàn bộ điểm
`.df()` → f-string trong `mcp_server/tools.py`/`alert_events.py`, viết 1
hàm `_safe(value, default)` dùng chung cho mọi trường được nội suy vào
văn bản hiển thị — đóng cả LỚP lỗi thay vì từng ca riêng lẻ.

---

## 4. Sửa dọn dẹp phụ: `.superpowers/` chưa từng có trong `.gitignore`

Phát hiện khi merge fix wave: 1 file report của workspace SDD (git-ignored
theo quy ước dự án từ A1 — mọi mảng trước đều `rm -rf` workspace khi đóng
plan) bị lỡ **commit vào lịch sử lần đầu tiên** — kiểm tra `.gitignore`
xác nhận `.superpowers/` chưa từng có dòng nào cho tới giờ. Trước đây
"an toàn" thuần tuý vì chưa agent nào từng chạy `git add` đủ rộng để cuốn
theo thư mục này. Đã gỡ tracking file đó + thêm `.superpowers/` vào
`.gitignore` (commit `2717aa9`).

---

## 5. Nợ nhỏ khác (deferred ở final review, không chặn merge)

| # | Nợ | Vị trí | Ghi chú |
|---|---|---|---|
| 1 | `con.unregister("df_alert")` không nằm trong `finally` | `src/warehouse.py::mark_events_alerted` | Không gây lỗi chức năng (đã kiểm — lần gọi sau tự re-register đè lên), chỉ rò object nhỏ trên nhánh lỗi; giống hệt idiom mọi hàm khác trong file, không phải lỗi riêng của C2 |
| 2 | `INSERT` không có target column list tường minh, dựa thứ tự cột DDL | `src/warehouse.py::mark_events_alerted` | Giống `upsert_prices`, rủi ro thấp |
| 3 | `alerted_at` lưu theo local time (session timezone cast) dù input là UTC tz-aware | `src/warehouse.py::mark_events_alerted` | Cosmetic — không dùng trong logic dedup (khoá là `event_id`), không ảnh hưởng đúng/sai |
| 4 | `notify.send` gửi nhiều chunk (>4000 ký tự) không atomic — lỗi ở chunk 2 để lại chunk 1 đã gửi mà không log | `src/notify.py` (có sẵn từ hệ thống cũ, không sửa ở C2) | Đáng 1 dòng docstring; với 5 mã danh mục, tin hiếm khi vượt 4000 ký tự |
| 5 | `init_warehouse(con)` chạy full DDL/migration mỗi lần `alert_events.py` chạy | `alert_events.py::main` | Idempotent, nhưng job cảnh báo giữ quyền migrate schema nó không cần — có thể tách helper `CREATE TABLE IF NOT EXISTS alert_sent_log` riêng |
| 6 | Portfolio rỗng (`holdings: []`) thoát hoàn toàn im lặng, không print gì | `alert_events.py::main` | Khó phân biệt "ngày yên tĩnh" với "cấu hình sai"; rủi ro thấp vì `portfolio.yml` hiện có 5 mã thật |
| 7 | Spec §5 và §3.3 tự mâu thuẫn (nói sẽ nêu `distribution_type` trong tin nhưng `format_message` không làm) | `docs/superpowers/specs/2026-08-19-c2-canh-bao-su-kien-design.md` | Lỗi ở spec, không phải code — vô hại vì tiêu đề sự kiện đã tự mô tả rõ, tự khắc phục 1 phần khi fix `event_name_vi` fallback được áp dụng |

---

## 6. Sau C2

- Sau khi C2 chạy ổn định vài lần thật (workflow `event-alerts.yml` đã có
  `workflow_dispatch` để chạy tay kiểm trước khi tin tưởng cron), cân nhắc
  TẮT `daily.yml` (quyết định của người dùng, không tự động).
- Nếu khối lượng tin thực tế gây phiền, cân nhắc lọc theo `distribution_type`
  (hiện cố ý báo TẤT CẢ loại sự kiện).
- Đóng lớp lỗi "NULL đi qua pandas rò rỉ vào text hiển thị" một lần cho
  toàn bộ `mcp_server/tools.py`/`alert_events.py` (mục 3 ở trên).
