# B1 — Sự kiện doanh nghiệp, phân phối & cơ cấu sở hữu

> Thiết kế chốt ngày 2026-08-16. Tiếp nối mảng A (A1 nền dữ liệu · A2 dbt marts &
> chấm điểm · A3 MCP server) đã merge vào `main` qua PR #3 và #4.
>
> Mảng B trong spec gốc (`2026-08-09-fundamental-analysis-platform-design.md` §667)
> gồm bốn hạng mục: BCTC chi tiết · sự kiện DN & cổ tức · khối ngoại · cơ cấu cổ đông.
> Tài liệu này chỉ đặc tả **B1** = sự kiện & phân phối & sở hữu. BCTC chi tiết tách
> thành B2. Khối ngoại **bị loại** — không có nguồn (xem §1.1).

---

## 1. Khảo sát nguồn — bằng chứng trước khi thiết kế

Toàn bộ kết luận dưới đây đến từ việc gọi thật `vnstock 4.0.4` trên dữ liệu sản
xuất, không phải đọc tài liệu. Ghi lại đầy đủ vì ba trong số đó đã **thay đổi phạm vi**
mảng B so với spec gốc.

### 1.1 Khối ngoại: không có nguồn — loại khỏi mảng B

Spec gốc ghi dùng `Trading.foreign_trade`. Gọi thật:

```
VCI.foreign_trade → NotImplementedError: Source 'VCI' does not support 'foreign_trade'
KBS.foreign_trade → NotImplementedError: Source 'KBS' does not support 'foreign_trade'
```

Method tồn tại trên interface nhưng chưa được cài đặt ở cả hai nguồn `Trading` hỗ
trợ. `prop_trade`, `insider_deal`, `Company.ownership`, `Company.capital_history`
cũng vậy. **Không có đường vòng** — `Company.dividends()` (từng có ở API cũ) gọi ra
`AttributeError`.

→ Khối ngoại chỉ quay lại chương trình khi vnstock cài đặt, hoặc khi tìm được nguồn
khác. Không phải nợ kỹ thuật của B1; là ràng buộc bên ngoài.

### 1.2 Cửa sổ `events()` nông và thiên lệch có hệ thống

`Company.events()` trả **50 sự kiện gần nhất**, không có tham số mở rộng. Cửa sổ
thời gian 50 sự kiện đó phủ được bao lâu **phụ thuộc mã đó hoạt động sự kiện nhiều
hay ít** — đo trên 15 mã:

| Nhóm | Mã · số năm cửa sổ phủ | Số năm có cổ tức |
|---|---|---|
| Bluechip năng động | MWG 1,0 · REE 1,3 · VNM 1,5 · FPT 1,7 · TCB 2,5 | 2–4 |
| Mã nhỏ ít sự kiện | AGX 9,9 · PHP 9,6 · VNR 9,4 · SBH 9,3 · MLS 9,1 | 9–11 |

Trung vị 5,6 năm. 8/15 mã đủ ≥5 năm cổ tức; 12/15 đủ ≥3 năm.

Thiên lệch này **có hệ thống, không phải nhiễu**: mã càng nhiều sự kiện (cổ đông lớn
giao dịch, phát hành…) thì lịch sử cổ tức nhìn thấy được càng ngắn. VNM — một trong
những mã trả cổ tức đều nhất thị trường — chỉ hiện 3 năm; PHP (cảng nhỏ) hiện 11 năm.

**Hệ quả thiết kế:** không được dùng `events()` để tính `dividend_years_consecutive`.
Làm vậy sẽ khiến profile `bluechip_dividend` loại chính các bluechip và ưu tiên mã
nhỏ ít sự kiện — sai ngược đúng mục đích của profile, và tệ hơn lỗi ngẫu nhiên vì nó
có hướng.

### 1.3 Nguồn cổ tức hiện có KHÔNG sai — bỏ mục tiêu "sửa chuỗi cổ tức"

Giả thuyết ban đầu (`dividend_years_consecutive` suy ra từ `dividend_yield` nên
sai, cần thay bằng số thật) đã bị **bác bỏ bằng đối chiếu**. Ghép sự kiện HPG với
`stg_financial_ratio` theo năm:

| Năm | `events()` ghi nhận | `dividend_yield` | Kết luận |
|---|---|---|---|
| 2021 | tiền mặt 500 đ (chi trả 17/06/2022) | 0,0278 | khớp |
| 2022 | chỉ cổ tức **cổ phiếu** 30% | 0 | đúng — không có tiền mặt |
| 2023 | không có sự kiện | 0 | đúng |
| 2024 | chỉ **cổ phiếu thưởng** 10% | 0 | đúng — thưởng ≠ cổ tức |
| 2025 | tiền mặt 500 đ (chi trả 11/05/2026) | 0,0235 | khớp |

"HPG 1 năm liên tiếp" là **chính xác** cho cổ tức tiền mặt. Nguồn hiện có còn *sâu
hơn* `events()`: `stg_financial_ratio` có 2018→2025 cho VNM/HPG/REE, trong khi cửa
sổ sự kiện của VNM chỉ 1,5 năm.

→ B1 **không sửa** `int_dividend_history`, **không đụng** `mart_stock_scorecard`,
**không đổi** công thức chấm điểm. Nợ N17 (chuỗi cổ tức chưa cắt khi một năm vắng
mặt hoàn toàn) nói về chuyện khác và vẫn để nguyên.

### 1.4 Cột `category` của nguồn sai ở 14/33 sự kiện `ISS`

Khảo sát 564 sự kiện trên 12 mã:

```
category    DIVIDEND  MAJOR_SHAREHOLDER_TRADING  OTHER  SHAREHOLDER_MEETING
DIV              120                          0      0                    0
ISS               33                          0      0                    0   ← sai
DDIND              0                         97      0                    0
DDINS              0                        152      0                    0
DDRP               0                         43      0                    0
AGME               0                          0      0                   73
AGMR               0                          0      0                    3
EGME               0                          0      0                   13
AIS                0                          0     20                    0
OTHE               0                          0      7                    0
MOVE / NLIS / SUSP 0                          0      3                    0
```

Nguồn gán **toàn bộ** 33 dòng `ISS` vào `category = 'DIVIDEND'`. Bóc tiêu đề ra:

| Tiêu đề (bỏ phần tỉ lệ) | Số dòng | Thực chất |
|---|---|---|
| Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu | 13 | phân phối cho cổ đông |
| Phát hành cổ phiếu - **Phát hành cho CBCNV** | **9** | **ESOP — pha loãng** |
| Phát hành cổ phiếu - Cổ phiếu thưởng | 6 | phân phối (từ thặng dư vốn) |
| Phát hành cổ phiếu - **Phát hành riêng lẻ** | **5** | **pha loãng** |

Tin thẳng `category` là đếm ESOP và phát hành riêng lẻ thành "phân phối cho cổ
đông", trong khi tác động kinh tế **ngược dấu**. Đây là lý do §4 phải phân loại hai
tầng chứ không dùng `category`.

### 1.5 `shareholders()` không tổng thành 100%

| Mã | Số dòng | Tổng % công bố | Nhỏ nhất |
|---|---|---|---|
| HPG | 66 | 51,9% | 0,0000% |
| VNM | 93 | 81,0% | 0,0002% |
| VCB | 29 | 91,0% | 0,0001% |

Đây là danh sách cổ đông **đã công bố** ở nhiều quy mô (không phải chỉ >5%). Phần
thiếu là cổ đông không công bố và **không đồng nghĩa free float** —
`dim_stock.free_float_percentage` là con số khác, từ nguồn khác. Tool phải nói rõ
chỗ này (§6).

### 1.6 Dữ liệu dùng được

| API | Kết quả | Dùng ở B1 |
|---|---|---|
| `Company.events()` | 50 dòng × 22 cột, có `exright_date`/`record_date`/`payout_date`/`exercise_ratio`/`value_per_share` | ✓ |
| `Company.shareholders()` | 5 cột: `symbol, share_holder, quantity, share_own_percent, update_date` | ✓ |
| `Company.officers()` | 6 cột, có `officer_own_percent`/`officer_own_quantity` | ✓ |
| `Company.subsidiaries()` | 4 cột | ✗ khác trục, để sau |
| `Company.affiliate()` | trả rỗng `(0, 0)` | ✗ |

---

## 2. Phạm vi B1

**Làm:** ingest sự kiện DN + cổ đông + ban lãnh đạo vào 3 bảng raw · tầng staging
phân loại sự kiện · tầng intermediate cho phân phối và cô đặc sở hữu · 2 tool MCP.

