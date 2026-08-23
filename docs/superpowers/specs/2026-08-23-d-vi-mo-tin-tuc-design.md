# D — Tỷ giá & kho tin tức

> Thiết kế chốt ngày 2026-08-23. Tiếp nối A/B1/B2/C1/C2 (đã merge vào
> `main`, tổng 11 tool MCP).
>
> Mảng D trong spec gốc (`2026-08-09-fundamental-analysis-platform-design.md`
> §2.2) gồm 2 phần: "dữ liệu vĩ mô (CPI, lãi suất, tỷ giá, tăng trưởng tín
> dụng)" và "kho tin tức & cơ chế scan thị trường". Sau khảo sát thật (§1),
> tài liệu này thu hẹp phạm vi còn **tỷ giá + kho tin tức** — 2 phần DUY
> NHẤT có nguồn dữ liệu miễn phí, hợp lệ khả thi ngay. CPI/lãi suất/tăng
> trưởng tín dụng và "cơ chế scan thị trường" bị loại khỏi phạm vi, lý do
> ghi rõ ở §1.3/§2.

---

## 1. Khảo sát nguồn — đã kiểm tra thật trước khi thiết kế

### 1.1 Tỷ giá — CÓ nguồn miễn phí thật, đã gọi thử thành công

`vnstock.explorer.misc.exchange_rate.vcb_exchange_rate(date)` — gọi thẳng
API export của Vietcombank (`vietcombank.com.vn/api/exchangerates/
exportexcel`), đã có sẵn trong package `vnstock` dự án đang dùng (không
cần thêm dependency). Gọi thật ngày 2026-08-20, xác nhận trả về DataFrame
6 cột (`currency_code, currency_name, buy_cash, buy_transfer, sell, date`)
cho ~20 loại ngoại tệ (USD, EUR, JPY, AUD, CAD, CHF, CNY...). `buy_cash`
đôi khi là `"-"` (không áp dụng cho loại tiền đó) — cần xử lý như
missing-not-wrong (giống `dq.filter_range`), không parse ra 0.

### 1.2 Kho tin tức — nguồn CÓ SẴN, đã dùng trong hệ thống bot cũ

`Company(symbol, source).news()` (`vnstock.api.company`) — hệ thống bot cũ
(`src/ingest.py::fetch_news`) đã dùng nguồn này, nhưng chỉ lấy TẠM THỜI
mỗi lần chạy digest, không LƯU TRỮ lâu dài (chỉ lưu `id` để chống lặp
tin trong `storage.py`, không lưu nội dung). D biến nguồn này thành 1
bảng warehouse thật, tra cứu lại được.

Gọi thật cho HPG, xác nhận: trả về **đúng 50 dòng**, cột `id` không trùng
lặp trong 1 lần gọi. **50 dòng khớp CHÍNH XÁC với cửa sổ trượt đã biết của
`Company.events()` ở B1** (cùng gia đình API `Company`, rất có thể dùng
chung cơ chế phân trang) — dự đoán mạnh đây cũng là cửa sổ TRƯỢT (chỉ trả
tin gần đây nhất, tin cũ rơi khỏi cửa sổ theo thời gian), giống hệt lý do
B1 phải thiết kế `raw_corporate_event` append-only. **CHƯA XÁC MINH** —
xử lý ở Task 1 (cổng chặn), giống mẫu B1 đã dùng cho `id` sự kiện DN.

Cột dùng được: `id` (khoá ổn định), `ticker`, `news_title`, `news_short_content`,
`news_full_content` (thường NULL qua nguồn VCI, không dựa vào), `news_source_link`,
`public_date`.

### 1.3 CPI / lãi suất / tăng trưởng tín dụng — KHÔNG có nguồn miễn phí hợp lệ, loại khỏi phạm vi

Đã khảo sát:
- **`vnstock`**: không có module CPI/lãi suất/tín dụng nào (chỉ có
  `exchange_rate.py`/`gold_price.py` trong `explorer/misc/`, đã kiểm tra
  toàn bộ package bằng grep, không tìm thấy).
- **SBV (`sbv.gov.vn/en/cpi`)**: chỉ có báo cáo văn bản dạng bài viết
  ("Vietnam's CPI increases by 0.20% in October 2025"), KHÔNG có API/file
  tải dữ liệu có cấu trúc (đã tự kiểm tra trang thật).
- **WiFeed (`wifeed.vn`)**: CÓ đúng dữ liệu cần (CPI, CPI Core, lãi suất
  huy động/cho vay theo nhóm ngân hàng, cung tiền, tín dụng) qua API —
  nhưng **TRẢ PHÍ** (quy trình yêu cầu "Thanh toán và lấy API Key"), không
  có gói miễn phí. Đây là quyết định CHI TIÊU THẬT, ngoài thẩm quyền tự
  quyết của phiên làm việc này — để dành cho người dùng tự cân nhắc.

**Quyết định:** không làm CPI/lãi suất/tín dụng ở D. Nếu sau này người
dùng muốn trả phí WiFeed (hoặc tìm được nguồn miễn phí khác), làm task
riêng.

