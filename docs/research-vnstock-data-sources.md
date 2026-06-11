# Research — Dữ liệu vnstock có thể thêm vào warehouse (free tier)

> Khảo sát thực tế bằng cách gọi trực tiếp các API trong `vnstock/explorer/vci/*`
> (đã cài ở `.venv`, nguồn VCI = miễn phí, không cần API key trả phí).
> Mục tiêu: liệt kê API nào "deep insight"/fundamental/valuation có thể lưu vào
> warehouse, đánh giá chất lượng dữ liệu thực tế, và đề xuất ưu tiên.

---

## 1. Đã tích hợp (warehouse hoặc news pipeline)

| API | Dùng ở đâu | Trạng thái |
|---|---|---|
| `Quote.history` | `ingest_market.fetch_history_one` → `raw_price_daily` | ✅ hoạt động (đã fix đơn vị) |
| `Trading.price_board` | `ingest_market.fetch_eod_prices` → `raw_price_daily` | ✅ hoạt động |
| `Listing.all_symbols` / `symbols_by_group` | `refresh_universe`, news pipeline | ✅ hoạt động |
| `Company.overview` | `ingest_market.fetch_company_info` → `raw_company_info` | ⚠️ code có, bảng **0 dòng** (chưa chạy `--mode monthly` thật) |
| `Company.news` | news pipeline (`ingest.fetch_news`) | ✅ hoạt động (không lưu warehouse) |

---

## 2. Đang BỊ LỖI / không dùng được — `Finance.ratio()`

`ingest_market.fetch_financials()` (Phase 2A, dùng cho `raw_financial_ratio`) gọi
`Finance(symbol, source="VCI", period="year").ratio()`. Test thực tế với HPG:

- Trả về **wide-pivot table** rất khó dùng: `df.columns` = `['item','item_en','item_id', '2018','2018','2018', ... x16 lần '2018']`
  (mỗi năm lặp lại cho 4 quý × nhiều mã chỉ số TTM, các cột trùng tên hoàn toàn).
- `_normalize_financials()` tìm cột tên `pe`/`pb`/`roe`... bằng `_find()` nhưng
  cấu trúc thật có các **chỉ số nằm ở hàng** (`item` = "P/E", "ROE"...), không
  phải ở tên cột → không khớp được gì có ý nghĩa.
- **Đây là lý do `raw_financial_ratio` có 0 dòng** dù code "đã có" theo Phase 2A.

→ **Khuyến nghị: thay bằng `Company.ratio_summary()`** (mục 3.1) — dữ liệu tương đương nhưng sạch hơn nhiều.

---

## 3. API mới đáng cân nhắc (đã test thực tế, free/VCI)

### 3.1 `Company.ratio_summary()` — ⭐ ưu tiên cao nhất

Test HPG: trả **40 dòng × 61 cột**, mỗi dòng = 1 quý (2018 Q1 → hiện tại), dạng
long/tidy sẵn:

```
symbol, year, quarter, organ_code, year_report,
market_cap, pe, pb, ps, dividend_yield, ev_to_ebitda,
roe, roa, roic, gross_margin, ebit_margin, after_tax_profit_margin,
debt_to_equity, current_ratio, quick_ratio, cash_ratio,
asset_turnover, fixed_asset_turnover, ... (+ chỉ tiêu ngân hàng: car, npl, ldr...)
```

- **Sạch, đúng kiểu số, theo quý từ 2018** — phù hợp trực tiếp làm
  `raw_financial_ratio (symbol, period, period_type, pe, pb, roe, roa, eps?, ...)`.
  Có thể mở rộng schema để giữ thêm `market_cap`, `roic`, `debt_to_equity`,
  `dividend_yield`, các margin — rất hữu ích cho mart `fct_financials` (Phase 3).
- **Hành động:** sửa `ingest_market.fetch_financials()` để gọi
  `Company(symbol, source).ratio_summary()` thay vì `Finance.ratio()`, viết lại
  `_normalize_financials()` cho schema mới. Xoá/migrate `raw_financial_ratio` cũ
  (đang rỗng nên không cần migration data).

### 3.2 `Company.events()` — sự kiện doanh nghiệp (cổ tức, phát hành, GD nội bộ)

Test HPG: 50 dòng, cột sạch:
`event_title_vi, category (DIVIDEND / SHARE_ISSUE / MAJOR_SHAREHOLDER_TRADING...),
record_date, exright_date, exercise_ratio, payout_date, value_per_share, ...`

- Khớp gần như chính xác với bảng `raw_corporate_event` đã **thiết kế sẵn trong
  DESIGN.md §5.1 nhưng chưa tạo**: `symbol, event_type, ex_date, record_date,
  ratio, description`.
- **Giá trị cao cho watchlist hiện tại**: VNR/HPG đều có lịch sử trả cổ tức đều —
  bản tin có thể cảnh báo "sắp đến ngày GDKHQ nhận cổ tức" — đúng tinh thần
  "liên quan và giá trị hơn" mà bạn vừa yêu cầu cho watchlist.
- **Hành động:** thêm bảng `raw_corporate_event`, hàm `fetch_corporate_events()`
  trong `ingest_market.py`, nạp ở `--mode monthly` (sự kiện không đổi nhanh).

