# A2 & A3 — Kết quả nghiệm thu & Nợ kỹ thuật

> Hoàn tất: A2 merge qua PR #3 (`35f09fd`), A3 merge qua PR #4 (`175ca19`).
> Tiếp nối `docs/A1-ket-qua-va-no-ky-thuat.md`. Tài liệu này giữ lại những gì
> git log không nói được: **vì sao** các quyết định được đưa ra, và **những gì
> còn nợ**.
>
> Nguồn: `.superpowers/sdd/2026-08-09-a2-dbt-marts-va-cham-diem/progress.md`
> (git-ignored, chỉ có trên máy local) + git log nhánh `feat/a3-mcp-server`.
> **Ledger A3 không tồn tại** — phần A3 dưới đây dựng lại từ plan + commit message.

---

# PHẦN I — A2: dbt marts & bộ chấm điểm

## 1. Nghiệm thu — 9/10 đạt

| # | Tiêu chí | Kết quả |
|---|---|---|
| 1 | pytest pass | ĐẠT — 129 passed (lúc merge A2) |
| 2 | `dbt build` sạch | ĐẠT — PASS=111, ERROR=0 |
| 3 | `assert_no_bank_sentinel_leak` pass | ĐẠT |
| 4 | ≥800 mã có ≥3/5 điểm thành phần | ĐẠT — 1.508 mã |
| 5 | ≥20 ngân hàng có `quality_score` > 0 | ĐẠT — **29/29** |
| 6 | 3 profile cho 3 danh sách khác nhau | ĐẠT |
| 7 | `bluechip_dividend` ≥3 ngân hàng trong top 30 | ĐẠT — **5 ngân hàng** |
| 8 | Doanh thu/LNST suy ra của HPG 2024 khớp BCTC ±2% | ĐẠT — LNST lệch **0,008%**, doanh thu lệch 1,2% |
| 9 | Đo tỉ lệ NULL `car`/`casa_ratio` | ĐẠT — `car` NULL 29/29 → loại khỏi seed; `casa_ratio` giữ |
| 10 | Workflow weekly xanh trên GitHub | **CHƯA XÁC NHẬN** — chỉ chạy theo lịch T7 hoặc `workflow_dispatch` |

Tiêu chí #7 là **phép thử trực tiếp cho toàn bộ công việc khử sentinel của A1**.
Ở A1, 187/187 dòng ngân hàng có `roic = 0` và `current_ratio = 0` vì sentinel giả.
Không khử thì cả 29 ngân hàng bị chấm bét bảng và **biến mất khỏi mọi khuyến nghị**.

Quy mô: 34 commit, 61 file, +3.489 dòng.

---

## 2. Sentinel giả có BA TRỤC, không phải một

Đây là phát hiện xuyên suốt A2. A1 mới xử lý trục thứ nhất.

| Trục | Biểu hiện | Phát hiện ở |
|---|---|---|
| **1. Loại hình DN** | Ngân hàng có `roic=0`, `current_ratio=0` (chỉ tiêu NONFIN không áp dụng) | A1 |
| **2. Kỳ báo cáo** | `car=0` ở 223/224 dòng Q1, `debt_to_equity=0` ở 207/207 dòng NĂM. VCB 2024: D/E 9,2–9,6 ở Q1–Q4 nhưng **0,0000** ở dòng năm → ngân hàng bị đọc là "không đòn bẩy", tức điểm tốt nhất có thể | Task 2 |
| **3. Âm vốn chủ sở hữu** | `roe = 0` ở 1.661 dòng. DN lỗ không thể có ROE đúng bằng 0. APT/JOS/HLA có `roa = −6,2`, biên LN −4,3, `debt_per_equity` **âm** (vốn chủ âm) mà `roe = 0` | Task 8.5 (V7) |

**Tác động đo được của trục 3:** `median_roe` thấp có hệ thống ở 7 nhóm ngành —
ngành 5700 lệch **−39%**, ngành 2300 lệch −22%. Nặng hơn ở tầng chấm điểm:
DN **mất sạch vốn chủ** được xếp hạng chất lượng **cao hơn** DN có ROE thấp nhưng
dương — đảo ngược thứ tự.

### Cái bẫy khi sửa

