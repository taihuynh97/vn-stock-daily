# C2 — Cảnh báo theo sự kiện

> Thiết kế chốt ngày 2026-08-19. Tiếp nối C1 (đã merge — tool
> `get_thesis_update`, báo cáo luận điểm định kỳ theo yêu cầu).
>
> Mảng C trong spec gốc (`2026-08-09-fundamental-analysis-platform-design.md`
> §2.2) gồm 2 phần: "báo cáo luận điểm đầu tư định kỳ" (= C1, xong) và
> "cảnh báo theo sự kiện, thay bản tin hằng ngày" (= C2, tài liệu này).

---

## 1. Bối cảnh & khảo sát

### 1.1 Hệ thống bot cũ (`main.py`/`digest.py`/`notify.py`/`storage.py`/`daily.yml`)

Vẫn đang chạy hằng ngày (`daily.yml`, cron 09:00 UTC), đọc `config/portfolio.yml`
(**5 mã: HPG, IDV, MLS, PHP, VNR**), sinh bản tin qua Claude API
(`digest.py`), gửi Telegram (`notify.py`), chống lặp tin tức bằng SQLite
CỤC BỘ (`storage.py`, bảng `seen_news`) — file docstring tự nhận đây là
**"best-effort"**, vì `data/market.db` chỉ được khôi phục qua
`actions/cache` (key `market-db-${{ github.run_id }}`, có thể bị evict/mất).

`notify.send(text: str)` (23 dòng, `src/notify.py`) là hàm gửi Telegram đơn
giản, tự chia nhỏ tin >4000 ký tự — TÁI DÙNG ĐƯỢC nguyên vẹn cho C2, không
cần viết lại.

### 1.2 Nguồn trigger: `stg_corporate_event` (B1, đã có sẵn)

Đã phân loại 2 tầng, fail-closed (đọc `transforms/models/staging/
stg_corporate_event.sql`): `distribution_type` ∈ {CASH_DIVIDEND,
STOCK_DIVIDEND, BONUS_SHARE, ESOP, PRIVATE_PLACEMENT, ISS_KHAC,
INSIDER_TRADING, SHAREHOLDER_MEETING, OTHER, UNKNOWN_CODE}. Cột dùng được
cho cảnh báo: `id` (khoá ổn định, PRIMARY KEY của `raw_corporate_event`),
`symbol`, `event_title_vi` (tiếng Việt, sẵn sàng hiển thị), `exright_date`/
`record_date`/`payout_date`/`public_date`, `ingested_at`.

Không cần ingest gì mới — B1 đã fetch sự kiện DN cho MỌI mã (không riêng
portfolio) ở cả `--mode weekly` lẫn `--mode monthly`.

### 1.3 Vì sao KHÔNG dùng SQLite cục bộ cho C2

Đã cân nhắc tái dùng `storage.py`, nhưng cơ chế cache-based của nó tự nhận
là best-effort — cache bị evict (GitHub xoá cache cũ theo LRU khi vượt giới
hạn dung lượng repo) sẽ khiến C2 GỬI LẠI toàn bộ sự kiện cũ, đúng lỗi mà C2
được sinh ra để tránh (bản tin cũ gửi lặp). → C2 dùng **MotherDuck** (durable,
đã có sẵn cho mọi state khác của nền tảng mới) làm nơi chống lặp tin, không
đụng `data/market.db`.

---

## 2. Phạm vi

**Trong phạm vi:**

- 1 bảng warehouse mới: `alert_sent_log` (chống lặp tin, khoá `event_id`).
- 1 script mới: `alert_events.py` — kiểm sự kiện mới cho 5 mã portfolio, gửi
  Telegram nếu có, ghi log đã gửi.
