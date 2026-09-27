# Lộ trình đọc hiểu mảng A — từ API vnstock tới câu trả lời hội thoại

> Mục tiêu: hiểu **toàn bộ luồng dữ liệu hiện tại** (sau pivot 2026-08), không chỉ
> "code làm gì" mà "vì sao làm vậy" và "bài học DE nào rút ra được".
>
> Ước lượng: ~12 giờ đọc, chia 14 ngày × 1-2 giờ. Tick vào ô khi xong.

---

## ⚠️ Đọc cái này trước khi mở bất kỳ file nào

**`docs/learning/01-08` mô tả hệ thống CŨ, trước pivot.**
Commit cuối của thư mục đó là **2026-06-11**; plan mảng A bắt đầu **2026-08-10**.
Chúng nói về `main.py` / RSI / MA / bản tin Telegram — vẫn tốt để học *khái niệm
nền* (API, rate limiting, DuckDB, pytest, GitHub Actions), nhưng **không phải
luồng hiện tại**.

| File | Trạng thái |
|---|---|
| `docs/learning/01-08` | Hệ thống cũ — đọc để học khái niệm, không để hiểu luồng nay |
| `docs/architecture-v2.html` | **Lỗi thời** — mô tả hệ thống trước pivot |
| `docs/architecture-v3.html` | ✅ Đúng hiện tại |
| `docs/DESIGN.md` §5.1 | Đã sửa khớp schema thật (trả nợ N8, commit `d68e9d0`) |

---

## Chặng 0 — Bản đồ tổng thể (~45 phút)

- [ ] **`README.md`** — đọc kỹ block ASCII dòng 11-18: INGESTION → WAREHOUSE → CONSUMERS
- [ ] **`docs/architecture-v3.html`** — mở bằng browser. 6 lớp:
      RAW → STAGING → INTERMEDIATE → MARTS → SCORING → outputs
- [ ] **`docs/superpowers/specs/2026-08-09-fundamental-analysis-platform-design.md`** (671 dòng)
      — **cái WHY của cả mảng A**. Vì sao tách `com_class`, vì sao percentile
      trong nhóm tương đương, vì sao không đưa khuyến nghị mua/bán

**Kiểm tra hiểu bài:** trả lời được câu *"dữ liệu đi từ API vnstock tới câu trả
lời 'top 10 bluechip' qua bao nhiêu lớp, mỗi lớp làm gì?"*

---

## Chặng 1 — A1: Nền dữ liệu (~3 giờ)

### 1.1 Đọc doc retro TRƯỚC khi đọc code

- [ ] **`docs/A1-ket-qua-va-no-ky-thuat.md`** — tài liệu giá trị nhất repo cho việc
      học DE. Ghi lại 5 giả định sai về dữ liệu nguồn + 12 khoản nợ kỹ thuật,
      kèm *lý do*. Git log không nói được những thứ này.

### 1.2 Đọc code theo chiều dữ liệu chảy

```
config/warehouse.yml  →  src/ingest_market.py  →  src/warehouse.py  →  build_warehouse.py
   (cấu hình)             (gọi API vnstock)        (DuckDB read/write)   (điều phối 3 cadence)
                                                          ↓
                                            scripts/reconcile_warehouse.py  (cổng kiểm chứng)
                                                          ↓
                                            .github/workflows/warehouse*.yml (lập lịch)
```

- [ ] **`config/warehouse.yml`** (26 dòng) — nợ **N4**: khối `exchanges` chưa từng
      có tác dụng → universe gồm cả UPCOM (1.598 mã thay vì ~750)
- [ ] **`src/ingest_market.py`** (471 dòng) — rate limiting, column normalization.
      Chú ý chỗ `_normalize_*` từng nằm ngoài `try` → một mã bất thường xoá sổ
      cả mẻ 1.598 mã
