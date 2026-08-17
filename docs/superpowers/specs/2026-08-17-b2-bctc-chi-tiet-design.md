# B2 — BCTC chi tiết (income_statement / balance_sheet / cash_flow)

> Thiết kế chốt ngày 2026-08-17. Tiếp nối mảng A (đã merge) và B1 — sự kiện DN,
> phân phối & cơ cấu sở hữu (đã review xong, đang chờ merge do GitHub gặp sự
> cố tạm thời).
>
> Mảng B trong spec gốc (`2026-08-09-fundamental-analysis-platform-design.md`
> §2.2) gồm bốn hạng mục: BCTC chi tiết · sự kiện DN & cổ tức · khối ngoại ·
> cơ cấu cổ đông. B1 đã làm ba hạng mục sau (khối ngoại bị loại vì không có
> nguồn). Tài liệu này đặc tả **B2** = BCTC chi tiết.

---

## 1. Khảo sát nguồn — bằng chứng trước khi thiết kế

Toàn bộ kết luận dưới đây đến từ việc gọi thật `vnstock 4.0.4`
(`vnstock.api.financial.Finance`) trên dữ liệu sản xuất, không phải đọc tài
liệu. Ba phát hiện dưới đây đã đổi hướng thiết kế so với giả định ban đầu.

### 1.1 Số suy ra hiện tại đã RẤT chính xác — mục tiêu "đối chiếu" yếu hơn dự kiến

Spec gốc mảng A (`2026-08-09-fundamental-analysis-platform-design.md` dòng
650) đưa B2 vào như một biện pháp giảm nhẹ rủi ro: *"Chỉ tiêu suy ra (doanh
thu/LNST) sai với doanh nghiệp có cấu trúc đặc biệt — Mảng B sẽ có số gốc từ
BCTC để đối chiếu chéo"*.

Đối chiếu thật cho HPG (2026-08-17): TTM doanh thu **suy ra** hiện tại trong
`fct_financial_quarterly` (từ `market_cap`/`ps`) so với TTM **thật** (tổng 4
quý `net_sales` lấy từ `income_statement`):

```
TTM suy ra (int_fundamentals_ttm) = 190.643.650.561.447
TTM thật (tổng 4 quý BCTC thật)   = 190.643.650.555.249
Lệch                              = -0,00%
```

Khớp gần như tuyệt đối — tốt hơn hẳn mức ±2% ghi nhận cho HPG 2024 trong
spec gốc mảng A. → **Đối chiếu số suy ra không còn là động lực chính cho
B2** (dù vẫn có thể làm sau như một task nhỏ riêng, xem §10).

### 1.2 Khoảng trống thật: một số mã KHÔNG có dữ liệu BCTC nào, không phải "số sai"

Thử 6 mã vốn hoá nhỏ/thanh khoản thấp (trùng nhóm đã phát hiện vấn đề
`dividend_yield` ở B1):

| Mã | `income_statement` qua VCI |
|---|---|
| AMP | 25 dòng |
| SIC | 25 dòng |
| VTJ | 25 dòng |
| HOM | 25 dòng |
| **TDN** | **0 dòng — RỖNG** (thử cả nguồn KBS cũng rỗng) |
| **ULG** | **0 dòng — RỖNG** |

2/6 mã mẫu hoàn toàn không có BCTC nào qua API. Đây là khoảng trống **thiếu
dữ liệu**, khác hẳn loại lỗi **sai dữ liệu** mà B1 gặp với `dividend_yield`.
→ B2 cần một trường `data_quality` báo rõ "không có dữ liệu" thay vì để tool
trả rỗng không giải thích (nguyên tắc xuyên suốt dự án: không để agent tự
suy diễn từ sự vắng mặt).

### 1.3 `item_id` KHÔNG phải khoá duy nhất trong một báo cáo — phát hiện cấu trúc quan trọng nhất

`item_id` là khoá text ổn định (`net_sales`, `gross_profit`, `cost`,
`accumulated_depreciation`...), và **nhất quán 100% giữa các mã cùng
`com_class`** — đã kiểm chéo cả 3 nhóm:

| `com_class` | Cặp mã kiểm | Kết quả |
|---|---|---|
| NONFIN | HPG vs VNM | `income_statement`: 25/25 khớp, 0 lệch |
| OTHERFIN | SSI vs VND | `income_statement`: 77/77 khớp, 0 lệch |
| BANK | VCB vs BID | `balance_sheet`: 78/78 khớp · `cash_flow`: 52/52 khớp |

Nhưng **`item_id` không unique bên trong một báo cáo của cùng một mã**.
`balance_sheet` của HPG (122 dòng, 109 `item_id` duy nhất — 22 dòng bị
trùng, thuộc 9 `item_id` khác nhau):

- `cost`/`accumulated_depreciation` xuất hiện **4 lần mỗi cái** — vì bảng
  cân đối có 4 nhóm tài sản cố định (hữu hình / thuê tài chính / vô hình /
  đầu tư), mỗi nhóm có dòng "Nguyên giá"/"Khấu hao luỹ kế" riêng, nhưng
  vnstock gán CHUNG một `item_id` cho cả 4 — chỉ tên tiếng Việt (`item`)
  phân biệt được (`"Nguyên giá TSCĐ hữu hình"` vs `"Nguyên giá tài sản thuê
  tài chính"` vs...).
- `short_term_investments` xuất hiện 2 lần với **CÙNG `item_id` LẪN CÙNG
  tên tiếng Việt** (`"Đầu tư ngắn hạn"`), chỉ khác giá trị (một dòng có số
  thật, một dòng luôn 0.0). Không cột nào (kể cả `item_en`) phân biệt được
  hai dòng này.

Không có cột phân cấp/section nào trong dữ liệu trả về (`item`, `item_en`,
`item_id`, cột theo kỳ — hết). **Chỉ có VỊ TRÍ DÒNG trong bảng trả về** giữ
được đúng nhóm ngữ nghĩa (đã xác nhận bằng cách in vị trí 8 dòng
`cost`/`accumulated_depreciation`: 30, 31, 33, 34, 36, 37, 40, 41 — liên
tục theo đúng thứ tự 4 nhóm tài sản).

→ **Khoá lưu trữ phải dựa vào vị trí dòng** (`row_seq`), không phải
`item_id`. Nhưng CHƯA XÁC MINH vị trí dòng có ổn định giữa các lần gọi API
cách nhau (ví dụ tuần này vs tuần sau) hay không — đây là rủi ro lớn nhất
của B2, xử lý ở §5 (Task 1 — cổng chặn, theo đúng mẫu B1 đã dùng cho `id`
sự kiện DN).

### 1.4 Dữ liệu dùng được

| API | Kết quả (HPG, `period="quarter"`) | Dùng ở B2 |
|---|---|---|
| `Finance(symbol, source, period).income_statement()` | 25 dòng × 8 cột kỳ | ✓ |
| `.balance_sheet()` | 122 dòng (109 `item_id` duy nhất) × 8 cột kỳ | ✓ |
| `.cash_flow()` | 41 dòng × 8 cột kỳ | ✓ |
| `period="year"` | Cùng cấu trúc, 8 cột kỳ = 8 năm (2018-2025) | ✓ (backfill 1 lần) |

Namespace `item_id` gần như tách biệt hoàn toàn giữa 3 báo cáo — chỉ trùng
1 mục (`minority_interests`, xuất hiện ở cả `income_statement` lẫn
`balance_sheet`, hợp lý vì lợi ích thiểu số vừa là khoản phân bổ P&L vừa là
mục vốn chủ trên bảng cân đối). Cột `item_en` cũng có sẵn (bản tiếng Anh),
không dùng làm khoá (dự án quy ước tiếng Việt) nhưng có thể lưu tham khảo.

**Không có tham số nào mở rộng quá 8 kỳ** — đã kiểm cả `period="quarter"`
lẫn `"year"`, không có `lang`/`dropna`/tham số ẩn nào đổi được số kỳ trả về
(cùng giới hạn đã gặp ở BCTC lúc khảo sát B1 §10).

---

## 2. Phạm vi B2

