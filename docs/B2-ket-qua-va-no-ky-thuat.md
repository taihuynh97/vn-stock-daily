# B2 — Kết quả nghiệm thu & Nợ kỹ thuật

> Hoàn tất 2026-08-18, merge vào `main` qua PR #6 (`feat/b2-bctc-chi-tiet`,
> commit merge `0d4f261`) ngày 2026-08-19. Tài liệu này giữ lại những gì git
> log không nói được: **vì sao** các quyết định được đưa ra, và **những gì
> còn nợ**. Nhật ký đầy đủ từng task từng nằm ở
> `.superpowers/sdd/2026-08-17-b2-bctc-chi-tiet/progress.md` (git-ignored,
> đã xoá sau khi review cuối sạch theo quy trình subagent-driven-development
> — git log là bản ghi chính thức).

---

## 1. Tóm tắt B2

B2 (chi tiết BCTC — income_statement/balance_sheet/cash_flow) hoàn thành qua
**5 task** theo TDD từng bước, cộng 1 vòng final review toàn nhánh (model
Opus, đọc toàn bộ diff + tự kiểm chứng bằng test/API sống, không chỉ tin
report) và 1 vòng sửa cuối cùng cho 1 Critical + 5 Important.

| Hạng mục | Kết quả |
|---|---|
| Task | 5/5, TDD từng bước (Task 1 là cổng chặn kiểm vị trí dòng ổn định) |
| Tool MCP mới | 1 — `get_financial_statement` (tổng 10/10 tool trả dữ liệu thật) |
| Bảng raw mới | 1 — `raw_financial_statement`, khoá `(symbol, statement_type, period_type, period_label, row_seq)` |
| Quy mô bảng (đo trên `md:vn_market` sau backfill đầu) | quarter **1,88 triệu dòng** · year **2,25 triệu dòng** |
| pytest sau vòng sửa cuối | 287 passed, 2 xfailed |

`row_seq` (vị trí dòng, 0-based, gán lập trình từ `reset_index()`) được dùng
làm một phần khoá THAY CHO `item_id` vì `item_id` không unique trong một báo
cáo — đã đo thật: `balance_sheet` của HPG có 22/122 dòng trùng `item_id`
(ví dụ `'cost'` xuất hiện 4 lần vì 4 nhóm tài sản cố định khác nhau dùng
chung `item_id`, chỉ `item_vi`/vị trí dòng phân biệt được). Task 1 xác nhận
vị trí dòng ổn định giữa các lần gọi API thật (≥60s, trộn cả 3 `com_class`)
trước khi thiết kế này được dùng làm khoá lưu trữ.

Ghi theo `INSERT OR REPLACE` (không phải append-only như
`raw_corporate_event` của B1) — vì đơn vị ghi là từng Ô `(period_label,
row_seq)` có khoá riêng, khác với sự kiện DN nơi đơn vị trùng lặp là toàn bộ
sự kiện. Cửa sổ 8-kỳ API trả về vẫn trượt theo thời gian, nhưng khoá đủ mịn
nên ghi đè không bao giờ xoá mất kỳ cũ hơn cửa sổ hiện tại.

---

## 2. CRITICAL (đã giảm nhẹ, CHƯA giải quyết triệt để) — job `--mode monthly` có thể vượt trần 360 phút của GitHub Actions

**Bối cảnh:** GitHub-hosted runner có trần cứng **360 phút (6 giờ) cho MỖI
LẦN chạy 1 job** (không phải quota theo tháng — đây là per-job execution
ceiling, áp dụng riêng cho từng lần cron fire). Nghiệm thu Task 5 đo thật:
`build_warehouse.py --mode monthly` (đã gồm BCTC quarter+year cho B2) mất
**767 phút** — vượt xa trần 360 phút.

**Đã sửa ở vòng review cuối (commit `b561647`), 4 điểm — thu hẹp HẬU QUẢ,
không thu hẹp NGUYÊN NHÂN:**

1. Đảo thứ tự trong `build_warehouse.py`: khối BCTC (chậm nhất, mới thêm)
   giờ chạy SAU khối dim_industry/company_info/shareholders/officers (đã có
   từ B1 trở về trước) — nếu job bị GitHub giết giữa chừng, các bước cũ
   không còn bị B2 chặn mất (trước đây thứ tự ngược lại, đây từng là một
   regression thật do B2 gây ra cho chức năng đã merge).