**Không làm** (ghi rõ để không hiểu nhầm ở review):

- Không đụng `mart_stock_scorecard`, không thêm cột vào mart hiện có.
- Không đổi công thức chấm điểm, không thêm/sửa thành phần điểm.
- Không sửa `int_dividend_history` — đã xác minh đúng (§1.3).
- Không làm khối ngoại — không có nguồn (§1.1).
- Không làm BCTC chi tiết — để B2.
- Không làm cảnh báo/thông báo — để mảng C. B1 chỉ dựng nền dữ liệu + tra cứu.

---

## 3. Kiến trúc & luồng dữ liệu

```
INGEST (Python)                      WAREHOUSE                        TIÊU THỤ
build_warehouse.py
  --mode weekly  → events()      → raw_corporate_event ─┐
  --mode monthly → shareholders() → raw_shareholder     ├→ stg_* → int_* → MCP tools
                 → officers()     → raw_officer         ─┘                (mảng C sau)
```

Gắn vào khung sẵn có: `build_warehouse.py --mode {daily,weekly,monthly}`,
`src/ingest_market.py`, rate limit qua `VNSTOCK_MIN_INTERVAL=1.05`, ghi log qua
`warehouse.log_load()`. **Không cần workflow mới** — thêm bước vào
`warehouse-weekly.yml` và `warehouse-monthly.yml` đã có.

### 3.1 Nhịp chạy

| Nguồn | Nhịp | Lý do |
|---|---|---|
| `events()` | **tuần** (`--mode weekly`) | GDKHQ có ngày cụ thể; chạy tháng dễ lỡ sự kiện công bố và chốt quyền trong cùng tháng — mảng C cần độ tươi này |
| `shareholders()`, `officers()` | **tháng** (`--mode monthly`) | trạng thái sở hữu đổi rất chậm |

Chi phí: ~1.600 mã × 1,05 s ≈ **28 phút** mỗi nguồn. Weekly job từ ~28 phút lên
~56 phút; monthly tăng tương tự. Xa dưới giới hạn 6 giờ của GitHub Actions.

### 3.2 Ba bảng raw, hai cơ chế ghi

Đây là điểm thiết kế quan trọng nhất của B1.

| Bảng | Bản chất | Cách ghi | Khoá |
|---|---|---|---|
| `raw_corporate_event` | **dòng sự kiện** — mỗi sự kiện xảy ra một lần | append-only, bỏ qua trùng | `id` từ nguồn |
| `raw_shareholder` | **trạng thái** — ai đang nắm bao nhiêu *hôm nay* | snapshot định kỳ, giữ lịch sử | `(symbol, share_holder, snapshot_date)` |
| `raw_officer` | trạng thái | snapshot định kỳ | `(symbol, officer_name, snapshot_date)` |

**Vì sao sự kiện phải append:** cửa sổ 50 sự kiện trượt theo thời gian. Mã năng động
như MWG (cửa sổ 1,0 năm) mỗi lần gọi lại rơi mất sự kiện cũ nhất. Ghi đè là mất vĩnh
viễn; cộng dồn thì lịch sử dày lên theo thời gian — sau 3 năm chạy đều, mọi mã đều có
ít nhất 3 năm lịch sử thật bất kể cửa sổ API.

**Vì sao sở hữu phải snapshot:** không có `id` ổn định, và thứ có giá trị chính là
*thay đổi theo thời gian* ("quỹ ngoại giảm từ 8% xuống 5%"). Cộng dồn không phân biệt
được "cổ đông mới xuất hiện" với "cổ đông cũ đổi tỉ lệ".

### 3.3 Cột giữ lại

Bỏ các cột `*_en` (trùng nghĩa với bản tiếng Việt), `display_date1`/`display_date2`
(ngữ nghĩa không rõ), `ticker` (trùng `symbol`).

**`raw_corporate_event`:** `id`, `symbol`, `event_code`, `event_name_vi`,
`event_title_vi`, `category`, `public_date`, `issue_date`, `start_date`, `end_date`,
`record_date`, `exright_date`, `listing_date`, `payout_date`, `exercise_ratio`,
`value_per_share`, `action_type_vi`, `ingested_at`

