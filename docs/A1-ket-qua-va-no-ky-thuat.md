# A1 — Kết quả nghiệm thu & Nợ kỹ thuật bàn giao cho A2

> Hoàn tất 2026-08-11. Tài liệu này giữ lại những gì git log không nói được:
> **vì sao** các quyết định được đưa ra, và **những gì còn nợ**.
> Nhật ký đầy đủ nằm ở `.superpowers/sdd/2026-08-09-a1-nen-du-lieu-co-ban/progress.md`
> (git-ignored, chỉ có trên máy local).

---

## 1. Nghiệm thu — 9/9 đạt

| # | Tiêu chí | Kết quả |
|---|---|---|
| 1 | Test pytest | 115 pass, 0 warning |
| 2 | `raw_financial_ratio` | 50 cột · 1.585 mã · 48.103 dòng |
| 3 | **Ngân hàng có NIM+NPL+CIR** | **27/27** |
| 4 | `raw_company_info` | `exchange` 99,8% · `icb_code_lv2` 100% |
| 5 | `dim_symbols.exchange` | 99,2% (1.586/1.598) |
| 6 | `dim_industry` | 177 dòng · 4 cấp |
| 7 | Chỉ số | 3 mã × 2.617 phiên · VNINDEX max 1.927,94 (< 5.000) |
| 8 | `reconcile_warehouse` | Tất cả đạt, exit 0 |
| 9 | Pipeline bản tin cũ | Nguyên vẹn |

Tiêu chí #3 là phép thử quyết định của cả thiết kế. Trước A1: **0** ngân hàng có chỉ tiêu riêng, và 187/187 dòng ngân hàng mang sentinel giả `0.0`.

---

## 2. Năm phát hiện về dữ liệu nguồn mà thiết kế ban đầu đã sai

Ghi lại vì A2 sẽ gặp lại cùng loại rủi ro: **giả định về dữ liệu nguồn phải được kiểm bằng lời gọi API thật, không suy từ tài liệu.**

| # | Giả định ban đầu | Sự thật |
|---|---|---|
| 1 | `com_group_code` trả `HOSE`/`HNX`/`UPCOM` | Trả **tên chỉ số**: `VNINDEX` / `HNXIndex` / `UpcomIndex` |
| 2 | Chỉ có 3 nơi giao dịch | Có **giá trị thứ tư `OTC`** — 185 mã |
| 3 | `Company.overview()` có cột `industry_icb`, `exchange` | Không có. Cột thật là `icb_code_lv2`, `icb_code_lv4`, `com_group_code` |
| 4 | Bảng backup sau `rename` giữ schema cũ 13 cột | Có đủ **50 cột** — vì `init_warehouse()` chạy trước khi dispatch step |
| 5 | Dữ liệu quá khứ là bất biến | VCI **rút lại** kỳ 2026 Q1 của 351 mã. Backup giữ dữ liệu API không còn phục vụ |

Phát hiện #5 là lý do bảng `raw_financial_ratio_v1_backup` được **giữ vĩnh viễn**, không xoá.

Và một phát hiện tích cực: `com_type_code` phân loại trực tiếp `CT`/`NH`/`BH`/`CK` — nguồn `com_class` sạch hơn hẳn cách suy từ `sector`. A2 đã được cập nhật để dùng trường này.

---

## 3. Nợ kỹ thuật — A2 phải biết trước khi bắt đầu

### Ưu tiên cao — ảnh hưởng trực tiếp tính đúng đắn của A2

**N1. `dim_symbols.is_active` không bao giờ được đặt `FALSE`.**
Không có chỗ nào trong repo set `is_active = FALSE`. Mã từng xuất hiện một lần sẽ mãi mãi `TRUE`. Hệ quả: mẫu số của **mọi** ngưỡng 95% trong `reconcile_warehouse` phình vĩnh viễn trong khi tử số không thể tăng → CI sẽ đỏ vào một thời điểm nào đó vì lý do không liên quan tới chất lượng dữ liệu. Sửa: deactivate mã vắng mặt trong universe mới, **kèm sàn an toàn** (chỉ deactivate nếu universe mới ≥ 90% universe cũ) để một lần `refresh_universe` lỗi không xoá sổ cả thị trường.

**N2. Ngân hàng thiếu hồ sơ sẽ bị phân loại nhầm thành `NONFIN`.**
A2 dự định dùng `coalesce(c.com_class, 'NONFIN')`. Một ngân hàng thiếu dòng trong `raw_company_info` sẽ giữ nguyên cụm sentinel `0.0` của nhóm NONFIN như **giá trị thật** (`roic=0`, `current_ratio=0`) và bị chấm điểm chất lượng bét bảng. Test `assert_no_bank_sentinel_leak` **không bắt được** vì nó lọc `where com_class='BANK'` — mã bị phân loại nhầm đã trượt khỏi phạm vi test.
→ **Khuyến nghị: đổi thành `'UNKNOWN'` và loại khỏi mọi rổ percentile**, cộng một dbt test đếm mã có tỷ số nhưng thiếu company_info.