### 1.4 "Cơ chế scan thị trường" — quá mơ hồ để scope chung với ingest dữ liệu, loại khỏi phạm vi

Spec gốc không định nghĩa rõ "scan" là quét theo tiêu chí gì (kỹ thuật?
khối lượng bất thường? tin tức mới?) — khác các mảng trước đều có đặc tả
đủ cụ thể để scope ngay khi brainstorm. Đây là một Q&A/thiết kế RIÊNG,
không phải hệ quả tự nhiên của việc có thêm bảng tỷ giá/tin tức. Để dành
brainstorm sau, độc lập.

---

## 2. Phạm vi

**Trong phạm vi:**

- Bảng warehouse mới `raw_exchange_rate` — tỷ giá VCB hằng ngày.
- Bảng warehouse mới `raw_news` — tin tức đã fetch, lưu trữ lâu dài
  (append-only, giống `raw_corporate_event`).
- Nối vào `build_warehouse.py --mode daily` (cả 2 đều rẻ: tỷ giá 1 lần gọi
  API/ngày cho toàn bộ ngoại tệ; tin tức giới hạn theo watchlist, xem §3.2).
- 2 tool MCP mới: `get_exchange_rate_history`, `get_recent_news`.

**Không làm** (ghi rõ để không hiểu nhầm ở review):

- Không làm CPI/lãi suất/tăng trưởng tín dụng (§1.3 — không có nguồn miễn
  phí hợp lệ).
- Không làm "cơ chế scan thị trường" (§1.4 — cần brainstorm riêng).
- Không đổi hệ thống bot cũ (`main.py`/`digest.py`/`src/ingest.py::fetch_news`/
  `storage.py`) — `raw_news` là bảng MỚI, độc lập, không thay thế cơ chế
  chống lặp tin tạm thời hiện có của bot cũ.
- Không dùng LLM để tóm tắt/phân loại tin tức — lưu nguyên văn, tool trả
  dữ liệu cấu trúc.

---

## 3. Kiến trúc

### 3.1 `raw_exchange_rate`

```sql
CREATE TABLE raw_exchange_rate (
    currency_code   VARCHAR,
    currency_name   VARCHAR,
    buy_cash        DOUBLE,
    buy_transfer    DOUBLE,
    sell            DOUBLE,
    rate_date       DATE,
    ingested_at     TIMESTAMP,
    PRIMARY KEY (currency_code, rate_date)
);
```

`buy_cash`/`buy_transfer`/`sell` = `"-"` từ nguồn → parse thành `NULL`
(không phải `0.0`) — đây là loại tiền KHÔNG có giao dịch tiền mặt cho
Vietcombank ngày đó, không phải tỷ giá bằng 0. Ghi `INSERT OR REPLACE` —
chạy lại cùng ngày thì ghi đè (tỷ giá có thể cập nhật trong ngày), khác
ngày thì tích luỹ.

### 3.2 `raw_news`

```sql
CREATE TABLE raw_news (
    id              VARCHAR PRIMARY KEY,
    symbol          VARCHAR,
    news_title      VARCHAR,
    news_short_content VARCHAR,
    news_source_link VARCHAR,
    public_date     TIMESTAMP,
    ingested_at     TIMESTAMP
);
```

**Append-only** (`INSERT ... WHERE NOT EXISTS`, giống `raw_corporate_event`)
— PHỤ THUỘC kết quả Task 1 (cổng chặn) xác nhận `id` ổn định và cửa sổ
50-tin có trượt theo thời gian hay không (xem §1.2). Nếu Task 1 phát hiện
`id` KHÔNG ổn định giữa các lần gọi, dừng lại, báo controller — không tự
đổi thiết kế (đúng mẫu B1/B2 Task 1).

**Phạm vi mã:** CHỈ 5 mã trong `config/portfolio.yml` (giống C2) — không
mở rộng ra toàn bộ ~1.600 mã. Lý do: tin tức toàn thị trường tốn nhiều lần
gọi API mỗi ngày (~1.600 mã × `_throttle()`) mà giá trị sử dụng thực tế
(tool MCP cho agent hội thoại) chủ yếu phục vụ câu hỏi về mã cụ thể người
dùng quan tâm — mở rộng sau nếu có nhu cầu thật (xem §8).

---

## 4. Nhịp ingest

Cả 2 bảng chạy ở `build_warehouse.py --mode daily` — nhịp hiện tại của
`--mode daily` chỉ có universe refresh + giá EOD (rẻ, không có vòng lặp
`_throttle()` theo mã cho API tốn kém). Thêm tỷ giá (1 lần gọi/ngày) không
đáng kể. Thêm tin tức (5 mã × `_throttle()`) cũng rẻ — ước tính +10-15
giây so với job daily hiện tại, không đáng lo vượt trần CI (khác B2's job
monthly nặng).

---

## 5. Task 1 (cổng chặn) — kiểm chứng `id` tin tức ổn định