**Mục tiêu chính đã chốt: phơi BCTC chi tiết đầy đủ** (không chỉ
doanh thu/LNST) — giá trị hoàn toàn mới so với hệ thống hiện tại, vốn chỉ
có tỷ số suy ra (`fct_financial_quarterly`) chứ không có số gốc từng dòng.
Đối chiếu số suy ra (§1.1) là hiệu ứng phụ, không phải mục đích.

**Làm cả 3 báo cáo cùng lúc** (không tách B2a/B2b) — vì thiết kế bảng dạng
DÀI thống nhất khiến việc thêm 1 báo cáo không tốn thêm bảng, chỉ tốn thêm
giá trị `statement_type`. Độ phức tạp chính nằm ở bước ánh xạ `item_id` +
vị trí dòng, không nằm ở số lượng bảng.

**Không làm** (ghi rõ để không hiểu nhầm ở review):

- Không tính lại tỷ số suy ra, không sửa `fct_financial_quarterly`/
  `int_fundamentals_ttm`/`src/scoring.py` — B2 chỉ THÊM dữ liệu gốc, không
  đổi công thức chấm điểm hay bất kỳ tỷ số nào đang chạy.
- Không làm tầng đối chiếu tự động (số suy ra vs số thật) — để dành làm
  task nhỏ riêng sau nếu cần (§10), vì giá trị đã được xác nhận thấp
  (§1.1).
- Không đụng `mart_stock_scorecard`.
- Không xử lý mã hoàn toàn thiếu dữ liệu (§1.3) bằng cách chặn/loại — chỉ
  cần `data_quality` báo đúng, để agent tự quyết định.

---

## 3. Kiến trúc & luồng dữ liệu

```
INGEST (Python)                        WAREHOUSE
build_warehouse.py --mode weekly
  Finance(symbol,source,period)     →  raw_financial_statement
    .income_statement()                (symbol, com_class, statement_type,
    .balance_sheet()                    period_type, period_label, row_seq,
    .cash_flow()                        item_id, item_vi, item_en, value,
    → unpivot wide → dài                ingested_at)
  (period="year": backfill 1 lần,
   xếp vào --mode monthly)
```

**Một bảng `raw_financial_statement` duy nhất** cho cả 3 báo cáo × 3
`com_class` × 2 `period_type` — thiết kế dạng dài tự nhiên xử lý được cả
sự khác biệt schema theo `com_class` (chỉ là tập `item_id` khác nhau, ánh
xạ theo giá trị `statement_type`+`com_class` cụ thể) lẫn 3 loại báo cáo
(thêm 1 cột phân biệt), không cần 9 bảng riêng.

### 3.1 Khoá & cột

**Khoá:** `(symbol, statement_type, period_type, period_label, row_seq)`.

`row_seq` là vị trí dòng (0-based) trong DataFrame trả về từ MỘT lần gọi
`income_statement()`/`balance_sheet()`/`cash_flow()` — mỗi lần gọi trả về
TOÀN BỘ 8 cột kỳ trong MỘT bảng, nên vị trí dòng nhất quán nội bộ trong
cùng một lần fetch theo thiết kế (không cần lo vị trí xáo trộn giữa các kỳ
của CÙNG một lần gọi). Rủi ro thật chỉ nằm ở việc vị trí có xáo trộn giữa
CÁC LẦN GỌI khác nhau (ví dụ tuần này vs tuần sau) hay không — xử lý ở §5.

**Cột đầy đủ:**

```
symbol          VARCHAR
com_class       VARCHAR   -- NONFIN/BANK/OTHERFIN, lấy từ dim_stock lúc ingest
statement_type  VARCHAR   -- income_statement / balance_sheet / cash_flow
period_type     VARCHAR   -- quarter / year
period_label    VARCHAR   -- "2026-Q2" hoặc "2025" (nguyên văn tên cột API)
row_seq         INTEGER   -- vị trí dòng trong lần fetch
item_id         VARCHAR
item_vi         VARCHAR   -- cột "item" của API
item_en         VARCHAR   -- cột "item_en" của API, tham khảo, không phải khoá
value           DOUBLE
ingested_at     TIMESTAMP
```