- [ ] **`src/warehouse.py`** (501 dòng) — pattern upsert, `_ensure_columns`.
      Nợ **N10**: `upsert_prices` khớp theo *vị trí* cột, không liệt kê tên →
      thêm cột sẽ ghi lệch cột im lặng
- [ ] **`build_warehouse.py`** (119 dòng) — `--mode daily/weekly/monthly`.
      Multi-cadence: giá mỗi ngày, tỷ số mỗi tuần, hồ sơ DN mỗi tháng
- [ ] **`scripts/reconcile_warehouse.py`** — cổng gác dữ liệu. Đọc kèm §4 của doc
      A1: *"cổng kiểm chứng cũng cần được kiểm chứng"*
- [ ] **`.github/workflows/warehouse.yml`**, `warehouse-weekly.yml`, `warehouse-monthly.yml`

**Thực hành:** chạy `python build_warehouse.py --mode daily` và đọc log.

---

## Chặng 2 — A2: dbt marts + chấm điểm (~5 giờ, phần nặng nhất)

Đây là trái tim hệ thống. **Đọc theo thứ tự DAG, không theo alphabet.**

### 2.1 Khung dbt

- [ ] `transforms/dbt_project.yml`
- [ ] `transforms/profiles.yml`
- [ ] `transforms/models/staging/_sources.yml` — khai báo bảng `raw_*` từ A1

### 2.2 Staging — chuẩn hoá, đổi tên, ép kiểu (5 model)

- [ ] `stg_price_daily.sql`
- [ ] `stg_financial_ratio.sql`
- [ ] `stg_company_info.sql`
- [ ] `stg_industry.sql`
- [ ] `stg_index_daily.sql`

### 2.3 Macro — ĐỌC TRƯỚC intermediate

- [ ] **`transforms/macros/applicable_metrics.sql`** — **chìa khoá của cả thiết kế**.
      Quyết định BANK dùng NIM/NPL/CIR/CAR/CASA còn NONFIN dùng ROIC/current_ratio.
      Không hiểu file này thì không hiểu phần còn lại.

### 2.4 Intermediate — nơi logic khó nằm (7 model)

- [ ] `int_fundamentals_ttm.sql` — gộp 4 quý trượt
- [ ] **`int_metric_long.sql`** — pivot wide→long, 50 cột thành cặp (metric, value).
      Kỹ thuật DE quan trọng: xử lý N chỉ tiêu bằng 1 đoạn SQL thay vì N đoạn
- [ ] `int_metric_percentile.sql` — percentile trong nhóm `com_class + icb_lv2`
- [ ] `int_quality_metrics.sql` — độ bền ROE, sentinel handling
- [ ] **`int_valuation_percentile.sql`** — P/E so với **chính mã 5 năm qua**
      (khác hẳn percentile ngành — đừng nhầm hai cái)
- [ ] `int_dividend_history.sql` — chuỗi năm trả cổ tức liên tiếp
- [ ] `int_price_features.sql` — thanh khoản 20 phiên, biến động

### 2.5 Marts — nơi mọi consumer query vào (8 model)

- [ ] **`mart_stock_scorecard.sql`** ← đọc kỹ nhất. 5 điểm thành phần
      (value/quality/growth/dividend/safety)
- [ ] `mart_valuation_band.sql`
- [ ] `mart_sector_snapshot.sql`
- [ ] `mart_data_quality.sql`
- [ ] `dim_stock.sql`, `dim_industry_hierarchy.sql`
- [ ] `fct_price_daily.sql`, `fct_financial_quarterly.sql`

### 2.6 25 dbt test — đọc TÊN FILE là hiểu rủi ro

- [ ] Duyệt qua `transforms/tests/` — mỗi test là một lỗi từng xảy ra hoặc suýt
      xảy ra. **Cách học data quality nhanh nhất trong repo.**

Vài cái đáng đọc nội dung:

| Test | Bắt lỗi gì |
|---|---|
| `assert_no_bank_sentinel_leak.sql` | Sentinel `0.0` giả rò vào nhóm ngân hàng |
| `assert_percentile_only_on_meaningful_periods.sql` | Percentile tính trên cửa sổ quá mỏng |
| `assert_dividend_streak_breaks_on_unknown.sql` | Chuỗi cổ tức nối sai qua năm thiếu dữ liệu |
| `assert_price_in_vnd_range.sql` | Lệch đơn vị ×1000 (xem ghi chú Task 1 ở Chặng 4) |
| `assert_scoring_weights_sum_to_one.sql` | Trọng số profile không cộng đủ 1.0 |

### 2.7 Tầng chấm điểm — tách khỏi dbt có chủ đích

- [ ] **`config/scoring_profiles.yml`** (61 dòng) — trọng số + điều kiện lọc
- [ ] **`src/scoring.py`** (226 dòng) — áp trọng số **lúc đọc**, nên sửa "gu" đầu
      tư xong chạy lại trong vài giây, không cần `dbt run` lại

**Thực hành:**
```bash
export WAREHOUSE_DB=md:vn_market
cd transforms && dbt build           # thấy DAG thật chạy
dbt docs generate && dbt docs serve  # xem đồ thị phụ thuộc trực quan
```

---

## Chặng 3 — A3: MCP server (~2 giờ)

- [ ] **`mcp_server/instructions.md`** — luật ràng buộc agent (không bịa số, luôn
      nêu `as_of` / `peer_basis`). Đây chính là nội dung agent nạp vào context
      mỗi phiên
- [ ] **`mcp_server/server.py`** (163 dòng) — đăng ký 7 tool, vòng đời server
- [ ] **`mcp_server/tools.py`** (387 dòng) — logic 7 tool + tầng `facts`
      (diễn giải số sẵn để agent không tự tính số mới)
- [ ] **`mcp_server/db.py`** (292 dòng) — **rào chắn SQL**, allowlist dựa trên
      `duckdb.extract_statements()` / `EXPLAIN`
- [ ] `tests/test_mcp_db.py` — đặc biệt các test bảo mật
- [ ] `tests/test_mcp_tools.py`, `tests/test_mcp_server.py`
- [ ] `.mcp.json` — hiểu vì sao đây là **local stdio server**, không dùng được
      từ app Claude trên điện thoại (cần remote HTTP transport mới dùng được)

**Thực hành:** gọi từng tool trong Claude Code, đối chiếu output với code trong
`tools.py`.

---

## Chặng 4 — Nhật ký thi công: học *quy trình*, không phải code (~1 giờ)

Phần ít người nghĩ tới nhưng giá trị cao. Ledger ghi lại **tranh luận và quyết
định**, thứ mà code cuối cùng đã xoá dấu vết.

- [ ] `.superpowers/sdd/2026-08-09-a1-nen-du-lieu-co-ban/progress.md` (341 dòng)
- [ ] `.superpowers/sdd/2026-08-09-a2-dbt-marts-va-cham-diem/progress.md` (1.070 dòng)
- [ ] `docs/A2-A3-ket-qua-va-no-ky-thuat.md` — doc retro A2/A3

> **Lưu ý:** ledger A3 không tồn tại trên máy (`.superpowers/sdd/` git-ignored,
> chỉ có A1 và A2). Kiến thức A3 nằm ở
> `docs/superpowers/plans/2026-08-09-a3-mcp-server.md` (1.195 dòng) — cuối file
> này cũng chứa **spec mảng B / C / D** sắp tới.

### Ví dụ đáng học nhất — Task 1 của A2

2 dbt test fail trên dữ liệu thật. Cách xử lý **không phải** nới ngưỡng cho test
xanh, mà điều tra ra DKC/VLP/VNX là **vỏ công ty thật** giá 30-900 VNĐ suốt 828
phiên — rồi nhận ra **test đang đo sai thứ**: tên là "kiểm dải giá VNĐ" nhưng
mục đích thật là bắt lệch đơn vị ×1000. Sàn tuyệt đối không phân biệt được
"penny thật" với "quên nhân 1000".