Giống hệt cách B1 kiểm `id` sự kiện DN: gọi `Company(symbol, source).news()`
cho vài mã trong portfolio, **hai lần cách nhau ≥60 giây**, đối chiếu:
- Các `id` xuất hiện ở CẢ hai lần gọi có giữ nguyên nội dung không (ổn định).
- Tin MỚI ở lần gọi 2 (nếu có) không làm thay đổi `id` của tin cũ.

**Nếu ổn định:** dùng append-only (`INSERT ... WHERE NOT EXISTS`) như
thiết kế ở §3.2.
**Nếu KHÔNG ổn định:** dừng, báo controller — không tự đổi thiết kế.

---

## 6. Tool MCP

### `get_exchange_rate_history(currency_code: str = "USD", days: int = 30) -> dict`

Chuỗi tỷ giá theo ngày cho 1 loại ngoại tệ, mặc định USD. Trả
`buy_cash`/`buy_transfer`/`sell` theo từng ngày, `data_quality.has_data`
nếu mã ngoại tệ không tồn tại trong `raw_exchange_rate`.

### `get_recent_news(symbol: str, limit: int = 10) -> dict`

Tin tức gần đây nhất đã lưu cho 1 mã (chỉ hoạt động cho 5 mã portfolio —
`data_quality.has_data = false` kèm ghi chú rõ ràng cho mã ngoài phạm vi,
KHÔNG trả lỗi mập mờ). Trả `news_title`, `public_date`, `news_source_link`
theo thứ tự mới nhất trước, cộng `news_short_content` CẮT còn tối đa 300
ký tự (agent có thể mở `news_source_link` nếu cần đọc đầy đủ).

---

## 7. Kiểm thử

| Test | Canh lỗi gì |
|---|---|
| `id` tin tức ổn định giữa 2 lần gọi (Task 1) | Khoá append-only vỡ nếu không kiểm trước |
| `buy_cash = "-"` parse thành `NULL`, không phải `0.0` | Nhầm "không áp dụng" thành "tỷ giá bằng 0" |
| `raw_exchange_rate` ghi `OR REPLACE` đúng theo `(currency_code, rate_date)` | Ghi trùng/ghi đè sai ngày |
| `raw_news` append-only không mất tin cũ khi cửa sổ 50-tin trượt (giả lập 2 lần fetch) | Giống bài học B1 `test_su_kien_cu_khong_bi_mat_khi_cua_so_truot` |
| `raw_news` chỉ fetch đúng 5 mã portfolio | Sai phạm vi, tốn API không cần thiết |
| `get_exchange_rate_history` mã ngoại tệ không tồn tại → `has_data=false`, không lỗi mập mờ | Đúng pattern toàn dự án |
| `get_recent_news` mã ngoài portfolio → `has_data=false` kèm ghi chú | Tránh agent hiểu nhầm "mã không tồn tại" |
| Gọi cả 2 tool qua `mcp.call_tool()` thật | Bài học A3 I1 — crash tầng serialize JSON |
| Fixture khớp đúng schema thật | Bài học A3 I2/B1/B2/C1/C2 |
| Đối chiếu tay ≥1 ngày tỷ giá thật + ≥1 mã tin tức thật trên production | Không dùng dữ liệu tổng hợp thay xác nhận thật |

---

## 8. Rủi ro

| Rủi ro | Mức | Xử lý |
|---|---|---|
| `id` tin tức không ổn định giữa các lần gọi | Chưa biết | Task 1 kiểm trước, chặn |
| VCB đổi cấu trúc API export (breaking change ngoài kiểm soát dự án) | Thấp | `dq.assert_columns` phát hiện sớm, giống pattern toàn dự án |
| Phạm vi 5 mã tin tức có thể quá hẹp nếu người dùng muốn tra cứu mã khác | Thấp, đã biết trade-off | Backlog mở rộng (§9) khi có nhu cầu thật |

---

## 9. Tiêu chí hoàn thành D

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| 1 | `id` tin tức ổn định (Task 1) | Task 1 |
| 2 | Toàn bộ pytest pass, không hỏng test cũ | `pytest tests/ -q` |
| 3 | `raw_exchange_rate`/`raw_news` có dữ liệu thật trên production | Nghiệm thu cuối |
| 4 | 13/13 tool đạt qua `scripts/check_mcp_tools.py` trên production | Nghiệm thu cuối |
| 5 | Đối chiếu tay khớp dữ liệu thật (tỷ giá + tin tức) | Nghiệm thu cuối |
| 6 | Không đổi hành vi 11 tool cũ, không đụng hệ thống bot cũ | Đối chiếu diff |

---

## 10. Sau D

- Mở rộng `raw_news` ra ngoài 5 mã portfolio nếu có nhu cầu thật.
- CPI/lãi suất/tăng trưởng tín dụng — nếu người dùng quyết định trả phí
  WiFeed (hoặc tìm được nguồn miễn phí khác), làm spec riêng.
- "Cơ chế scan thị trường" — brainstorm riêng, làm rõ tiêu chí "bất
  thường" cụ thể là gì trước khi thiết kế.