- 1 workflow GitHub Actions mới: chạy hằng ngày (giờ tương tự `daily.yml`),
  đọc `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (secret đã có sẵn) +
  `WAREHOUSE_DB=md:vn_market`.
- Cơ chế "seed lần đầu": lần chạy ĐẦU TIÊN không gửi gì, chỉ đánh dấu toàn
  bộ sự kiện HIỆN CÓ của 5 mã portfolio là "đã biết" — tránh dội hàng chục
  sự kiện lịch sử vào Telegram ngay khi bật tính năng.

**Không làm** (ghi rõ để không hiểu nhầm ở review):

- **KHÔNG tắt/sửa `daily.yml`, `main.py`, `digest.py`, `signals.py`,
  `screener.py`, `storage.py`** — xây dựng SONG SONG, không thay thế. Việc
  có tắt bản tin hằng ngày cũ hay không là quyết định của người dùng, cần
  xác nhận trực tiếp SAU khi thấy C2 chạy ổn qua ít nhất vài lần thật —
  KHÔNG tự động tắt trong phạm vi C2.
- Không lọc theo `distribution_type` — báo TẤT CẢ sự kiện (danh mục chỉ 5
  mã nên khối lượng tin vốn đã nhỏ; lọc thiếu 1 loại quan trọng rủi ro hơn
  báo dư).
- Không mở rộng ra ngoài 5 mã portfolio (không phải toàn bộ ~1.600 mã).
- Không gọi LLM để viết lại tin — tin sự kiện DN là dữ kiện ngắn
  (`event_title_vi` đã tiếng Việt sẵn), không cần AI tổng hợp như C1.
- Không đổi `notify.py`/`src/warehouse.py`'s DDL của bảng khác — chỉ THÊM
  bảng mới.

---

## 3. Kiến trúc

```
alert_events.py (mới, chạy hằng ngày, workflow riêng)
  đọc config/portfolio.yml -> 5 mã
  query stg_corporate_event WHERE symbol IN (...) AND id NOT IN (SELECT event_id FROM alert_sent_log)
  RỖNG lần đầu (alert_sent_log chưa có dòng nào cho 5 mã này)?
    -> seed: ghi TẤT CẢ sự kiện hiện có vào alert_sent_log, KHÔNG gửi Telegram, thoát
  CÓ sự kiện mới (không phải lần đầu)?
    -> format tin, notify.send(text), ghi các event_id vừa gửi vào alert_sent_log
  KHÔNG có gì mới -> im lặng, không gửi tin "không có gì mới"
```

### 3.1 Bảng `alert_sent_log`

```sql
CREATE TABLE IF NOT EXISTS alert_sent_log (
    event_id    VARCHAR PRIMARY KEY,
    symbol      VARCHAR,
    alerted_at  TIMESTAMP
);
```

`event_id` = `stg_corporate_event.id` (chuỗi ổn định, đã dùng làm PRIMARY
KEY của `raw_corporate_event` từ B1). `INSERT` đơn giản (không cần `OR
REPLACE` — mỗi `event_id` chỉ ghi đúng 1 lần, ghi lại lần 2 là lỗi logic
cần biết, không phải ghi đè hợp lệ).

### 3.2 Phân biệt "lần đầu" (seed) và "có sự kiện mới thật"

"Lần đầu" = `SELECT count(*) FROM alert_sent_log WHERE symbol IN (5 mã)` = 0.
Đây là điều kiện ĐỦ và CHÍNH XÁC (không dựa vào timestamp/ngày — không có
rủi ro "chạy 2 lần trong ngày đầu tiên vẫn tính là lần đầu cả 2 lần", vì sau
lần seed đầu tiên bảng đã có dòng, lần chạy thứ 2 trong cùng ngày sẽ đi
đúng nhánh "kiểm sự kiện mới" như bình thường — nếu không có gì mới thì im
lặng, đúng hành vi mong muốn).

### 3.3 Định dạng tin nhắn

Văn bản thuần (giống `notify.py` đang gửi), không markdown (Telegram
`sendMessage` không bật `parse_mode` trong `notify.py` hiện tại — giữ
nguyên, không đổi).

```
📅 Sự kiện DN mới (2026-08-19):

HPG — Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND
  GDKHQ: 2026-05-11