`dividend_yield = 0` có **38.112 dòng** và là giá trị **THẬT** (phần lớn DN Việt
không trả cổ tức trong quý). Áp `nullif(x, 0)` bừa lên mọi cột là xoá 38.112 điểm
dữ liệu thật và làm sập thành phần điểm cổ tức.

→ Task 8.5 chia ba nhóm cột A/B/C và có **hai test canh hai chiều ngược nhau**:
`assert_no_impossible_zero` (còn sót sentinel) và `assert_real_zeros_preserved`
(NULL hoá quá tay). **Một test một chiều là không đủ cho loại sửa này.**

### Phát hiện thêm: `com_class` phải có bốn giá trị, không phải ba

Brief ban đầu viết "OTHERFIN chỉ dùng nhóm chỉ tiêu COMMON" — **sai với 14/15 chỉ
tiêu**. Kiểm raw: bảo hiểm 478/478 dòng và chứng khoán 1.396/1.402 dòng có
`roic`/`current_ratio`/`ebit` **thật**. Chỉ `days_inventory_outstanding` mới thật
sự N/A. Nếu không bắt: **~26.000 ô bị xoá oan**.

Không test nào bắt được, vì cả 3 test hiện có đều lọc `BANK`/`NONFIN`/`UNKNOWN` —
OTHERFIN nằm ngoài phạm vi mọi test. → thêm `metrics_otherfin` + test
`assert_otherfin_metrics_present`.

---

## 3. Lỗi nặng nhất: "cửa sổ theo DÒNG thay vì theo LỊCH"

`lag(x, 4)` / `lag(x, 12)` lấy theo **vị trí dòng**, không theo **lịch**.
Nhưng **1.378/1.585 mã (87%)** có khoảng trống trong chuỗi quý — riêng 2021 Q2
chỉ có 177/1.585 mã báo cáo.

Hệ quả đo trên production:

| Phép đo | Kết quả |
|---|---|
| `revenue_yoy` **lật dấu** tăng trưởng | 12.407/23.268 dòng (**53%**) |
| Lệch > 20 điểm phần trăm | 13.376 dòng (57%) |
| `revenue_cagr_3y` lẽ ra phải NULL | 12.066/19.241 (62,7%) |

Sửa: thay `lag()` bằng self-join theo `(symbol, year−N, quarter)`; các cửa sổ
`rows between` đổi sang `range` trên `abs_quarter`.

**Sau khi sửa xong Task 4, controller chủ động rà toàn bộ plan tìm cùng lớp lỗi**
và tìm thấy 2 chỗ nữa (`int_quality_metrics` cửa sổ 8 quý, `int_valuation_percentile`
cửa sổ 20 quý) — sửa **trước** khi giao việc. Task 5 sau đó là task đầu tiên của A2
được duyệt ngay vòng đầu, 0 Critical.

> **Bài học:** khi tìm ra một lớp lỗi, đừng chỉ sửa chỗ vừa tìm thấy — **rà cả
> codebase tìm cùng hình thái** trước khi làm tiếp.

---

## 4. Năm lỗi tương tác — chỉ hiện ở review TOÀN NHÁNH

Cả 13 task đều qua review riêng và **đều đạt**. Vòng review cuối cùng vẫn tìm ra
**1 Critical + 4 Important**.

### Hình thái chung của cả 5 lỗi

> Một task **sau** NULL hoá hoặc siết một cột; một model viết ở task **trước** vẫn
> đọc theo giả định cũ. **Mỗi bên đọc riêng đều đúng hoàn toàn** — đó là lý do 13
> vòng review từng-task không thể thấy.

**CRITICAL — `int_metric_long` không áp `pe_meaningful`/`pb_meaningful`.**
Model này (Task 5) viết **trước** khi bài học `pe_meaningful` được rút ra ở Task 6.
Với chỉ tiêu `direction='lower'`, số **âm** nhận phân vị ≈0 → sau khi đảo chiều
thành điểm gần tuyệt đối. Nghĩa là **P/E âm được chấm là "rẻ nhất thị trường"**:

