# C1 — Kết quả nghiệm thu & Nợ kỹ thuật

> Hoàn tất 2026-08-19, merge vào `main` qua PR #7 (`feat/c1-luan-diem-dinh-ky`,
> commit merge `ecba86d`). Tài liệu này giữ lại những gì git log không nói
> được: **vì sao** các quyết định được đưa ra, và **những gì còn nợ**. Nhật
> ký đầy đủ từng task từng nằm ở
> `.superpowers/sdd/2026-08-19-c1-luan-diem-dinh-ky/progress.md` (git-ignored,
> đã xoá sau khi review cuối sạch theo quy trình subagent-driven-development
> — git log là bản ghi chính thức).

---

## 1. Tóm tắt C1

C1 (luận điểm đầu tư định kỳ) hoàn thành qua **2 task** (nhỏ hơn hẳn A/B1/B2
vì không có ingest/bảng/model dbt mới — thuần đọc dữ liệu đã có), cộng 1
vòng final review toàn nhánh (model Opus) và 1 vòng sửa cuối cùng cho 1
Critical + 5 Important.

| Hạng mục | Kết quả |
|---|---|
| Task | 2/2 |
| Tool MCP mới | 1 — `get_thesis_update` (tổng 11/11 tool trả dữ liệu thật) |
| Bảng/model dbt mới | 0 — C1 không ingest, chỉ đọc `mart_stock_scorecard`, `fct_financial_quarterly`, `int_distribution_event`, `raw_financial_statement`, `stg_shareholder`/`stg_officer` |
| pytest sau vòng sửa cuối | 315 passed, 2 xfailed |

Thiết kế cốt lõi: `mart_stock_scorecard` KHÔNG có lịch sử (không diff được
điểm số) — chỉ dùng làm ngữ cảnh hiện tại. Bốn khối còn lại (sự kiện mới,
kỳ BCTC mới ghi nhận, thay đổi sở hữu, xu hướng tài chính) đều dựa vào các
cột timestamp THẬT đã có sẵn (`exright_date`, `ingested_at`, `snapshot_date`,
`period_end_date`) — không cần thêm cơ chế lưu lịch sử nào mới.

---

## 2. Bug nghiêm trọng nhất tìm được ở final review — tái diễn đúng bug đã fix ở B1

`_ownership_change` (viết mới hoàn toàn cho C1, không tái dùng
`int_ownership_snapshot` vì model đó chỉ giữ snapshot MỚI NHẤT, không so
sánh được) ban đầu dùng CHUNG 1 ngày `snapshot_date` (lấy từ
`stg_shareholder`) để lọc CẢ `stg_officer`. Đây chính xác là bug B1 đã phát
hiện và sửa cho `get_ownership` (thêm cột `officer_snapshot_date` riêng vào
`int_ownership_snapshot.sql`, vì `fetch_shareholders`/`fetch_officers` bọc
`except Exception: continue` ĐỘC LẬP theo từng mã — một mã có thể fetch
thành công cổ đông nhưng lỗi officer ở CÙNG lần chạy monthly).

Hậu quả tái hiện được tại final review: nếu officer fetch thất bại ở 1 trong
2 mốc so sánh, `insider_pct` tính ra `0.0` (không phải thiếu dữ liệu thật)
→ tool báo delta âm lớn kiểu "nội bộ đã bán sạch 30% cổ phần" hoàn toàn GIẢ,
kèm `baseline_is_fallback: false` (trông như đáng tin cậy). Đã sửa: tách 2
trục thời gian (`officer_baseline_snapshot_date`/`officer_latest_snapshot_date`
riêng với `baseline_snapshot_date`/`latest_snapshot_date` của cổ đông),
`insider_pct`/`delta` trả `None` khi không có snapshot officer nào, thay vì
`0.0`.

**Bài học ghi lại để không lặp lại lần ba:** bất kỳ chỗ nào tự tính lại phép
gộp sở hữu (thay vì tái dùng `int_ownership_snapshot`) PHẢI xử lý 2 trục
thời gian cổ đông/officer độc lập — đã thêm comment cảnh báo lockstep ở đầu
`transforms/models/intermediate/int_ownership_snapshot.sql` trỏ tới
`mcp_server/tools.py::_ownership_change` cho lần thứ ba.

---

## 3. Nợ đã ghi nhận ở final review, chưa giải quyết triệt để

### 3.1 `new_statement_periods` đo "được ghi lại", không phải "mới công bố"