2. Ghi theo lô 100 mã/lần (`_ingest_statements_chunked` trong
   `build_warehouse.py`) thay vì gom hết ~1.600 mã rồi ghi 1 lần ở cuối —
   nếu bị giết giữa chừng, các lô đã xử lý xong vẫn được ghi thật (nhờ
   `INSERT OR REPLACE`), không mất trắng; lần chạy tháng sau tự nối tiếp
   đúng phần còn thiếu.
3. Bỏ qua fetch lại `period=year` cho mã đã có dữ liệu year với
   `ingested_at` trong vòng 300 ngày gần đây (`_symbols_need_year_fetch`) —
   giảm đáng kể thời lượng các lần chạy TỪ THÁNG THỨ HAI TRỞ ĐI (lần backfill
   đầu không được lợi gì vì chưa có dữ liệu để bỏ qua).
4. Thêm `timeout-minutes: 350` cho cả `warehouse-monthly.yml` lẫn
   `warehouse-weekly.yml` — để job fail RÕ RÀNG (log lỗi timeout) thay vì bị
   GitHub âm thầm giết đúng lúc 360 phút không cảnh báo.

**CHƯA giải quyết — backlog cần làm sau:**

Bốn fix trên đảm bảo job **an toàn khi bị cắt** (không mất dữ liệu, không
chặn chức năng cũ đã merge), nhưng **KHÔNG đảm bảo job chạy xong dưới 360
phút**. Lần chạy thật tiếp theo (dự kiến ngày 1 hàng tháng) vẫn có khả năng
bị cắt giữa chừng — nếu vậy, các bước `Đối chiếu chéo warehouse`/`dbt
build`/`dbt source freshness` (chạy SAU bước ingest trong CÙNG 1 CI job,
xem `.github/workflows/warehouse-monthly.yml`) sẽ KHÔNG chạy được tháng đó.
Dữ liệu BCTC không mất, nhưng lớp dbt/reconcile bị bỏ lỡ 1 kỳ.

**Hướng giải quyết triệt để (chưa làm, để dành task riêng):**

- Tách bước fetch BCTC ra một workflow GitHub Actions riêng, không chung
  job với `dbt build`/reconcile — mỗi workflow có ngân sách 360 phút riêng.
- Sharding theo mã (chia ~1.600 mã thành N phần, N workflow con hoặc N lần
  cron trong tháng) để mỗi lần chạy nhỏ hơn hẳn 360 phút, có dư nhiều.
- Cân nhắc self-hosted runner (không bị trần 360 phút) nếu 2 hướng trên vẫn
  không đủ.
- **Mục kiểm sau lần chạy monthly kế tiếp (ngày 1 hàng tháng):** kiểm
  workflow `warehouse-monthly` trên GitHub Actions có hoàn tất hay bị
  timeout; nếu bị timeout, đo lại thời lượng thật SAU 4 fix trên để biết
  còn thiếu bao nhiêu % mới về dưới 350 phút, làm căn cứ chọn hướng sharding
  cụ thể (chia đôi? chia 3? theo `com_class`? theo alphabet?).

---

## 3. Nợ chất lượng dữ liệu phát hiện qua B2 — coverage quarter thấp hơn year là ĐẶC TÍNH NGUỒN, không phải lỗi

Nghiệm thu Task 5 ban đầu đo: `period_type='quarter'` phủ 1.284/1.600 mã
(80,25%) trong khi `period_type='year'` phủ 1.564/1.600 mã (97,75%) — chênh
lệch ~280 mã. Báo cáo gốc suy đoán nguyên nhân là cụm mã bị lỗi
`RetryError[ValueError]` (BPW, DKH, DPD, HGA, HGC, IPH, MXC, PYU, TAC, ...).

**Final review đã chứng minh suy đoán này SAI** (gọi trực tiếp API thật):
cụm mã `RetryError` đó lỗi GIỐNG HỆT NHAU ở CẢ HAI `period_type` (0 dòng cho
cả quarter lẫn year), nên không thể là nguyên nhân của một chênh lệch CHỈ
xảy ra ở quarter. Vòng sửa cuối đã điều tra lại đúng cách (không đoán):

- Liệt kê mã có dữ liệu `year` nhưng KHÔNG có `quarter` → đúng **284 mã**,
  khớp gần như chính xác khoảng cách 280 (1.564 − 1.284).