- 206 mã có `value_score` lẽ ra phải NULL; 86 mã trong đó ≥80 điểm
- **KSH: 99,3 điểm với `pe = −419`**
- **DAC: 81,6 điểm dù âm vốn chủ**, sát MBB (83,2)
- Ô nhiễm cả rổ so sánh: **1.193/1.266 mã sạch bị dìm điểm** (TB +3,64 nếu sửa)
- **Đổi kết quả đầu tư thật:** `bluechip_dividend` đổi hạng 1 SSI→FPT;
  `deep_value` có 15 mã đổi ≥3 bậc

**IMPORTANT 1 — `earnings_yoy` tính qua mốc gốc ÂM.** Cùng model có rào chắn cho
`earnings_cagr_3y` nhưng **không có** cho YoY, cách nhau 5 dòng. **37 mã đang lỗ
mà nhận YoY dương** — TSC lỗ 36 tỷ, YoY +93,9, `pct_peer` = 1,000 (cao nhất rổ).

**IMPORTANT 2 — dòng NĂM thừa hưởng số liệu quý 4.** `fct_financial_quarterly` đọc
`stg_financial_ratio` không lọc `quarter`, rồi join chỉ theo `period_end_date` — mà
dòng năm và quý 4 **dùng chung ngày 31/12**. `earnings_ttm` lệch ở **95,1%** dòng
năm, trung vị 25,3%. *Chính comment trong `stg_financial_ratio` dòng 24-28 đã cảnh
báo phải lọc `period_type`.*

**IMPORTANT 3 — bản sửa Task 8.5 thổi phồng chuỗi năm cổ tức.** NULL hoá
`dividend_yield` làm 686 dòng trắng **biến mất** khỏi `int_dividend_history` — mà
đó chính là dòng `last_zero_year` dùng để **cắt** chuỗi. **VOC: 0 → 7 năm**, BBC 0 → 5.
Sai ở cả hai đường: `dividend_years_consecutive` vừa là 30% thành phần cổ tức, vừa
là bộ lọc cứng `dividend_years_min`.

**MINOR → Important khi xét toàn mảng.** `loss_quarters_12q` đọc NULL thành "không
lỗ": 360 mã báo "0 quý lỗ" với <8 quý dữ liệu. ALC có 2 quý dữ liệu → điểm an toàn
74,2. Sau sửa: 67,9.

### Kết quả âm cũng có giá trị

Nghi vấn ưu tiên **số 1** của controller (mart lệch kỳ giữa các bảng nguồn) hoá ra
**SAI**: 1.585/1.585 mã trùng khít, 0 lệch — và đó là bảo đảm **cấu trúc**, không
phải trùng hợp dữ liệu. Ghi lại để không ai đi điều tra lại.

---

## 5. Ba lần "một con số cần được phơi kèm bằng chứng đỡ nó"

Cùng một hình thái lặp lại **bốn** lần trong A2:

| Lần | Con số | Vấn đề | Bằng chứng phải phơi kèm |
|---|---|---|---|
| T6 | `pe_pct_own_5y` | Không biết tính trên bao nhiêu quý | `pe_quarters_used` / `pb_quarters_used` |
| T8 | `median_pe` ngành | Không biết tính trên bao nhiêu mã | `n_pe` / `n_pb` / `n_roe` |
| T10 | 5 điểm thành phần | Không biết dựa trên bao nhiêu trọng số thật | `*_weight_coverage` |
| T11 | `rejected_counts` | Chỉ ghi lý do **đầu tiên** | `rejected_total` + đếm chồng lấp |

> **Mỗi lần đều cùng một hình thái: con số trông có thẩm quyền hơn bằng chứng đỡ nó.**

### Ví dụ T11 — con số không bịa nhưng dẫn tới kết luận sai hoàn toàn

85,5%–96,4% mã bị loại trượt từ **2 điều kiện trở lên**, nhưng code chỉ ghi lý do đầu:

| Điều kiện (`bluechip_dividend`) | Bảng cũ | Sự thật |
|---|---|---|
| thanh khoản < 5 tỷ/phiên | 26 | **1.420** |
| vốn hoá < 5.000 tỷ | 517 | **1.417** |
| cổ tức < 3 năm | 73 | **1.146** |
| ROE 8 quý < 12% | 6 | **1.077** |