**`raw_shareholder`:** `symbol`, `share_holder`, `quantity`, `share_own_percent`,
`update_date`, `snapshot_date`, `ingested_at`

**`raw_officer`:** `symbol`, `officer_name`, `officer_position`,
`officer_own_percent`, `officer_own_quantity`, `update_date`, `snapshot_date`,
`ingested_at`

---

## 4. Phân loại sự kiện — `stg_corporate_event`

Phân loại **hai tầng**: `event_code` (có cấu trúc, tin được) làm tầng chính; chỉ đọc
tiêu đề tự do cho đúng nhánh `ISS`, nơi `event_code` không đủ phân biệt (§1.4).

| `event_code` | Điều kiện tiêu đề | `distribution_type` | `is_distribution` |
|---|---|---|---|
| `DIV` | — | `CASH_DIVIDEND` | ✓ |
| `ISS` | chứa "cổ tức bằng cổ phiếu" | `STOCK_DIVIDEND` | ✓ |
| `ISS` | chứa "cổ phiếu thưởng" | `BONUS_SHARE` | ✓ |
| `ISS` | chứa "cho CBCNV" / "CBNV" / "ESOP" | `ESOP` | ✗ |
| `ISS` | chứa "riêng lẻ" | `PRIVATE_PLACEMENT` | ✗ |
| `ISS` | **không khớp mẫu nào** | `ISS_KHAC` | ✗ |
| `DDIND` / `DDINS` / `DDRP` | — | `INSIDER_TRADING` | ✗ |
| `AGME` / `AGMR` / `EGME` | — | `SHAREHOLDER_MEETING` | ✗ |
| `AIS` / `OTHE` / `MOVE` / `NLIS` / `SUSP` | — | `OTHER` | ✗ |
| **code chưa từng thấy** | — | `UNKNOWN_CODE` | ✗ |

So khớp tiêu đề **không phân biệt hoa/thường**, bỏ dấu cách thừa. Ba nguyên tắc:

1. **Không khớp thì gán "không biết", không đoán.** `ISS_KHAC` và `UNKNOWN_CODE` là
   nhãn hợp lệ, không phải lỗi cần né. Mọi thứ không chắc chắn có
   `is_distribution = false` — fail-closed.
2. **`is_distribution` chỉ true cho `CASH_DIVIDEND`, `STOCK_DIVIDEND`,
   `BONUS_SHARE`.** ESOP và phát hành riêng lẻ vẫn nằm trong bảng (mảng C sẽ cảnh
   báo được — "sắp phát hành riêng lẻ" là tin đáng quan tâm) nhưng bị loại khỏi mọi
   phép tính phân phối.
3. **Phơi tỉ lệ chưa phân loại được.** Test dbt cảnh báo khi
   `ISS_KHAC + UNKNOWN_CODE` vượt **5% tổng số sự kiện** — biết ngay khi nguồn đổi
   format, thay vì âm thầm phân loại sai. Ngưỡng 5% chọn từ mẫu khảo sát: 564 sự
   kiện / 12 mã cho **0 dòng** chưa phân loại (33/33 `ISS` khớp một trong bốn mẫu),
   nên 5% là biên rộng rãi — vượt qua nghĩa là có thay đổi thật ở nguồn, không phải
   nhiễu. Mở mẫu từ 1 mã lên 12 mã đã lộ thêm 5 `event_code` (`AGMR`, `EGME`,
   `MOVE`, `NLIS`, `SUSP`), nên gặp code lạ là chuyện chắc chắn xảy ra.

Cùng tinh thần `pe_quarters_used` / `n_pe` / `*_weight_coverage` / `rejected_total`
của A2: **một con số cần được phơi kèm bằng chứng đỡ nó.**

### 4.1 Tầng intermediate

- **`int_distribution_event`** — lọc `is_distribution = true`; chuẩn hoá
  `cash_per_share` (từ `value_per_share`, chỉ `CASH_DIVIDEND`) và `stock_ratio` (từ
  `exercise_ratio`, chỉ `STOCK_DIVIDEND`/`BONUS_SHARE`); giữ `exright_date` làm trục
  thời gian.
- **`int_ownership_snapshot`** — theo `snapshot_date` mới nhất mỗi mã: `top1_pct`,
  `top5_pct`, `n_disclosed`, `total_disclosed_pct`, `insider_pct` (tổng từ
  `raw_officer`).