**N3. `raw_price_daily` và `raw_index_daily` bất đồng về tập ngày giao dịch.**
`is_trading_day()` chỉ loại T7/CN, **chưa có lịch nghỉ lễ VN**. Job daily sẽ ghi dòng "ma" vào `raw_price_daily` mỗi dịp lễ (đã từng xảy ra — xem `scripts/fix_phantom_sunday.py`), trong khi `raw_index_daily` miễn nhiễm vì lấy từ `Quote.history`. A2 join giá với chỉ số để tính beta sẽ gặp ngày lệch.
→ **Lời giải rẻ nhất, A1 vừa tạo ra vật liệu:** fetch VNINDEX trước; nếu không trả dòng nào cho `run_date` thì đó là ngày nghỉ → bỏ qua `fetch_eod_prices`. Không cần bảng lịch lễ.

**N4. `config/warehouse.yml: exchanges` chưa từng có tác dụng.**
Vì `Listing.all_symbols()` không trả cột sàn, khối lọc theo sàn không bao giờ chạy → universe gồm **cả UPCOM** (1.598 mã thay vì ~750). Comment trong file đã được sửa cho trung thực. A2 dùng universe này làm rổ tính percentile — cần quyết định có lọc hay không.

### Ưu tiên trung bình

**N5. `dq.status_for` và `etl_load_log.rows_rejected` gần như là code chết.** Chỉ `fetch_financials`/`fetch_company_info` dùng ngưỡng; các job khác vẫn ghi `"ok" if n else "empty"` thủ công, nên `status='degraded'` hiếm khi xuất hiện. A2 sẽ muốn dùng `etl_load_log` để quyết định "dữ liệu hôm nay có dùng được không" — tín hiệu đó chưa đủ mạnh.

**N6. `VNSTOCK_MIN_INTERVAL` và API key không ràng buộc nhau.** Nếu key trống/hết hạn mà biến vẫn đặt `1.05`, job chạy ~57 req/phút trong khi bậc Guest chỉ cho 20 → vượt hạn mức, biểu hiện là exception rải rác bị nuốt và warehouse thiếu dữ liệu im lặng. Nên suy nhịp từ sự hiện diện của key.

**N7. Script nạp dữ liệu không có timeout và không có checkpoint.**
`fetch_company_info` gom toàn bộ 1.598 mã trong bộ nhớ rồi mới upsert **một lần** ở cuối. Thực tế đã xảy ra: một job treo 5,5 giờ vì DNS chập chờn, và giết nó mất trắng toàn bộ tiến độ. Cũng vì không in tiến độ khi thành công, **không phân biệt được "đang chạy ngon" với "đã treo"** — phải so CPU time mới biết.
→ Sửa: upsert theo lô · timeout cho từng lời gọi · giới hạn số lần retry · in `đã xong X/N mã` sau mỗi lô.

### Ưu tiên thấp

- **N8.** `docs/DESIGN.md` §5.1 lỗi thời: vẫn ghi `raw_financial_ratio (symbol, period, period_type, ...)` và `raw_company_info.industry_icb`. **A2 đọc file này để viết `sources.yml` sẽ viết sai.**
- **N9.** Cột `industry_icb` mồ côi còn sót trên `raw_company_info` production (NULL 100%) — `_ensure_columns` chỉ thêm chứ không xoá. Dọn bằng `ALTER TABLE ... DROP COLUMN`.
- **N10.** `upsert_prices` là lệnh INSERT duy nhất khớp theo **vị trí** thay vì liệt kê cột. Nếu `raw_price_daily` được thêm cột (A2 có thể muốn `adjusted_close`), lỗi sẽ là ghi lệch cột im lặng.
- **N11.** `upsert_financial_ratios` trả `len(df)` chứ không phải số dòng thật sự ghi được — khi df có trùng khoá, `etl_load_log.rows_loaded` nói dối.
- **N12.** `_ensure_columns` không phát hiện được **lệch kiểu**: nếu bảng có sẵn cột cùng tên khác kiểu, nó giữ nguyên kiểu cũ và `INSERT` ép kiểu âm thầm.

---

## 4. Bài học quy trình

**Review từng task không thấy được lỗi tương tác.** Cả 8 task đều sạch khi xét riêng, nhưng final review toàn nhánh tìm ra 2 lỗi Critical sinh ra từ *tương tác giữa các task* — không nằm trong diff của bất kỳ task nào:

- Job `daily` xoá trắng `dim_symbols.exchange` mà job `monthly` vừa điền (`upsert_symbols` ghi đè vô điều kiện, còn `refresh_universe` luôn gán `None`).
- `_normalize_*` nằm ngoài `try` → một mã bất thường xoá sổ cả mẻ 1.598 mã.

→ **Với mỗi hàm ghi DB mới, hỏi thêm: "job nào khác ghi vào cùng cột này, ở cadence nào?"**

**Cổng kiểm chứng cũng cần được kiểm chứng.** `check_against_source` so `pe` giữa warehouse và API — nhưng `pe` tỷ lệ với `market_cap`, mà `market_cap` tính từ giá thị trường hiện tại. Kỳ đã khớp mà vẫn lệch 1,27–7,41%. Một cổng báo động sai liên tục thì tệ hơn không có cổng, vì người ta học cách bỏ qua nó. Đã sửa: chỉ so `roe`/`roa`.

**Đặt cổng gác ngay sau bước nạp thì nó chỉ đo được trạng thái tốt nhất.** `reconcile_warehouse` chạy ngay sau `--mode monthly` trong cùng workflow, nên nó **về mặt cấu trúc** không bao giờ phát hiện được việc job daily xoá cột vào hôm sau. Nên tách thành workflow độc lập.