Bảng cũ khiến người đọc kết luận *"thanh khoản gần như không cản ai (26 mã)"*.
Sự thật ngược lại: **thanh khoản là điều kiện chặt nhất**, cản 1.420/1.589 mã —
tức sàn Việt Nam chỉ có ~169 mã giao dịch trên 5 tỷ/phiên. Tổng vẫn ra đúng 1.564
nên không con số nào "sai", nhưng dùng nó để kết luận thì sai hoàn toàn.

---

## 6. Lỗi lớn nhất A2 — chặn được TRƯỚC khi giao việc

Cổng chặn trong kế hoạch gốc: `metrics_used * 2 >= count(*)`. **Van luôn mở** —
chỉ tiêu vắng mặt hoàn toàn không sinh dòng nào nên tự biến mất khỏi **cả tử số lẫn
mẫu số**.

Mô phỏng trên production: **617 cặp (mã, thành phần) lọt lưới**.

Ca tệ nhất: QLD, SDY, HFX, VHH, VMT, PLA, VGL, LMC chỉ có `growth_consistency`
(trọng số 0,10). Vì điểm được chuẩn hoá lại trên phần trọng số dùng được, chúng
nhận **`growth_score` = 100/100** dù **không có một dòng doanh thu hay lợi nhuận nào**.

> Không phải lệch số — mà là **tự tin tối đa từ bằng chứng tối thiểu**, và nó đẩy
> đúng mã rác nhất lên đầu bảng xếp hạng tăng trưởng.

Sửa: lấy tổng trọng số **định nghĩa** từ seed làm mẫu số. Sau sửa: **0 lọt lưới**,
mà vẫn giữ 1.552 mã đạt ≥3/5 (cổng cũ 1.573).

---

## 7. Nợ kỹ thuật A2 còn lại

| # | Nợ | Mức |
|---|---|---|
| **N14** | Chưa từng chạy `dbt build` **thật** trên DuckDB local — chỉ `dbt compile` (107/107 node). Ràng buộc "chạy được cả hai engine" mới chứng minh ở mức **biên dịch**, chưa ở mức **kết quả** | Trung bình |
| **N15** | Tiêu chí #10: workflow weekly chưa từng chạy xanh trên GitHub — cần chủ repo kích hoạt `workflow_dispatch` | Trung bình |
| **N16** | `regr_slope()` trả **NaN** (không phải NULL) trên 1.727/36.676 dòng, phơi thẳng ra `fct_financial_quarterly`. Model nào đọc thẳng có thể bị NaN đầu độc `avg()` | Trung bình |
| **N17** | `dividend_years_consecutive` chưa cắt chuỗi khi một năm **vắng mặt hoàn toàn** (khác với năm có dữ liệu nhưng = 0) | Thấp |
| **N13** | 3 mã (DPD, PYU, TAC) có giá nhưng VCI không phục vụ hồ sơ. `has_profile` chưa được phơi ra scorecard | Thấp |
| — | `assert_price_in_vnd_range` có lỗ: nếu **TOÀN BỘ** lịch sử một mã bị chia 1000 thì test "bắt đứt gãy" không thấy. Đề xuất: dùng khối lượng giao dịch để phân biệt (vỏ công ty thật có KL 1-5 cp/phiên) | Thấp |
| — | Mã phantom-quote (volume=0 xen kẽ) vẫn cho `return_1m/3m` vô nghĩa (NSS: −67,5%). Nghi phạm đầu tiên nếu thấy `sector_return_3m` lệch bất thường | Thấp |

---

# PHẦN II — A3: MCP server

## 8. Nghiệm thu — 7/8 đạt

| # | Tiêu chí | Kết quả |
|---|---|---|
| 1 | pytest pass | ĐẠT |
| 2 | 7 tool đăng ký đầy đủ | ĐẠT |
| 3 | Cả 7 tool trả dữ liệu thật | ĐẠT — `scripts/check_mcp_tools.py` |
| 4 | `run_sql` từ chối DDL/DML | ĐẠT |
| 5 | Mọi tool trả kèm `as_of` và `data_quality` | ĐẠT |
| 6 | `compare_stocks` cảnh báo khi khác `com_class` | ĐẠT |
| 7 | Agent trả lời đúng luật trong Claude Code thật | **CHƯA XÁC NHẬN** — cần phiên tương tác, không tự động hoá được |
| 8 | Xoá `.mcp.json` không ảnh hưởng warehouse/bản tin | ĐẠT |