---

## 5. Hai trục thời gian — quyết định kiến trúc

Hai nguồn phân phối nằm trên **hai trục thời gian khác nhau**: `dividend_yield` gán
theo *năm tài chính*; `events()` gán theo *ngày GDKHQ*. Cổ tức "cả năm 2021" của HPG
chi trả ngày 17/06/2022.

**Chốt hướng A: giữ hai trục riêng, không ép ghép.** Tool trả hai khối tách bạch, mỗi
khối ghi rõ trục của nó.

Hướng B (ép về một trục năm tài chính bằng cách parse "Cả năm 2025" trong tiêu đề) bị
loại vì: cổ tức **bằng cổ phiếu** — đúng phần dữ liệu mới mà B1 sinh ra để lấy —
**không có thông tin năm nào trong tiêu đề** ("Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%").
Hướng B chỉ ghép được phần đã có sẵn và bó tay ở phần mới.

---

## 6. Hai tool MCP

Cả hai bọc `_safe_tool`, trả `as_of`, đọc qua `db.run_query` — dùng lại nguyên khung
A3, không phát minh gì mới.

### 6.1 `get_distribution_history(symbol, years=5)`

```
{
  "symbol": "HPG",
  "cash_dividend_by_fiscal_year": [        # nguồn cũ, trục NĂM TÀI CHÍNH
      {"year": 2025, "dividend_yield": 0.0235},
      {"year": 2024, "dividend_yield": 0.0}, ...
  ],
  "distribution_events": [                  # nguồn mới, trục NGÀY GDKHQ
      {"exright_date": "2026-05-25", "type": "STOCK_DIVIDEND",
       "ratio": 0.10, "cash_per_share": null, "title": "..."},
      {"exright_date": "2026-05-11", "type": "CASH_DIVIDEND",
       "ratio": 0.05, "cash_per_share": 500.0, "title": "..."}, ...
  ],
  "note": "Hai khối nằm trên HAI TRỤC THỜI GIAN khác nhau — cổ tức 'cả năm 2021'
           chi trả ngày 17/06/2022. KHÔNG cộng gộp hai khối.",
  "data_quality": {"event_window_start": "2022-04-18", "event_window_years": 4.1,
                   "n_events": 50, "unclassified_events": 0},
  "price_as_of": "...", "ratio_as_of": "..."
}
```

`data_quality.event_window_years` là trường **bắt buộc**. Không có nó, agent nhìn VNM
thấy 3 sự kiện cổ tức rồi kết luận "VNM mới trả cổ tức 3 năm gần đây", trong khi sự
thật là cửa sổ chỉ nhìn được 1,5 năm (§1.2).

### 6.2 `get_ownership(symbol)`

```
{
  "symbol": "HPG",
  "major_shareholders": [{"name": "Trần Đình Long", "quantity": ..., "percent": 0.2580}, ...],
  "officers": [{"name": "...", "position": "...", "own_percent": ...}],
  "concentration": {"top1_pct": 0.2580, "top5_pct": ...,
                    "n_disclosed": 66, "total_disclosed_pct": 0.5189},
  "snapshot_date": "2026-08-01",
  "note": "Chỉ gồm cổ đông ĐÃ CÔNG BỐ — tổng 51,9%, không phải 100%. Phần còn lại là
           cổ đông không công bố, KHÔNG đồng nghĩa free float.",
  "price_as_of": "...", "ratio_as_of": "..."
}
```

---

## 7. Kiểm thử

### 7.1 Kiểm chứng chặn — làm trước, chưa xong thì chưa xây

Gọi `events()` hai lần cách nhau, đối chiếu `id`. **Toàn bộ cơ chế append-only dựa
vào giả định `id` ổn định giữa các lần gọi.** Nếu nguồn sinh `id` mới mỗi lần thì
dedup vỡ, bảng phình vô hạn, và mọi thứ phía sau vô nghĩa. Sai giả định này thì phải
đổi khoá dedup (ví dụ hash của `symbol + event_code + exright_date + title`) trước
khi đi tiếp.

### 7.2 Bộ test