### 3.3 `Finance.balance_sheet()` / `income_statement()` / `cash_flow()`

Test HPG `income_statement(period="year")`: 25 dòng × 11 cột, dạng
`item, item_en, item_id, <year>, <year>, ...` (long-by-item, wide-by-year) — sạch,
dùng được. **Lưu ý: bản free/community giới hạn tối đa 8 kỳ** (in cảnh báo khi gọi).

- Khớp với bảng `raw_financial_stmt` đã thiết kế trong DESIGN.md:
  `symbol, period, period_type, stmt_type, line_item, value`. Cần
  `melt()` từ wide (theo năm) sang long.
- Giá trị: nền tảng cho phân tích cơ bản sâu (biên lợi nhuận, dòng tiền, nợ vay)
  — phù hợp Phase 3 (`fct_financials`), không cấp thiết cho bản tin hằng ngày.
- **Effort trung bình-cao** (3 statement × melt + mapping item_id). Đề xuất làm
  sau 3.1/3.2.

### 3.4 `Listing.industries_icb()` — bảng phân ngành ICB chuẩn

Test: 177 dòng, `icb_code, icb_name, en_icb_name, level (1-4)` — bảng tĩnh, ít đổi.

- Hiện `raw_company_info.industry_icb` (nếu có dữ liệu) chỉ là tên ngành phẳng.
  Bảng này cho phép build `dim_industry` (mã ICB → tên ngành theo cấp 1-4) →
  group theo "Basic Resources", "Insurance", "Real Estate"... cho
  `mart_sector_daily` (Phase 3) — vd so sánh HPG (Thép) với toàn ngành Basic Resources.
- **Effort thấp** (1 bảng tĩnh, refresh `--mode monthly` là đủ).

### 3.5 `vcb_exchange_rate()` (`vnstock.explorer.misc.exchange_rate`)

Test: gọi trực tiếp Vietcombank (không qua vnstock API key, không rate-limit
chung với `_throttle()`), trả tỷ giá mua/bán USD/EUR/JPY/CNY... theo ngày.

- **Yếu tố vĩ mô đơn giản nhất, miễn phí, ổn định** — liên quan trực tiếp đến
  PHP (cảng — XNK), HPG (NK quặng/than, XK thép). Lưu `raw_exchange_rate (date,
  currency_code, buy_cash, buy_transfer, sell)`, nạp `--mode daily`.
- **Effort rất thấp.**

### 3.6 `Company.shareholders()` — cơ cấu cổ đông lớn

Test HPG: 68 dòng, `share_holder, quantity, share_own_percent, update_date` — sạch.

- Hữu ích để theo dõi cô đặc sở hữu / giao dịch cổ đông lớn, nhưng **đổi chậm**,
  ưu tiên thấp hơn 3.1-3.5. Có thể gộp chung đợt với `--mode monthly`.

### 3.7 Cân nhắc nhưng KHÔNG khuyến nghị ngay: `vnstock.explorer.msn.*`

Cung cấp chỉ số toàn cầu (S&P500, DJI...), giá vàng/bạc (XAUUSD/XAGUSD), USDVND
qua Bing/MSN — nhưng là API bên thứ 3 (không phải vnstock gốc), độ ổn định/ToS
chưa rõ, và đã có `vcb_exchange_rate` cho tỷ giá. **Để dành, không làm trước.**

---

## 4. Đề xuất thứ tự triển khai

| Ưu tiên | Việc | Bảng mới/sửa | Effort | Lợi ích |
|---|---|---|---|---|
| **1** | Thay `Finance.ratio()` → `Company.ratio_summary()` | sửa `raw_financial_ratio` (đang rỗng) | Thấp-vừa | Sửa tính năng đang **hỏng**, dữ liệu PE/PB/ROE/ROA theo quý từ 2018 |
| **2** | `Company.events()` → bảng cổ tức/sự kiện | tạo `raw_corporate_event` (đã thiết kế, chưa tạo) | Thấp-vừa | Bản tin báo lịch cổ tức cho watchlist — giá trị trực tiếp |
| **3** | `Listing.industries_icb()` → bảng ngành ICB | tạo `dim_industry` | Thấp | Nền cho `mart_sector_daily` (Phase 3), enrich nhãn ngành |
| **4** | `vcb_exchange_rate()` → tỷ giá hằng ngày | tạo `raw_exchange_rate` | Rất thấp | Yếu tố vĩ mô đơn giản, liên quan HPG/PHP |
| **5** | `Finance.balance_sheet/income_statement/cash_flow` | tạo `raw_financial_stmt` (đã thiết kế) | Vừa-cao | Phân tích cơ bản sâu, nền Phase 3 `fct_financials` |
| 6 (optional) | `Company.shareholders()` | bảng `raw_shareholders` | Thấp | Theo dõi cổ đông lớn, ưu tiên thấp |

Tất cả đều dùng nguồn **VCI miễn phí**, qua `_throttle()` sẵn có, theo đúng pattern
hiện tại (`--mode weekly/monthly`, upsert + `etl_load_log`).

**Đề xuất bắt đầu với #1 và #2** — effort thấp, sửa lỗi hiện có (#1) và mang lại
giá trị trực tiếp cho watchlist mới (#2: lịch cổ tức cho HPG/IDV/MLS/PHP/VNR).