Test được viết lại để bắt **đứt gãy trong cùng một mã** (mã nào vừa có dòng
< 100 vừa có dòng > 1000) thay vì ngưỡng tuyệt đối.

> Tư duy DE trưởng thành: khi test fail, hỏi **"test này có đo đúng thứ nó sinh
> ra để đo không"** *trước khi* hỏi "làm sao cho nó xanh".

---

## 7 bài học DE rút ra từ chính repo này

1. **Giả định về dữ liệu nguồn phải kiểm bằng lời gọi API thật, không suy từ tài
   liệu.** 5/5 giả định ban đầu của A1 đều sai (doc A1 §2).
2. **Dữ liệu quá khứ KHÔNG bất biến.** VCI rút lại kỳ 2026 Q1 của 351 mã → đó là
   lý do `raw_financial_ratio_v1_backup` được giữ vĩnh viễn, không xoá.
3. **Với mỗi hàm ghi DB, hỏi thêm: "job nào khác ghi vào cùng cột này, ở cadence
   nào?"** Job `daily` từng xoá trắng cột mà job `monthly` vừa điền.
4. **Review từng task không thấy được lỗi tương tác.** 8/8 task A1 sạch khi xét
   riêng, nhưng final review toàn nhánh tìm ra 2 lỗi Critical *sinh ra từ tương
   tác giữa các task* — không nằm trong diff của bất kỳ task nào.
5. **Cổng kiểm chứng đặt sai chỗ thì vô dụng.** `reconcile_warehouse` chạy ngay
   sau job monthly trong cùng workflow → về mặt cấu trúc không bao giờ bắt được
   lỗi phát sinh hôm sau.
6. **Cổng báo động sai liên tục tệ hơn không có cổng**, vì người ta học cách bỏ
   qua nó. (`check_against_source` so `pe` — mà `pe` phụ thuộc giá thị trường
   hiện tại nên luôn lệch 1-7%. Đã sửa: chỉ so `roe`/`roa`.)
7. **NULL ≠ 0.** Sentinel `0.0` giả cho ngân hàng từng khiến 187 dòng bị chấm
   điểm chất lượng bét bảng. Cả hệ thống scoring hiện tại được thiết kế quanh
   việc phân biệt "không đo được" với "kém nhất nhóm".

---

## Lịch gợi ý (14 ngày × 1-2 giờ)

| Ngày | Nội dung |
|---|---|
| 1-2 | Chặng 0 + doc retro A1 (chỉ đọc, chưa chạy code) |
| 3-5 | Chặng 1, vừa đọc vừa chạy `build_warehouse.py` xem log |
| 6-10 | Chặng 2 — chạy `dbt build`, `dbt docs serve` xem DAG trực quan |
| 11-12 | Chặng 3 — gọi từng tool trong Claude Code, đối chiếu code |
| 13-14 | Chặng 4 + tự viết bổ sung vào doc retro theo hiểu biết của mình |

---

## Việc còn treo (nếu muốn thực hành trên việc thật)

- Tiêu chí #7 của plan A3: chạy thử 3 câu hỏi mẫu trong Claude Code thật để xác
  nhận agent nêu đúng `as_of` / `peer_basis`, không đưa khuyến nghị mua/bán
- Tạo token MotherDuck **read-only/scoped** riêng cho MCP server thay vì dùng
  token cá nhân đầy quyền (xem `mcp_server/instructions.md` phần giới hạn đã biết)
- Trả các nợ N1, N3, N5, N6, N7, N9, N10, N11, N12 trong doc A1
- Cập nhật `docs/learning/01-08` cho khớp hệ thống sau pivot (hoặc đánh dấu rõ
  là tài liệu lịch sử)