| Test | Canh lỗi gì | Rút từ |
|---|---|---|
| Đối chiếu chéo `CASH_DIVIDEND` từ events vs `dividend_yield` theo năm | hai nguồn lệch nhau | §1.3 (đã làm tay với HPG, khớp) |
| `is_distribution` chỉ true cho 3 loại; ESOP/riêng lẻ luôn false | đếm pha loãng thành phân phối | §1.4 |
| `ISS_KHAC + UNKNOWN_CODE` ≤ 5% tổng sự kiện | nguồn đổi format, parser xuống cấp âm thầm | `docs/A2-A3-ket-qua-va-no-ky-thuat.md` §5 |
| Số dòng `raw_corporate_event` không giảm sau ingest | ghi đè làm mất lịch sử | §3.2 |
| `raw_shareholder` có ≥2 `snapshot_date` sau 2 lần chạy | snapshot bị ghi đè thành 1 dòng | §3.2 |
| Tool gọi qua `mcp.call_tool()` thật, **không** gọi hàm Python trần | crash ở tầng serialize JSON | **A3 I1** |
| Fixture khớp schema thật, đủ mọi cột | fixture sai giống code sai → test luôn xanh | **A3 I2** |

Mọi test canh lỗi phải được chứng minh bằng cách **chạy trên trạng thái lỗi**, không
chỉ trên trạng thái đã sửa (quy tắc A2 Task 8.5).

---

## 8. Rủi ro

| Rủi ro | Mức | Xử lý |
|---|---|---|
| `id` không ổn định giữa các lần gọi | **Cao** | §7.1 kiểm trước, chặn |
| Nguồn đổi tiêu đề tiếng Việt → parser `ISS` hỏng | Trung bình | test ngưỡng `ISS_KHAC + UNKNOWN_CODE` ≤ 5% (§4) |
| Xuất hiện `event_code` mới | **Chắc chắn xảy ra** | nhánh `UNKNOWN_CODE`, fail-closed |
| Rate limit vnstock (60 req/phút) | Thấp | `VNSTOCK_MIN_INTERVAL=1.05` đã có sẵn |
| Dung lượng bảng | Thấp | ~1.600 mã × 50 sự kiện ≈ 80k dòng ban đầu, tăng chậm |
| Agent cộng gộp hai trục thời gian | Trung bình | `note` bắt buộc trong response (§6.1) |

---

## 9. Tiêu chí hoàn thành B1

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| 1 | `id` ổn định giữa hai lần gọi (hoặc đã đổi sang khoá thay thế) | §7.1 |
| 2 | Toàn bộ pytest pass, không hỏng test cũ | `pytest tests/ -q` |
| 3 | 3 bảng raw có dữ liệu thật trên MotherDuck | truy vấn đếm dòng |
| 4 | Chạy ingest 2 lần: `raw_corporate_event` không mất dòng; `raw_shareholder` có 2 snapshot | §7.2 |
| 5 | Không dòng nào có `is_distribution = true` mà `distribution_type` ngoài 3 loại | dbt test |
| 6 | `ISS_KHAC` + `UNKNOWN_CODE` ≤ 5% tổng sự kiện | dbt test |
| 7 | 2 tool trả dữ liệu thật qua `mcp.call_tool()` | mở rộng `scripts/check_mcp_tools.py` |
| 8 | `mart_stock_scorecard` và điểm số **không đổi** trước/sau B1 | đối chiếu trước/sau |

Tiêu chí #8 là phép thử cho ràng buộc "không đụng mart" ở §2 — B1 chỉ được thêm, không
được đổi thứ đang chạy.

---

## 10. Sau B1

- **B2** — BCTC chi tiết (`income_statement` / `balance_sheet` / `cash_flow`). Đã
  khảo sát: chạy được nhưng **chỉ 8 kỳ cố định**, dạng wide (item × kỳ), và **schema
  khác nhau hoàn toàn theo loại hình DN** — HPG (NONFIN) 25 dòng income / 122 dòng
  balance · VCB (BANK) 26 / 86 · SSI (OTHERFIN) 79 / 208. Không phải cùng bộ chỉ tiêu
  với giá trị khác nhau, mà là **ba bộ chỉ tiêu khác nhau**. Đây là bài học `com_class`
  của A2 lặp lại ở tầng sâu hơn, phải tính từ đầu khi thiết kế B2.
- **Khối ngoại** — chờ nguồn (§1.1).
- **Mảng C** — cảnh báo theo sự kiện, hộ tiêu thụ đầu tiên của `raw_corporate_event`.