**Cách ghi:** `INSERT OR REPLACE` theo khoá đầy đủ (giống `raw_shareholder`/
`raw_officer` ở B1 — chạy lại cùng kỳ thì ghi đè, khác kỳ thì tích luỹ).

Cửa sổ 8 kỳ **cũng trượt** giống sự kiện DN (mỗi lần fetch chỉ trả 8 kỳ gần
nhất — kỳ cũ nhất rơi khỏi cửa sổ khi có kỳ mới). Nhưng KHÁC
`raw_corporate_event` (phải dùng append-only vì đơn vị trùng lặp là
**toàn bộ sự kiện**, không có gì phân biệt "sự kiện cũ" khỏi batch mới
ngoài chính nó): ở đây đơn vị ghi là **từng Ô (dòng × kỳ)** có khoá riêng
theo `period_label`. Khi kỳ mới nhất xuất hiện và kỳ cũ nhất rơi khỏi cửa
sổ fetch, `INSERT OR REPLACE` chỉ chạm tới các khoá CÓ MẶT trong batch mới
(8 kỳ hiện tại) — kỳ đã rơi khỏi cửa sổ (ví dụ 2024-Q3 sau vài quý) đơn
giản KHÔNG bị đụng tới, vẫn nằm nguyên trong bảng từ lần ghi trước. Đây là
lý do tích luỹ vẫn đúng dù dùng `OR REPLACE` chứ không phải vì "không có
cửa sổ trượt" — khoá đủ mịn (tới từng kỳ) khiến ghi đè không bao giờ xoá
mất kỳ cũ hơn cửa sổ hiện tại. **Cần 1 test xác nhận đúng hành vi này**
(tương tự `test_su_kien_cu_khong_bi_mat_khi_cua_so_truot` ở B1) — mô phỏng
2 lần fetch với cửa sổ 8-kỳ lệch nhau, xác nhận kỳ cũ nhất của lần 1 vẫn
còn sau lần 2.

### 3.2 Quy mô ước tính

~80 dòng trung bình/báo cáo (dải 25-208 tuỳ `statement_type`×`com_class`)
× 3 báo cáo × 8 kỳ × 2 `period_type` × ~1.600 mã ≈ **6 triệu dòng** cho lần
backfill đầu (quý sẽ tích luỹ thêm theo thời gian sau mỗi lần chạy weekly;
năm chỉ backfill 1 lần, không lặp lại). Cùng cấp độ với `raw_price_daily`
(1,25 triệu dòng hiện có) — không phải vấn đề với MotherDuck free tier.

---

## 4. Nhịp ingest & tầng dbt

**Nhịp: `weekly`** (`period="quarter"`) — cùng nhịp `raw_financial_ratio`/
sự kiện DN (B1). BCTC mỗi công ty chỉ công bố 1 lần/quý (không đổi trong
quý), nhưng các công ty công bố vào thời điểm khác nhau trong khoảng ~45
ngày sau khi quý kết thúc — chạy đều hàng tuần để bắt kịp, không có lý do
tách nhịp riêng khi cùng họ API `Finance` với `fetch_financials` đã có
(dùng chung pattern bắt lỗi theo từng mã, `dq.status_for`).

**Backfill `period="year"` (8 năm): chạy 1 lần, sau đó xếp vào `--mode
monthly`** (không lặp lại hàng tuần — dữ liệu năm chỉ đổi khi có báo cáo
kiểm toán mới, hiếm).

**Tầng dbt — giữ tối giản:**

```
raw_financial_statement → stg_financial_statement (view, làm sạch nhẹ)
```

Không làm tầng `intermediate`/mart mới trong B2 (mục tiêu là phơi dữ liệu
gốc, không tính lại chỉ tiêu tổng hợp — xem §2 "Không làm").
`stg_financial_statement` chỉ ép kiểu + test: `unique` trên khoá tổng hợp
5 cột, `accepted_values` trên `statement_type` (3 giá trị) và `period_type`
(2 giá trị) và `com_class` (NONFIN/BANK/OTHERFIN/UNKNOWN, khớp quy ước có
sẵn), `not_null` trên `symbol`/`item_id`/`item_vi`.