Bộ test hiện tại (đã chạy lại khi viết doc này): **213 passed, 2 xfailed**.

---

## 9. Hành trình rào chắn SQL — 6 lần viết lại

Đây là phần đáng học nhất của A3. Rào chắn `run_sql` được viết lại **sáu lần**,
mỗi lần vì một lớp tấn công mới:

| Commit | Cách tiếp cận | Vì sao bỏ |
|---|---|---|
| `be70597` | Khung ban đầu | — |
| `f308745` | Chặn đọc file hệ thống | False-positive |
| `e5f7d40` | Chặn `checkpoint()` qua **regex cú pháp** | Regex không hiểu SQL |
| `6487469` | **Parser thật** `duckdb.extract_statements()` | Bước nhảy đúng hướng |
| `8915600` | Danh sách hàm hữu hạn | Không phủ hết |
| `85fd557` | **`EXPLAIN (FORMAT JSON)`** thay vì đoán tên hàm | Đúng tầng |
| `d46ad69` | **Đảo blocklist → allowlist** | Blocklist luôn thua |

> **Bài học kinh điển:** blocklist (chặn cái xấu đã biết) luôn thua allowlist
> (chỉ cho cái tốt đã biết). Và **đừng đoán cú pháp bằng regex khi có parser thật.**

### Giới hạn còn lại — được ghi nhận công khai, không giấu

`EXPLAIN`-based guard chỉ đọc `extra_info.Function` của node **table-function**, nên
**hàm vô hướng** (dùng trong `SELECT`) không bao giờ lọt vào diện được kiểm. Đây là
**giới hạn kỹ thuật thật**, không phải sơ suất.

Cách xử lý — đúng tầng phòng thủ:
1. Ghi rõ trong `mcp_server/instructions.md` để agent tự kiềm chế
2. Giữ test `xfail` đánh dấu lỗ hổng đã biết (`test_scalar_function_is_not_blocked_known_gap`)
3. **Nợ còn treo:** tạo token MotherDuck **read-only/scoped** riêng — đây mới là lớp
   phòng thủ đúng tầng cho rủi ro này

---

## 10. Lớp lỗi A3: "test gọi sai tầng"

**I1 — 4 task liên tiếp không phát hiện được một crash thật.**

`run_sql` là tool **duy nhất** trả thẳng dòng thô từ `db.run_query` mà không qua
`tools._clean()`. Cột DATE NULL (`pandas.NaT`) làm FastMCP **crash thật** khi
serialize JSON — và crash xảy ra **SAU khi hàm return**, nên `_safe_tool` không bắt được.

Vì sao 4 task không thấy: **mọi test cũ gọi hàm Python trần** (`server.run_sql(...)`),
đi vòng qua tầng serialize JSON thật của FastMCP.

→ Sửa: thêm test gọi **đúng qua `server.mcp.call_tool()`**.

**I2 — fixture lệch schema production.** `get_sector_snapshot` thiếu 3 cột
`n_pe`/`n_pb`/`n_roe` suốt 4 task, vì bảng giả trong `conftest_mart.py` **cũng thiếu
đúng 3 cột đó**. Fixture sai giống hệt code sai nên test luôn xanh.

→ Sửa: fixture phải khớp schema thật, và **cố tình đặt `n_pe` (32) < `n_symbols` (40)**
để mô phỏng đúng ca lệch mà A2 đã đo trên production (17/21 nhóm).

**I3 — Global Constraint chưa từng được cài đặt.** Plan A3 ghi "timeout 30 giây".
Giới hạn 1.000 dòng đã có; **timeout thì chưa**. Không ai kiểm chéo constraint với
code cho tới vòng review cuối.

> **Bài học:** một test chỉ chứng minh được điều gì đó nếu nó chạy qua **đúng tầng
> mà lỗi xảy ra**, và fixture của nó **không mang cùng lỗi với code**.

---

# PHẦN III — Bài học quy trình (áp cho mảng B/C/D)

## 11. Bốn lần "thứ sai chính là cái test"