- Lấy mẫu ngẫu nhiên 15 mã trong nhóm đó, gọi trực tiếp
  `Finance(symbol, "VCI", "quarter").income_statement()` — cả 15 mã trả về
  **DataFrame rỗng, KHÔNG exception** (khác hẳn `RetryError`), trong khi
  `period="year"` cho cùng mã trả về 25 dòng thật.

**Kết luận thật:** VCI công bố BCTC năm nhưng KHÔNG công bố BCTC quý cho một
nhóm mã (nhiều khả năng vốn hoá siêu nhỏ trên UPCoM, không bị bắt buộc công
bố theo quý). Đây là đặc tính/giới hạn dữ liệu nguồn, **không phải lỗi code
B2** — cách đọc đúng con số là **1.284/1.288 mã có BCTC quý** trong nhóm mã
VCI THỰC SỰ công bố quý, không phải "thiếu 20% so với 1.600 mã".

**Không cần sửa gì** — `data_quality.has_data=false` của tool
`get_financial_statement` đã phản ánh đúng tình trạng này cho từng
`(symbol, statement_type, period_type)`. Ghi lại ở đây để không ai nhầm lẫn
điều tra lại từ đầu nếu thấy con số coverage lệch nhau giữa 2 `period_type`
ở các lần build sau.

---

## 4. Nợ nhỏ khác (deferred ở final review, không chặn merge)

| # | Nợ | Vị trí | Ghi chú |
|---|---|---|---|
| 1 | `n_periods` (tham số tool `get_financial_statement`) không có trần trên | `mcp_server/tools.py` | An toàn hiện tại (bảng mới có ≤10 kỳ), nên thêm `min(n_periods, X)` khi bảng tích luỹ vượt ~20 kỳ (~5 năm dữ liệu quarter) |
| 2 | `dq.status_for` tính ngưỡng degraded theo TỪNG lô 100 mã (sau fix chunked-upsert) thay vì cả batch ~1.600 mã | `src/ingest_market.py` | Nhạy hơn trước (1 lô lỗi cục bộ có thể abort sớm hơn) — nhưng fail loud (lô trước vẫn giữ nguyên), không silent; production thật ghi nhận 0 `rejected` nên rủi ro thấp |
| 3 | `isinstance(n_periods, int)` chấp nhận `bool` (`n_periods=True` → hiểu ngầm là `n_periods=1`) | `mcp_server/tools.py` | Cosmetic, MCP schema có kiểu riêng nên rủi ro thực tế thấp |
| 4 | Year-gate khi TOÀN BỘ mã đã có dữ liệu gần đây (bỏ qua hết) log `status="empty"` — giống hệt trạng thái lỗi thật | `build_warehouse.py` | `notes` phân biệt được (`"đã bỏ qua N/1600 mã"`) nhưng không tự rõ chỉ qua `status` |
| 5 | `data_quality.truncated` vắng mặt ở nhánh trả về `has_data=false`/`error` (chỉ có ở nhánh thành công) | `mcp_server/tools.py` | Không sai, chỉ không nhất quán shape giữa 3 nhánh trả về |
| 6 | `raw_financial_statement` chưa được `scripts/reconcile_warehouse.py` kiểm tra | `scripts/reconcile_warehouse.py` | Một `count(distinct symbol)` theo `period_type` ở đây sẽ tự động phát hiện các chênh lệch coverage như mục 3 ở trên, thay vì phải điều tra tay |

---

> Bài học chung của B2: cả finding Critical (trần CI 360 phút) lẫn finding
> chất lượng dữ liệu (coverage quarter/year) đều chỉ lộ ra khi **chạy thật
> quy mô đầy đủ trên production** (767 phút, ~1.600 mã) — không lộ ra khi
> đọc code, chạy pytest trên fixture, hay review từng task riêng lẻ. Giống
> bài học B1 (2 lỗi Important nghiêm trọng nhất chỉ lộ ra khi query dữ liệu
> production thật), việc plan B2 dành hẳn Task 5 làm nghiệm thu đầu-cuối
> trên dữ liệu thật — thay vì coi 4 task đầu (đã pass hết unit test) là đủ —
> là điều trực tiếp giúp bắt được cả 2 vấn đề này trước khi merge.