---

## 5. Task 1 (cổng chặn) — kiểm chứng vị trí dòng ổn định

Giống hệt cách B1 kiểm `id` sự kiện DN trước khi xây append-only: gọi
`income_statement()`/`balance_sheet()`/`cash_flow()` cho một mẫu mã (trộn
cả 3 `com_class`: ví dụ HPG/VNM (NONFIN), VCB/BID (BANK), SSI/VND
(OTHERFIN)) **hai lần cách nhau ≥60 giây**, đối chiếu:

- Số dòng có đổi không (thêm/bớt dòng giữa 2 lần gọi).
- Với mỗi vị trí dòng, `item_id`+`item_vi` có giữ nguyên không (đây chính
  là điều kiện "vị trí dòng ổn định").

**Nếu ổn định:** dùng `row_seq` làm khoá đúng như §3.1, tiếp tục các task
sau.

**Nếu KHÔNG ổn định:** DỪNG, không tự ý đổi thiết kế — báo cáo controller.
Hướng dự phòng (chưa chọn, chỉ ghi lại để không mất thời gian nghĩ lại):
dùng `(item_id, item_vi)` làm khoá phụ, chấp nhận các dòng thật sự trùng
cả hai (như ca `short_term_investments` ở §1.3) bị gộp làm một (mất chính
xác ở một số ít dòng, nhưng vẫn đúng cho tuyệt đại đa số).

---

## 6. Tool MCP

**1 tool mới: `get_financial_statement(symbol, statement_type,
period_type="quarter") -> dict`**

```json
{
  "symbol": "HPG",
  "statement_type": "balance_sheet",
  "period_type": "quarter",
  "items": [
    {
      "item_id": "cost",
      "item_vi": "Nguyên giá TSCĐ hữu hình",
      "row_seq": 30,
      "values_by_period": {
        "2026-Q2": 186818000000000,
        "2026-Q1": 185926000000000,
        "...": "..."
      }
    }
  ],
  "n_items": 122,
  "data_quality": {
    "has_data": true,
    "n_periods_available": 8
  },
  "price_as_of": "...", "ratio_as_of": "..."
}
```

Giữ dạng "mỗi dòng BCTC kèm chuỗi giá trị theo kỳ" (gần với hình dạng wide
gốc của API) thay vì bung phẳng thành hàng nghìn dòng dài — dễ đọc hơn cho
agent, và khớp tự nhiên với cách `get_valuation_history`/
`get_financial_history` (đã có) trả chuỗi theo kỳ.

`row_seq` trả kèm để phân biệt các dòng trùng `item_id` (ca `cost` × 4
nhóm tài sản, §1.3) — cùng `item_vi` để agent tự biết dòng nào là dòng
nào mà không cần tra `row_seq` trực tiếp trong câu trả lời cho người dùng.

`data_quality.has_data = false` khi mã không có báo cáo nào (ca TDN/ULG,
§1.2) — tool trả `error` rõ ràng thay vì `items: []` không giải thích
(đúng pattern `get_stock_profile`/`get_distribution_history` đã dùng cho
mã không tồn tại/không có dữ liệu).

**Không đổi 9 tool cũ**, không đụng `get_financial_history` hiện có (dùng
`fct_financial_quarterly`/tỷ số suy ra — mục đích khác, giữ nguyên).

---

## 7. Kiểm thử