| Lần | Test | Nó đo gì | Thật ra phải đo gì |
|---|---|---|---|
| T1 | `assert_price_in_vnd_range` | Sàn giá tuyệt đối | **Đứt gãy trong cùng một mã** (bắt lệch đơn vị ×1000) |
| T4 | `assert_derived_revenue_sanity` | 0,94% dòng ngoài dải | **Trung vị toàn thị trường** (lỗi công thức sai trên MỌI dòng) |
| T6 | Test biên `[0,1]` | Phân vị trong biên | 0,839 vẫn "trong biên" nhưng gán cho `pe = −9.126` |
| T11 | `test_screen_report_...` | Không thể đỏ | Fixture chỉ có 1 mã bị loại với 1 lý do → cả logic cũ và mới cho cùng kết quả |

> **Khi test fail, hỏi "test này có đo đúng thứ nó sinh ra để đo không" TRƯỚC KHI
> hỏi "làm sao cho nó xanh".**

### Quy tắc rút ra (Task 8.5)

> **Mọi test mới thêm vào để canh một lỗi đều phải được chứng minh bằng cách chạy
> trên TRẠNG THÁI LỖI, không chỉ trên trạng thái đã sửa.**

Re-reviewer Task 8.5 đã làm đúng vậy: dựng lại cấu trúc SELECT lỗi cũ, chạy test mới
lên đó → ra đúng 686 và 1.797 dòng lệch, khớp số liệu lỗi đã báo. **Đây là cách duy
nhất chứng minh một test không phải "luôn xanh".**

## 12. Bài học lớn nhất của dự án — implementer cứu controller

Task 4, chuỗi sự kiện:

1. **Reviewer sai:** báo "HPG 2022Q4 đúng phải là +18,88%"
2. **Controller lan truyền** số sai đó vào chỉ thị sửa
3. **Implementer từ chối sửa** — tra BCTC công bố và chứng minh:
   HPG 2021Q4 = 149.680 tỷ, 2022Q4 = 141.409 tỷ → YoY đúng = **−5,53%** (đúng cái
   model đang cho ra). Con số +18,88% là so với năm **SAU** — reviewer lỗi dấu năm.
   Khớp thực tế: HPG 2022 doanh thu giảm 5,5%, LNST giảm ~75% (chu kỳ thép).

> **Nếu implementer nghe lời, ta đã cố ý cài lại đúng lớp lỗi đang sửa — và không ai
> bắt được, vì cả reviewer lẫn controller đều đã "xác nhận".**

Hiện tượng này lặp lại ở Task 6: implementer bắt được **2 con số sai** nữa của
controller (mẫu số percentile phải là *số quý hợp lệ − 1*, không phải tổng số dòng).

**Hệ quả cho quy trình:** vai trò kiểm chứng phải **độc lập**, không phải tuần tự.
Người thực thi có quyền — và có nghĩa vụ — từ chối một chỉ thị sai, kèm bằng chứng.

## 13. "Tác động = 0" phải hỏi: đo ở ĐÂU?

`mart_data_quality.has_required_metrics` dùng `else 1` cho 54 mã OTHERFIN: tự động
đạt mà không kiểm gì, nhưng vẫn ăn trọn **15% trọng số**.

Ở Task 9, controller ghi nợ với lý do *"sửa hay không cũng không đổi điểm mã nào hôm
nay"* — đã đo, cả 54 mã đều có `roic`. Lập luận đúng nhưng **thiếu**:

`data_quality_score` **không dừng ở `mart_data_quality`**. Nó chảy vào
`mart_stock_scorecard` **và** vào ngưỡng lọc `min_data_quality_score` của screener
trong `src/scoring.py`. Nên 15 điểm cho không **có thể đẩy một mã qua mốc 60** và lọt
vào danh sách khuyến nghị.

> **Khi phán quyết "tác động = 0", phải hỏi *tác động đo ở đâu*.** Đo ở bảng chứa nó
> là không đủ — phải đo ở **nơi giá trị đó chảy tới**.

Đây cũng là lý do reviewer Task 9 gắn nhãn Minor (chỉ nhìn phạm vi task mình), còn
xét toàn mảng thì là Important.

## 14. Các bẫy công cụ đã gặp