Thiết kế spec ban đầu giả định `ingested_at` mới trên `raw_financial_statement`
đồng nghĩa "kỳ BCTC mới công bố" — SAI. `INSERT OR REPLACE ... now()` khiến
MỌI lần refetch (kể cả kỳ đã biết từ lâu) đều cập nhật `ingested_at` mới, và
job `weekly` refetch TOÀN BỘ cửa sổ 8 quý × 3 báo cáo cho MỌI mã mỗi tuần.
Hậu quả đo thật: `new_statement_periods` với cửa sổ mặc định 90 ngày trả về
~24-48 dòng cho hầu hết mọi mã (HPG đo thật: 48/48), gần như không phân biệt
được kỳ THẬT SỰ mới với kỳ cũ bị ghi đè lại.

Đã sửa PHẦN DIỄN GIẢI (docstring nói đúng hành vi thật, cảnh báo agent không
kết luận "vừa công bố" chỉ vì 1 kỳ xuất hiện ở đây) — KHÔNG sửa dữ liệu,
vì cần thêm cột (ví dụ `first_seen_at`, giữ nguyên qua các lần `REPLACE`) mới
giải quyết triệt để, một thay đổi schema nằm ngoài phạm vi C1.

**Backlog:** thêm cột `first_seen_at` cho `raw_financial_statement` (chỉ set
1 lần lúc INSERT đầu tiên, giữ nguyên qua các lần `REPLACE` sau — khác
`ingested_at` vốn luôn cập nhật) — cần cho cả C1 lẫn C2 (cảnh báo sự kiện sẽ
gặp đúng vấn đề tương tự khi cần phân biệt "sự kiện mới" khỏi "dữ liệu được
ghi lại").

### 3.2 Lệch NULL-handling nhỏ giữa `_ownership_change` và `int_ownership_snapshot.sql`

`int_ownership_snapshot.sql` tính `top1_pct = max(case when rn=1 then
share_own_percent end)` → `NULL` nếu cổ đông lớn nhất có `share_own_percent`
NULL. `_ownership_change` (sau khi lọc bỏ NULL khỏi danh sách) trả `0.0` cho
cùng tình huống thay vì `NULL`. Chưa chạm được trên dữ liệu production hiện
tại (chưa gặp mã nào có `share_own_percent` NULL ở đúng vị trí top1), đã ghi
vào comment lockstep ở `int_ownership_snapshot.sql` để không bị quên nếu
tình huống này xảy ra thật.

### 3.3 `_financial_trend` chưa có cờ `truncated`

`data_quality.truncated` đã thêm cho `new_distribution_events`/
`new_statement_periods` (fix Important #4 ở final review), nhưng
`_financial_trend` (limit=40, tương đương ~10 năm dữ liệu quý) chưa có cờ
tương tự — nằm ngoài phạm vi 2 khối đã nêu trong finding gốc. Chưa khả thi
chạm trần ở cửa sổ mặc định 90 ngày (`since_date` phải lùi >10 năm mới có
nguy cơ), rủi ro thấp nhưng nên thêm cho nhất quán nếu có dịp sửa
`mcp_server/tools.py` liên quan.

### 3.4 `has_ownership_baseline` chỉ dựa trục cổ đông

`data_quality.has_ownership_baseline` chỉ phản ánh trục thời gian CỔ ĐÔNG,
không tính tới trục OFFICER (có thể lệch nhau sau fix mục 2 ở trên). Không
bịa số (payload vẫn phơi đủ 2 trục `officer_baseline_snapshot_date`/
`latest_snapshot_date` để agent tự đọc), chỉ là khoảng trống về mức độ dễ
đọc — cân nhắc thêm `has_officer_baseline` riêng nếu use case thực tế cần.

---

## 4. Bài học quy trình: cần đối chiếu spec ↔ code ở review cuối, không chỉ plan ↔ code

Cả 2 task review (kiểm code so với PLAN) đều Approved, nhưng final review
phát hiện `get_thesis_update` THIẾU HẲN khối `data_quality` — dù plan Step 24
không có nó, SPEC (`docs/superpowers/specs/2026-08-19-c1-luan-diem-dinh-ky-design.md`
§4.1) đã khai báo rõ hợp đồng trả về PHẢI có `data_quality`. Lỗi này là do
chính người viết plan (không phải implementer) bỏ sót khi dịch spec §4.1
thành các step cụ thể — implementer làm ĐÚNG theo plan, chỉ là plan sai so
với spec.

**Áp dụng cho các mảng sau:** ở bước tự rà soát plan (writing-plans skill),
cần đối chiếu TỪNG trường trong hợp đồng trả về (`§4.1`-style JSON mẫu) của
spec với các step cụ thể trong plan — không chỉ kiểm "mỗi mục spec có 1 task
tương ứng" ở mức tiêu đề, mà kiểm từng field trả về có mặt trong step code
thật hay không.