| Test | Canh lỗi gì |
|---|---|
| Vị trí dòng ổn định giữa 2 lần gọi (Task 1, §5) | Khoá `row_seq` vỡ nếu không kiểm trước |
| Kỳ cũ nhất KHÔNG mất khi cửa sổ 8-kỳ trượt qua 2 lần fetch (giả lập, §3.1) | `INSERT OR REPLACE` vô tình xoá mất lịch sử nếu khoá không đủ mịn |
| `unique` trên khoá 5 cột | Ghi đè nhầm giữa các dòng khác nhau |
| `accepted_values` trên `statement_type`/`period_type`/`com_class` | Nguồn đổi format không bị lọt |
| Tool trả `data_quality.has_data=false` đúng cho mã không có BCTC | Không để `items: []` mập mờ (§1.2) |
| Tool gọi qua `mcp.call_tool()` thật, không chỉ hàm Python trần | Crash ở tầng serialize JSON (bài học A3 I1, B1 áp dụng lại nhiều lần) |
| Fixture khớp schema thật, đủ cột (kể cả `row_seq` trùng `item_id`) | Fixture sai giống code sai → test luôn xanh (A3 I2, B1 Task 4/5) |
| Đối chiếu tay 1 báo cáo thật (ví dụ HPG `balance_sheet`) — số dòng, `item_id` trùng, giá trị 1-2 dòng cụ thể | Không dùng dữ liệu tổng hợp thay cho xác nhận trên dữ liệu thật khi có thể chạy được |

---

## 8. Rủi ro

| Rủi ro | Mức | Xử lý |
|---|---|---|
| Vị trí dòng không ổn định giữa các lần gọi | **Cao, chưa biết** | Task 1 kiểm trước, chặn (§5) |
| Mã hoàn toàn thiếu BCTC (TDN, ULG, ...) | Đã biết, ≥2/6 mẫu | `data_quality.has_data=false`, không chặn build |
| `item_id` trùng trong 1 báo cáo (đã đo: 22/122 dòng ở HPG balance_sheet) | Đã biết, đã có hướng xử lý | `row_seq` + `item_vi` đi kèm, không dùng `item_id` một mình làm khoá |
| Quy mô bảng ~6 triệu dòng | Thấp | Cùng cấp `raw_price_daily`, MotherDuck xử lý được |
| Rate limit vnstock (60 req/phút) | Thấp | `VNSTOCK_MIN_INTERVAL` đã có sẵn, dùng lại pattern `fetch_financials` |
| Thời lượng job weekly tăng thêm (~28 phút/nguồn × 3 báo cáo mới) | Trung bình | Ước tính +84 phút cho weekly job — cần đo thật ở Task nghiệm thu, có thể cần tách bớt hoặc chấp nhận job dài hơn (đã có tiền lệ B1 monthly ~140 phút) |

---

## 9. Tiêu chí hoàn thành B2

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| 1 | Vị trí dòng ổn định giữa 2 lần gọi (hoặc đã đổi sang khoá thay thế) | Task 1 |
| 2 | Toàn bộ pytest pass, không hỏng test cũ | `pytest tests/ -q` |
| 3 | `raw_financial_statement` có dữ liệu thật trên MotherDuck, cả `period_type="quarter"` lẫn `"year"` | Truy vấn đếm dòng theo `period_type` |
| 4 | Không dòng nào vi phạm `unique` trên khoá 5 cột | dbt test |
| 5 | Tool trả đúng `data_quality.has_data=false` cho ít nhất 1 mã đã biết thiếu dữ liệu (TDN hoặc ULG) trên production thật | Gọi tool thật |
| 6 | Đối chiếu tay ≥1 báo cáo thật khớp giá trị hiển thị trên nguồn (không chỉ khớp số dòng) | Task nghiệm thu |
| 7 | `mart_stock_scorecard` và điểm số **không đổi** | Đối chiếu trước/sau |

---

## 10. Sau B2

- **Đối chiếu số suy ra vs số thật** (giá trị đã xác nhận thấp ở §1.1,
  nhưng có thể vẫn đáng làm cho nhóm mã vốn hoá nhỏ nơi số suy ra ít được
  kiểm chứng hơn — tương tự nợ `dividend_yield` B1 đã phát hiện) — task
  nhỏ riêng, không phải core B2.
- **Khối ngoại** — vẫn chờ nguồn (B1 §1.1, chưa đổi).
- **Mảng C** — báo cáo luận điểm định kỳ, hộ tiêu thụ tiềm năng của
  `raw_financial_statement` (ví dụ trích dẫn nguyên văn dòng BCTC trong
  luận điểm thay vì chỉ tỷ số suy ra).