VNR — Đại hội cổ đông thường niên 2026
  Ngày công bố: 2026-04-01
```

Không nêu khuyến nghị mua/bán — giữ đúng nguyên tắc đã ghi trong
`digest.py`/`mcp_server/instructions.md` xuyên suốt dự án.

---

## 4. Kiểm thử

| Test | Canh lỗi gì |
|---|---|
| Lần đầu (bảng `alert_sent_log` rỗng cho 5 mã) → seed toàn bộ, KHÔNG gọi `notify.send` | Dội tin cũ khi mới bật tính năng |
| Có sự kiện mới thật (đã seed trước đó) → gọi `notify.send` đúng 1 lần, ghi đúng `event_id` vào log | Logic dedup/gửi tin sai |
| Không có gì mới → KHÔNG gọi `notify.send` | Tin "không có gì mới" gây phiền |
| Chạy lại lần 2 với CÙNG dữ liệu (event đã gửi ở lần 1) → không gửi lặp | Đúng mục đích cốt lõi của C2 |
| Chỉ lấy sự kiện của 5 mã portfolio, mã khác không lọt vào | Sai điều kiện `WHERE symbol IN (...)` |
| `notify.send` bị mock trong test — KHÔNG gọi Telegram thật khi chạy `pytest` | An toàn CI, không gửi tin giả vào chat thật |
| Định dạng tin đúng — không có markdown, đúng cấu trúc | Test snapshot nội dung |

---

## 5. Rủi ro

| Rủi ro | Mức | Xử lý |
|---|---|---|
| `alert_sent_log` bị mất do lỗi thao tác | Thấp | MotherDuck bền hơn SQLite/cache-CI, nhưng nếu thật sự mất, hậu quả tệ nhất là dội lại tin cũ 1 lần — không phải mất dữ liệu vĩnh viễn (dữ liệu gốc `raw_corporate_event` không đụng tới) |
| Sự kiện DN chỉ cập nhật theo nhịp `weekly`/`monthly` của `build_warehouse.py`, nhưng `alert_events.py` chạy hằng ngày | Thấp, chấp nhận được | Phần lớn ngày sẽ im lặng (không có gì mới) — không lãng phí đáng kể, và đảm bảo phát hiện sự kiện sớm nhất có thể sau khi warehouse cập nhật |
| Không lọc `distribution_type` có thể báo cả sự kiện ít quan trọng (`OTHER`/`UNKNOWN_CODE`) | Thấp | Danh mục nhỏ (5 mã), khối lượng tin vốn đã thấp; nêu rõ loại sự kiện trong tin để người đọc tự đánh giá |

---

## 6. Tiêu chí hoàn thành C2

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| 1 | Toàn bộ pytest pass, không hỏng test cũ | `pytest tests/ -q` |
| 2 | Lần chạy đầu tiên trên production KHÔNG gửi Telegram, chỉ seed | Nghiệm thu cuối, kiểm `alert_sent_log` có dòng nhưng Telegram không nhận tin |
| 3 | `daily.yml`/`main.py`/`digest.py`/`storage.py` không bị đụng | Đối chiếu diff |
| 4 | Workflow mới chạy được thủ công (`workflow_dispatch`) trên GitHub Actions | Nghiệm thu cuối |
| 5 | Chạy `alert_events.py` 2 lần liên tiếp trên production thật (thủ công, không qua cron) → lần 2 không gửi gì (không có sự kiện mới giữa 2 lần chạy sát nhau) | Nghiệm thu cuối |

---

## 7. Sau C2

- Sau khi C2 chạy ổn định vài lần thật, cân nhắc TẮT `daily.yml` (quyết
  định của người dùng, không tự động).
- Lọc theo `distribution_type` nếu khối lượng tin thực tế gây phiền.
- Mở rộng nguồn portfolio ra ngoài `config/portfolio.yml` nếu người dùng
  muốn theo dõi thêm mã ngoài danh mục nắm giữ.