| Bẫy | Biểu hiện | Cách tránh |
|---|---|---|
| **dbt partial parse cache** | `target/partial_parse.msgpack` tạo **GREEN GIẢ** ngay sau RED — test mới bị âm thầm bỏ khỏi `dbt list`. Gặp ở cả Task 2 và Task 6 | Chạy `--no-partial-parse` (hoặc xoá `target/`) khi chuyển RED→GREEN |
| **`--select tag:daily`** | Chỉ 4 model có tag `daily`, nhưng 4 model hạ nguồn cũng đọc dữ liệu giá mà **không** có tag → mart trễ 1 phiên. **Không test nào bắt được** — mỗi bảng tự nó nhất quán, chỉ quan hệ giữa chúng sai | Workflow chạy `dbt build` **toàn DAG** (111 giây, không có lý do tiết kiệm) |
| **Thiếu `motherduck_token`** | Bước đó âm thầm ghi vào file DuckDB **local của runner** rồi mất khi runner tắt — **mà job vẫn xanh** | Mọi bước có `WAREHOUSE_DB: md:vn_market` phải kèm token |
| **Logic ba trị của SQL** | `pe_meaningful = false` bỏ sót 374 dòng `IS NULL` | `coalesce(x, false) = false` |
| **Alias trùng tên trong DuckDB** | `pb_meaningful` viết `(pb > 0 ...)` phân giải về cột raw **trước** `nullif` → 1.797 dòng sai | Tách bậc CTE: mọi NULL hoá ở `nulled`, suy diễn cờ ở SELECT ngoài |
| **`printf('%.0f', ...)` với BIGINT** | DuckDB đòi kiểu thực | `cast(... as varchar)` |
| **Máy dev che giấu phụ thuộc** | `pytest` chưa từng có trong `requirements.txt` — máy dev có vì cài tay từ trước. CI đỏ ngay lần chạy đầu | Mô phỏng CI bằng venv sạch + `env -i` |

## 15. Bài học chốt

**Lỗi sinh ra từ chính bản sửa lỗi.** Task 8.5 NULL hoá cột nguồn, nhưng cờ suy diễn
đọc cột raw → bản sửa tạo bất nhất mới ở nơi trước đó nhất quán. Rồi chính Task 8.5
lại gây IMPORTANT 3 (thổi phồng chuỗi cổ tức).

> **Cứ NULL hoá một cột là phải rà mọi cột suy diễn đọc nó — và mọi model hạ nguồn
> phụ thuộc vào sự tồn tại của dòng đó.**

**Lần theo mọi quan sát dạng "chỉ tiêu này gần như không bao giờ NULL".** Trục
sentinel thứ ba (§2) được phát hiện từ một **Minor** của reviewer — chỉ là quan sát
phụ `n_roe = n_symbols`. Nó thường nghĩa là **NULL đang bị ghi thành 0**.

**Ghi chú xử-lý-sự-cố trong plan cũng cần được kiểm chứng như code.** Dòng "nếu test
fail thì chạy monthly rồi build lại" nghe hợp lý, nhưng nếu implementer làm theo thì
test vẫn fail (DPD/PYU/TAC không có nguồn ở VCI) và **lỗi thiết kế thật bị che thêm
một lớp**.

---

## 16. Việc cần làm tiếp

**Chặn merge / ưu tiên cao — không có.** Mảng A đã merge đủ.

**Nên làm trước khi bắt đầu mảng B:**
1. Tạo token MotherDuck **read-only/scoped** cho MCP server (lớp phòng thủ đúng tầng
   cho lỗ hổng hàm vô hướng, §9)
2. Đóng tiêu chí A3 #7 — chạy 3 câu hỏi mẫu trong Claude Code thật
3. Đóng tiêu chí A2 #10 — kích hoạt `warehouse-weekly.yml` bằng `workflow_dispatch`
4. Chạy `dbt build` **thật** trên DuckDB local một lần (N14)

**Nợ mang theo:** N1, N3, N5, N6, N7, N9, N10, N11, N12 (từ A1) + N13–N17 (bảng §7).

**Spec mảng tiếp theo** nằm ở cuối `docs/superpowers/plans/2026-08-09-a3-mcp-server.md`:
**B** — BCTC chi tiết, sự kiện & cổ tức, khối ngoại ·
**C** — báo cáo luận điểm định kỳ + cảnh báo theo sự kiện ·
**D** — vĩ mô + kho tin & cơ chế scan.
