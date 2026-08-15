# Thiết kế — Nền tảng phân tích cơ bản & Agent đầu tư (Mảng A + MCP)

> **Trạng thái:** thiết kế đã được chấp thuận, chờ lập kế hoạch triển khai.
> **Ngày:** 2026-08-09
> **Phạm vi:** Mảng A (tầng phân tích trên dữ liệu đã có) + luồng hội thoại MCP.

---

## 1. Bối cảnh & mục tiêu

### 1.1 Vì sao đổi hướng

Hệ thống hiện tại (`main.py` → bản tin Telegram hằng ngày) dừng ở **tầng mô tả**: giá hôm nay ±%, RSI, khối lượng đột biến. Đây là thông tin mở ứng dụng chứng khoán nào cũng thấy, nên không tạo ra giá trị quyết định.

Nhu cầu thật là **tầng định giá và so sánh**: mã này đang rẻ hay đắt so với chính nó trong quá khứ và so với các doanh nghiệp cùng ngành; chất lượng lợi nhuận có bền không; cổ tức có đều không.

### 1.2 Mục tiêu

Xây một nền tảng cho phép trả lời — có căn cứ số liệu, truy vết được — các câu hỏi:

- Trong 1.577 mã, mã nào đang có định giá thấp so với lịch sử của chính nó và so với ngành?
- Doanh nghiệp nào có ROE cao *và bền* qua nhiều quý, nợ vay trong tầm kiểm soát?
- Mã nào trả cổ tức tiền mặt đều đặn nhiều năm, phù hợp tích sản dài hạn?
- Ngành nào đang được định giá thấp so với chính ngành đó trong quá khứ?

### 1.3 Hồ sơ người dùng & khẩu vị

- Nhà đầu tư cá nhân tự quản lý danh mục, chưa có phương pháp phân tích hệ thống.
- Khẩu vị hiện tại: **bluechip/large-cap + tích sản dài hạn + cổ tức**, nắm 1–3 năm.
- **Chưa xác định được "gu" đầu tư của mình** → hệ thống phải cho phép *thử nghiệm* nhiều bộ tiêu chí và so sánh kết quả, thay vì áp một công thức cố định.
- Đồng thời đây là dự án học **Data Engineering** (chuyển hướng từ Data Analyst) → chọn công cụ chuẩn công nghiệp (dbt) thay vì giải pháp nhanh-gọn.

---

## 2. Phạm vi

### 2.1 Trong phạm vi

| # | Hạng mục |
|---|---|
| 1 | Vá 4 lỗ hổng dữ liệu nền: mở rộng `raw_financial_ratio`, sửa bug ánh xạ cột hồ sơ DN, thêm `dim_industry` (ICB), thêm `raw_index_daily` |
| 2 | dbt-duckdb project: `staging` → `intermediate` → `marts` |
| 3 | Bộ chấm điểm 5 thành phần, tách công thức theo loại hình doanh nghiệp, trọng số cấu hình được theo profile |
| 4 | MCP server — luồng hội thoại, bật/tắt độc lập |
| 5 | Bốn tầng kiểm chứng dữ liệu |

### 2.2 Ngoài phạm vi (các spec sau)

- **Mảng B** — Báo cáo tài chính chi tiết (`income_statement` / `balance_sheet` / `cash_flow`), sự kiện doanh nghiệp & cổ tức (`Company.events`), khối ngoại (`Trading.foreign_trade`), cơ cấu cổ đông.
- **Mảng C** — Job báo cáo luận điểm đầu tư định kỳ (tháng/quý); thay bản tin hằng ngày bằng **cảnh báo theo sự kiện**.
- **Mảng D** — Dữ liệu vĩ mô (CPI, lãi suất, tỷ giá, tăng trưởng tín dụng); kho tin tức & cơ chế scan thị trường.
- Streamlit dashboard; chuyển orchestration sang Prefect.

### 2.3 Không đụng tới trong spec này

`main.py`, `digest.py`, `signals.py`, `screener.py`, `storage.py`, `notify.py` và workflow `daily.yml` **giữ nguyên và tiếp tục chạy**. Việc thay thế bằng cảnh báo sự kiện thuộc mảng C, để không phá thứ đang hoạt động.

---

## 3. Hiện trạng đã kiểm chứng

### 3.1 Tài sản dữ liệu hiện có (MotherDuck `md:vn_market`, đo ngày 2026-08-09)

| Bảng | Quy mô | Khoảng thời gian |
|---|---|---|
| `raw_price_daily` | 1.246.543 dòng · 1.577 mã | 2016-07-20 → 2026-08-07 |
| `raw_financial_ratio` | 48.103 dòng · 1.585 mã | theo quý, 2018 → 2026 |
| `raw_company_info` | 1.587 mã | snapshot |
| `dim_symbols` | 1.598 mã | — |
| `backfill_status` | 1.594 mã `done` | — |
| `etl_load_log` | 135 dòng | — |

Ba workflow GitHub Actions (daily/weekly/monthly) đang chạy ổn định, ghi thẳng lên MotherDuck, upsert idempotent.

> **Lưu ý:** file `data/warehouse.duckdb` trong repo chỉ còn 2.359 dòng — là bản test cũ đã lạc hậu, **không phải** nguồn dữ liệu thật.

### 3.2 Sáu vấn đề đã xác minh bằng truy vấn/gọi API thật

#### V1 — Sentinel `0.0` giả làm hỏng dữ liệu ngân hàng (nghiêm trọng nhất)

VCI dùng `0.0` để biểu thị "chỉ tiêu không áp dụng", không phải giá trị 0 thật.

Bằng chứng: **187/187 dòng** của 27 mã ngân hàng từ 2025 tới nay có `current_ratio = 0` **và** `roic = 0`. Ngược lại, HPG (phi tài chính) có `net_interest_margin = 0`, `npl = 0`.

Hậu quả nếu không xử lý: mọi ngân hàng bị chấm 0 điểm ROIC → **bị loại khỏi mọi bộ lọc chất lượng**, và bị đọc là mất khả năng thanh toán (`current_ratio = 0`). Đây đúng là nhóm cổ phiếu cổ tức dài hạn mà người dùng quan tâm.

#### V2 — Warehouse đang bỏ 27 trong 61 cột của nguồn

`Company.ratio_summary()` trả **61 cột**, bảng `raw_financial_ratio` hiện chỉ giữ 13. Toàn bộ khối chỉ tiêu ngân hàng (`net_interest_margin`, `npl`, `cir`, `car`, `casa_ratio`, `ldr_loan_deposit_ratio`, `loans_growth`, `deposit_growth`…) và nhiều chỉ tiêu hữu ích (`ev_to_ebitda`, `quick_ratio`, `cash_ratio`, `asset_turnover`, `cash_cycle`, `number_of_shares_mkt_cap`…) bị vứt bỏ.

#### V3 — Bug ánh xạ cột trong `_normalize_company()`

`raw_company_info.industry_icb` và `.exchange` **NULL 100%** (1.587/1.587), `dim_symbols.exchange` **NULL 100%** (1.598/1.598).

Nguyên nhân: `_normalize_company()` tại [`src/ingest_market.py:258-284`](../../../src/ingest_market.py) dò tên cột `"industry_icb"` / `"exchange"`, nhưng cột thật của `Company.overview()` là `icb_code_lv2`, `icb_code_lv4`, `com_group_code`.

Cột thật đầy đủ (đã gọi API xác minh với HPG):

```
symbol, organ_code, current_price, market_cap, issue_share, tag, rating, rating_as_of,
organ_name, organ_short_name, com_type_code, com_group_code, sector,
average_match_value1_month, average_match_volume1_month,
highest_price1_year, lowest_price1_year,
foreigner_percentage, maximum_foreign_percentage, state_percentage,
analyst, upside_to_target_percent, dividend_per_share_tsr, projected_tsr_percentage,
target_price, company_profile, in_cu, icb_code_lv2, icb_code_lv4,
free_float, free_float_percentage, listing_date, prev_insight, fund_info,
is_bank, listing, bank
```

Hệ quả: hiện **không lọc được HOSE/HNX/UPCOM**, dù `config/warehouse.yml` khai báo chỉ lấy HOSE+HNX.

#### V4 — Lệch đơn vị `value` 10⁶ lần

Đối chiếu HPG phiên 2026-08-07: `volume 13.018.100 × close 21.850 ≈ 284 tỷ VNĐ`, trong khi `value = 287.111,73`.

Kết luận: **`close` tính bằng VNĐ, `value` tính bằng triệu VNĐ.** Chưa được ghi ở tài liệu nào. Bất kỳ bộ lọc thanh khoản nào dùng thẳng `value` sẽ sai 1 triệu lần.

Thêm nữa: `value` chỉ có dữ liệu từ 2026-06-07 trở đi (mọi dòng backfill qua `Quote.history` đều NULL). Bộ lọc thanh khoản dài hạn phải dùng `close × volume` làm proxy.

#### V5 — Chỉ số không nhân ×1000

`Quote(symbol='VNINDEX').history()` trả `close = 1768.06` cho phiên 2026-08-07 — **đã đúng đơn vị**. Hàm `fetch_history_one()` hiện nhân ×1000 cho cổ phiếu, **không được dùng lại cho chỉ số**. Cần hàm riêng.

#### V6 — Suy ra được doanh thu & lợi nhuận mà không cần BCTC (phát hiện tích cực)

Vì `pe`, `ps`, `pb` và `market_cap` cùng thuộc một dòng (cùng thời điểm giá), phép chia triệt tiêu giá:

```
doanh_thu_ttm = market_cap / ps
lnst_ttm      = market_cap / pe
von_chu_so_huu = market_cap / pb
so_co_phieu   = number_of_shares_mkt_cap
eps = lnst_ttm / so_co_phieu      bvps = von_chu_so_huu / so_co_phieu
```

Đối chiếu HPG:

| Kỳ | Doanh thu TTM suy ra | LNST TTM suy ra | Thực tế |
|---|---|---|---|
| 2024 Q4 | 138.855 tỷ | 12.021 tỷ | Khớp BCTC 2024 |
| 2023 Q2 | 116.014 tỷ | **−1.908 tỷ** | Đúng giai đoạn HPG lỗ |

→ **Tầng tăng trưởng làm được ngay trong spec này**, không phải chờ mảng B.

#### Ghi chú chất lượng bổ sung

- `cir` và `average_cost_of_financing` trả **giá trị âm** (VCB: `cir = -0,4098`) — quy ước dấu ngược. Phải `abs()` và kiểm tra thuộc `[0, 1]`.
- **Hai cặp cột trùng nhau hoàn toàn**, đã xác minh: `cost_to_income` ≡ `cir` (VCB: cả hai `-0,409843`); `financial_leverage` ≡ `debt_to_equity` (HPG: cả hai `0,581189` rồi `0,694886`). Chỉ giữ một cột mỗi cặp.
- `debt_per_equity` **không** trùng `debt_to_equity` (HPG: `0,359252` vs `0,581189`) — là hai chỉ tiêu đòn bẩy khác nhau (nợ vay/vốn chủ vs tổng nợ/vốn chủ). Giữ cả hai.
- `owners_equity` có ngữ nghĩa không rõ (HPG: 0,0603 / 0,1359 — không phải giá trị vốn chủ) → **không đưa vào warehouse** cho tới khi xác minh được.
- `car`, `casa_ratio`, `equity` trả `None` với HPG. Cần đo tỉ lệ NULL trên nhóm ngân hàng trước khi đưa vào công thức chấm điểm (xem §7.4).
- `pe` âm khi doanh nghiệp lỗ (HPG Q2/2023: `pe = −78,62`); `pe` rất lớn khi lợi nhuận sát 0 (HPG Q1/2023: `pe = 236,43`).
- Môi trường đang chạy `vnstock 4.0.4`, có bản 4.0.5. Không nâng cấp trong spec này để tránh thay đổi hành vi API giữa chừng.

---

## 4. Kiến trúc

### 4.1 Sơ đồ

```
INGESTION (Python, giữ pattern hiện tại)
  job_daily    → giá EOD + chỉ số
  job_weekly   → tỷ số tài chính (50 cột)
  job_monthly  → hồ sơ DN + ICB + refresh universe
        │
        ▼
  RAW layer (immutable)         dim_symbols · etl_load_log · backfill_status
  raw_price_daily · raw_index_daily · raw_financial_ratio · raw_company_info · dim_industry
        │
        ▼  dbt-duckdb
  STAGING   chuẩn hoá đơn vị · khử sentinel · gắn cờ chất lượng
        ▼
  INTERMEDIATE   percentile định giá · chỉ tiêu suy ra · độ bền · tăng trưởng
        ▼
  MARTS     dim_stock · dim_industry_hierarchy · fct_price_daily · fct_financial_quarterly
            mart_valuation_band · mart_sector_snapshot
            mart_stock_scorecard · mart_data_quality
        │
        ├──────────────────────────────┬───────────────────────────┐
        ▼                              ▼                           ▼
  src/scoring.py                 MCP server                  (mảng C)
  + scoring_profiles.yml       (luồng hội thoại)          job báo cáo định kỳ
                                                          cảnh báo sự kiện
```

### 4.2 Cấu trúc repo sau spec này

```
vn-stock-daily/
├─ src/
│   ├─ ingest_market.py        # SỬA _normalize_company; THÊM fetch_industries_icb,
│   │                          # fetch_index_history, mở rộng fetch_financials
│   ├─ warehouse.py            # THÊM dim_industry, raw_index_daily;
│   │                          # mở rộng raw_financial_ratio, raw_company_info
│   ├─ scoring.py              # ✨ MỚI — áp profile lên mart_stock_scorecard
│   └─ (các file news pipeline giữ nguyên)
├─ transforms/                 # ✨ MỚI — dbt project
│   ├─ dbt_project.yml
│   ├─ profiles.yml
│   ├─ seeds/
│   │   └─ metric_applicability.csv    # ma trận khả dụng chỉ tiêu
│   ├─ models/{staging,intermediate,marts}/
│   └─ tests/                  # singular tests
├─ mcp_server/                 # ✨ MỚI
│   ├─ server.py
│   └─ instructions.md         # luật cho agent
├─ config/
│   ├─ warehouse.yml
│   └─ scoring_profiles.yml    # ✨ MỚI
├─ scripts/
│   ├─ migrate_financial_ratio_v2.py   # ✨ MỚI
│   └─ reconcile_warehouse.py          # ✨ MỚI — đối chiếu chéo với API gốc
└─ .github/workflows/          # thêm bước dbt build + dbt test
```

### 4.3 Ranh giới bật/tắt

| Luồng | Cách bật | Cách tắt | Ảnh hưởng khi tắt |
|---|---|---|---|
| Hội thoại (MCP) | Khai báo trong `.mcp.json` | Xoá khai báo | Không ảnh hưởng warehouse hay luồng báo cáo |
| Báo cáo định kỳ (mảng C) | Workflow GHA riêng | Disable workflow | Không ảnh hưởng warehouse hay MCP |

Cả hai đọc **cùng một mart** và dùng **cùng một `src/scoring.py`** → kết quả luôn nhất quán giữa hai luồng.

---

## 5. Thay đổi tầng ingestion

### 5.1 `raw_financial_ratio` — mở rộng 13 → 50 cột

**Khoá chính:** `(symbol, year, quarter)` — giữ nguyên.
`quarter` 1–4 = TTM kết thúc tại quý đó (`ratio_type = RATIO_TTM`); `quarter = 5` = cả năm (`RATIO_YEAR`).

| Nhóm | Cột |
|---|---|
| **Khoá & meta** (6) | `symbol`, `year`, `quarter`, `period_type`, `ratio_type`, `loaded_at` |
| **Chung** (12) | `market_cap`, `number_of_shares_mkt_cap`, `dividend_yield`, `pe`, `pb`, `ps`, `roe`, `roa`, `debt_to_equity`, `gross_margin`, `pre_tax_profit_margin`, `after_tax_profit_margin` |
| **Phi tài chính** (16) | `roic`, `ev_to_ebitda`, `price_to_cash_flow`, `current_ratio`, `quick_ratio`, `cash_ratio`, `ebit_margin`, `asset_turnover`, `fixed_asset_turnover`, `cash_cycle`, `day_sale_outstanding`, `days_inventory_outstanding`, `days_payable_outstanding`, `ebit`, `ebitda`, `debt_per_equity` |
| **Ngân hàng** (16) | `net_interest_margin`, `average_yield_on_earning_assets`, `average_cost_of_financing`, `non_and_interest_income`, `cir`, `loans_growth`, `deposit_growth`, `equity_to_liabilities`, `equity_to_loans`, `total_equity_total_asset`, `ldr_loan_deposit_ratio`, `npl`, `loans_loss_reserve_to_loans`, `provision_to_outstanding_loans`, `car`, `casa_ratio` |

**Không đưa vào:** `ratio_ttm_id`, `ratio_year_id`, `organ_code`, `year_report`, `owners_equity` (ngữ nghĩa không rõ), `loans_loss_reserves_to_np_ls`, `equity`, `nob66`, `nob69`, `nob70`, `bsb113`, và hai cột trùng lặp đã xác minh: `financial_leverage` (≡ `debt_to_equity`), `cost_to_income` (≡ `cir`).

**Migration:** raw layer tái tạo được từ API nên không cần chuyển dữ liệu.

1. `ALTER TABLE raw_financial_ratio RENAME TO raw_financial_ratio_v1_backup`
2. Tạo bảng mới theo schema trên
3. Nạp lại toàn bộ 1.585 mã
4. Đối chiếu: số mã mới ≥ 95% số mã cũ **và** số dòng mới ≥ số dòng cũ
5. Chỉ khi đối chiếu đạt mới xoá bảng backup

**Thời gian chạy lại:** ~82 phút ở throttle 3,1 s/call. Đưa `_MIN_CALL_INTERVAL` ra biến môi trường `VNSTOCK_MIN_INTERVAL` (mặc định giữ 3,1) để có thể hạ xuống ~1,05 s khi dùng key Community 60 req/phút (~28 phút).

### 5.2 `raw_company_info` — sửa bug ánh xạ + mở rộng

Viết lại `_normalize_company()` dùng **tên cột chính xác** (không dò mềm nữa, vì đã biết cột thật):

| Cột warehouse | Nguồn |
|---|---|
| `symbol` | `symbol` |
| `company_name` | `organ_name` |
| `short_name` | `organ_short_name` |
| `exchange` | `com_group_code` |
| `com_type_code` | `com_type_code` |
| `is_bank` | `is_bank` |
| `icb_code_lv2`, `icb_code_lv4` | như tên |
| `sector` | `sector` (giữ, tên ngành cấp cao tiếng Anh) |
| `market_cap`, `issue_share` | như tên |
| `free_float_percentage` | `free_float_percentage` |
| `foreigner_percentage`, `maximum_foreign_percentage`, `state_percentage` | như tên |
| `avg_match_value_1m`, `avg_match_volume_1m` | `average_match_value1_month`, `average_match_volume1_month` |
| `highest_price_1y`, `lowest_price_1y` | như tên |
| `listed_date` | `listing_date` |
| `loaded_at` | `now()` |

**Không đưa vào:** `analyst`, `target_price`, `upside_to_target_percent`, `projected_tsr_percentage`, `rating` — là khuyến nghị của bên thứ ba, không phải dữ kiện; đưa vào sẽ khiến agent trích dẫn nhầm thành phân tích của mình.

Job monthly cập nhật `dim_symbols.exchange` từ `raw_company_info.exchange`.

### 5.3 `dim_industry` — mới

Nguồn `Listing(source='VCI').industries_icb()` — đã xác minh: 177 dòng, cột `icb_name` (**tiếng Việt**), `en_icb_name`, `icb_code`, `level` (1–4).

```
dim_industry(icb_code VARCHAR PK, icb_name VARCHAR, en_icb_name VARCHAR,
             level INTEGER, loaded_at TIMESTAMP)
```

Refresh ở `--mode monthly`. Bảng tĩnh.

### 5.4 `raw_index_daily` — mới

```
raw_index_daily(index_code VARCHAR, trade_date DATE,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                volume BIGINT, loaded_at TIMESTAMP,
                PRIMARY KEY (index_code, trade_date))
```

Chỉ số: `VNINDEX`, `VN30`, `HNXINDEX` — cả ba đã xác minh gọi được.

Hàm mới `fetch_index_history(index_code, start, end)` — **tách riêng khỏi `fetch_history_one()`** vì chỉ số không nhân ×1000 (V5). Backfill 10 năm một lần (3 call), sau đó append ở `--mode daily`.

---

## 6. Mô hình dbt

### 6.1 Ma trận khả dụng chỉ tiêu (dbt seed)

`transforms/seeds/metric_applicability.csv` — **nền tảng của việc chống lỗi V1**.

```csv
metric,com_class,is_applicable,use_in_scoring
roic,NONFIN,true,true
roic,BANK,false,false
roic,OTHERFIN,false,false
current_ratio,NONFIN,true,true
current_ratio,BANK,false,false
gross_margin,NONFIN,true,true
gross_margin,BANK,true,false          # BANK có giá trị thật nhưng ngữ nghĩa khác
npl,BANK,true,true
npl,NONFIN,false,false
net_interest_margin,BANK,true,true
...
```

**Hai cờ tách biệt, có chủ đích:**

- `is_applicable = false` → staging đổi `0.0 → NULL` (khử sentinel giả).
- `use_in_scoring = false` → giữ nguyên giá trị, nhưng không đưa vào công thức chấm điểm.

Phân biệt này cần thiết vì `gross_margin` của ngân hàng **có giá trị thật** (ACB: 0,68) nhưng mang ngữ nghĩa khác doanh nghiệp sản xuất — NULL hoá sẽ mất dữ liệu, còn chấm điểm chung sẽ so sai.

`com_class` suy ra từ `raw_company_info`:

| `com_class` | Điều kiện |
|---|---|
| `BANK` | `is_bank = true` hoặc `sector = 'Banks'` |
| `OTHERFIN` | `sector` ∈ {`Insurance`, `Financial Services`} |
| `NONFIN` | còn lại |

### 6.2 Staging

| Model | Nội dung |
|---|---|
| `stg_price_daily` | Cast, khử trùng theo `(symbol, trade_date)`. `value_vnd = value × 1e6`. `turnover_proxy_vnd = close × volume`. Cờ: `has_ohlc`, `has_value`, `is_suspect_price` (close ngoài `[100, 5.000.000]`) |
| `stg_index_daily` | Cast, khử trùng. **Không** đổi đơn vị |
| `stg_financial_ratio` | Join `metric_applicability` → NULL hoá sentinel. `period_end_date` từ `(year, quarter)`. `abs()` cho `cir`, `average_cost_of_financing`. Cờ: `is_loss_making` (`pe < 0`), `pe_meaningful` (`pe > 0 AND pe < 200`), `pb_meaningful` (`pb > 0 AND pb < 30`) |
| `stg_company_info` | Thêm `com_class`. Join `dim_industry` lấy tên ngành lv2/lv4 tiếng Việt |
| `stg_industry` | Phân cấp ICB 1→4 dạng phẳng: `icb_code_lv4 → lv3 → lv2 → lv1` kèm tên |

### 6.3 Intermediate

| Model | Nội dung |
|---|---|
| `int_price_features` | Theo `(symbol, trade_date)`: MA20/50/200; return 1T/3T/6T/12T/YTD; `avg_turnover_20d`, `avg_turnover_60d` (dùng `value_vnd` khi có, ngược lại `turnover_proxy_vnd`); biến động 60 phiên; vị trí giá trong biên 52 tuần; beta 250 phiên so VNINDEX |
| `int_fundamentals_ttm` | Chỉ tiêu suy ra theo §3.2-V6: `revenue_ttm`, `earnings_ttm`, `book_value`, `eps`, `bvps`. Tăng trưởng: YoY quý gần nhất, CAGR 3 năm, `growth_consistency` = số quý YoY dương / 12 |
| `int_valuation_percentile` | **(a)** Percentile P/E, P/B, P/S của kỳ hiện tại trong **20 quý gần nhất của chính mã** (chỉ tính trên các quý `pe_meaningful`, yêu cầu ≥12 quý hợp lệ). **(b)** Percentile so với peer group cùng kỳ. Kèm `peer_basis`, `peer_count` |
| `int_quality_metrics` | ROE trung bình 8 quý; `roe_stability = 1 − CV(roe, 8q)` với `CV = độ_lệch_chuẩn / |trung_bình|`, chặn về `[0, 1]` — **nếu ROE trung bình ≤ 0 thì `roe_stability = 0`** (doanh nghiệp lỗ không có "độ bền"); số quý ROE > 15%; hệ số góc xu hướng biên 8 quý; đòn bẩy. **Công thức tách theo `com_class`** |
| `int_dividend_history` | `dividend_yield` kỳ mới nhất; trung bình 5 năm; `dividend_years_consecutive` — đếm trên **các dòng năm (`quarter = 5`)**, số năm liên tiếp `dividend_yield > 0` tính lùi từ năm gần nhất có dữ liệu; độ ổn định |

### 6.4 Marts

| Model | Hạt | Nội dung |
|---|---|---|
| `dim_stock` | 1 dòng/mã | Hồ sơ, ngành ICB lv2/lv4 (tiếng Việt), `com_class`, sàn, vốn hoá, free float, sở hữu nước ngoài/nhà nước, thanh khoản 20 phiên, ngày niêm yết, `is_active` |
| `dim_industry` | 1 dòng/mã ngành | Phân cấp ICB 1–4 |
| `fct_price_daily` | mã × phiên | Giá sạch + chỉ báo từ `int_price_features` |
| `fct_financial_quarterly` | mã × quý | Tỷ số (đã khử sentinel) + chỉ tiêu suy ra + tăng trưởng |
| `mart_valuation_band` | mã × quý | P/E, P/B, P/S + percentile (own & peer) + nhãn vùng: `rất rẻ` (pct < 0,20) · `rẻ` (< 0,40) · `hợp lý` (< 0,60) · `đắt` (< 0,80) · `rất đắt` (≥ 0,80) |
| `mart_sector_snapshot` | ngành lv2 × quý | Trung vị P/E, P/B, ROE; số mã; return ngành bình quân gia quyền vốn hoá |
| `mart_stock_scorecard` | 1 dòng/mã (kỳ mới nhất) | 5 điểm thành phần + chỉ tiêu thô + `facts` (JSON) + cờ. **Không chứa điểm tổng hợp** |
| `mart_data_quality` | 1 dòng/mã | `data_quality_score` (0–100) + cờ chi tiết |

---

## 7. Bộ chấm điểm

### 7.1 Nguyên tắc

1. **Điểm là percentile trong peer group**, không phải ngưỡng cứng. Thang 0–100.
2. Peer group xác định theo thứ tự: (a) cùng `com_class` **và** cùng ICB lv2, nếu có ≥15 mã đủ điều kiện; (b) ngược lại, cùng `com_class` toàn thị trường. Ghi `peer_basis` và `peer_count` vào từng dòng.
3. Chỉ tiêu "thấp là tốt" (P/E, NPL, CIR, nợ/vốn chủ, biến động) dùng `1 − percent_rank()`.
4. **Không bao giờ so chỉ tiêu giữa các `com_class` khác nhau.**
5. **NULL ≠ 0.** Doanh nghiệp lỗ → `value_score = NULL` kèm cờ `is_loss_making`, không phải 0 điểm. Điểm 0 nghĩa là "đắt nhất nhóm"; NULL nghĩa là "không định giá được bằng P/E".
6. **Chuẩn hoá lại trọng số:** nếu một chỉ tiêu trong công thức bị NULL, trọng số của nó được phân bổ lại cho các chỉ tiêu còn dữ liệu, và ghi `metrics_used_count`. Nếu số chỉ tiêu dùng được < 50% số chỉ tiêu của công thức → điểm thành phần = NULL.

### 7.2 `value_score`

| Chỉ tiêu | Chiều | NONFIN | BANK / OTHERFIN |
|---|---|---|---|
| Percentile P/E so với chính nó 5 năm | thấp tốt | 0,30 | 0,35 |
| Percentile P/B so với chính nó 5 năm | thấp tốt | 0,20 | 0,25 |
| Percentile P/E so với peer | thấp tốt | 0,25 | 0,25 |
| Percentile P/B so với peer | thấp tốt | 0,15 | 0,15 |
| Percentile EV/EBITDA so với peer | thấp tốt | 0,10 | — |

### 7.3 `quality_score`

**NONFIN**

| Chỉ tiêu | Chiều | Trọng số |
|---|---|---|
| ROE trung bình 8 quý | cao tốt | 0,25 |
| `roe_stability` | cao tốt | 0,20 |
| ROIC kỳ mới nhất | cao tốt | 0,20 |
| Xu hướng biên gộp 8 quý | cao tốt | 0,10 |
| `current_ratio` | cao tốt | 0,10 |
| `debt_to_equity` | thấp tốt | 0,15 |

**BANK**

| Chỉ tiêu | Chiều | Trọng số |
|---|---|---|
| ROE trung bình 8 quý | cao tốt | 0,25 |
| `roe_stability` | cao tốt | 0,15 |
| `net_interest_margin` | cao tốt | 0,15 |
| `cir` (đã `abs()`) | thấp tốt | 0,15 |
| `npl` | thấp tốt | 0,15 |
| `car` | cao tốt | 0,05 |
| `casa_ratio` | cao tốt | 0,05 |
| `ldr_loan_deposit_ratio` | thấp tốt | 0,05 |

**OTHERFIN:** ROE trung bình 8 quý (0,35) · `roe_stability` (0,25) · `after_tax_profit_margin` (0,20) · `debt_to_equity` thấp tốt (0,20).

### 7.4 Xử lý `car` / `casa_ratio` thiếu dữ liệu

Trước khi chốt công thức BANK, đo tỉ lệ NULL của `car` và `casa_ratio` trên 27 mã ngân hàng ở kỳ gần nhất. Nếu **> 50% NULL**, loại khỏi công thức và phân bổ lại trọng số theo quy tắc §7.1-6. Kết quả đo phải được ghi vào kế hoạch triển khai.

### 7.5 `growth_score`

| Chỉ tiêu | NONFIN / OTHERFIN | BANK |
|---|---|---|
| CAGR doanh thu 3 năm | 0,30 | `loans_growth` 0,30 |
| CAGR LNST 3 năm | 0,30 | 0,30 |
| YoY doanh thu quý gần nhất | 0,15 | `deposit_growth` 0,15 |
| YoY LNST quý gần nhất | 0,15 | 0,15 |
| `growth_consistency` | 0,10 | 0,10 |

### 7.6 `dividend_score`

`dividend_yield` kỳ mới nhất (0,30) · trung bình 5 năm (0,25) · `dividend_years_consecutive` (0,30) · độ ổn định `1 − CV` (0,15). Công thức như nhau cho mọi `com_class`.

### 7.7 `safety_score`

`avg_turnover_20d` (0,20) · vốn hoá (0,15) · `free_float_percentage` (0,10) · biến động 60 phiên, thấp tốt (0,15) · số quý lỗ trong 12 quý, thấp tốt (0,20) · số năm niêm yết (0,10) · `data_quality_score` (0,10).

### 7.8 `data_quality_score` (`mart_data_quality`)

| Thành phần | Trọng số |
|---|---|
| `quarters_available / 20`, chặn tại 1 | 0,30 |
| Độ phủ phiên giá 1 năm so với số phiên kỳ vọng | 0,25 |
| Độ tươi tỷ số (kỳ mới nhất cách hiện tại ≤ 1 quý) | 0,20 |
| Không còn sentinel rò rỉ ở các chỉ tiêu bắt buộc của `com_class` | 0,15 |
| Không có khoảng trống giá > 10 phiên liên tiếp trong 1 năm | 0,10 |

### 7.9 Fact có cấu trúc — cơ chế chặn LLM bịa số

`mart_stock_scorecard.facts` là mảng JSON:

```json
[
  {"metric": "pe_pct_own_5y", "value": 0.18, "as_of": "2026Q2",
   "text": "P/E 8,3 — thấp hơn 82% số quý trong 5 năm qua của chính mã"},
  {"metric": "roe_avg_8q", "value": 0.163, "as_of": "2026Q2",
   "text": "ROE trung bình 8 quý 16,3%, độ bền 0,87"},
  {"metric": "dividend_years_consecutive", "value": 5, "as_of": "2025",
   "text": "Trả cổ tức tiền mặt 5 năm liên tiếp"}
]
```

**Luật:** mọi con số agent nói ra phải truy ngược được về một fact. Agent không được tự tính toán số mới từ fact.

### 7.10 Điểm tổng hợp tính ở tầng đọc

`mart_stock_scorecard` **chỉ lưu điểm thành phần**. Điểm tổng hợp do `src/scoring.py` tính khi đọc, dựa trên `config/scoring_profiles.yml`:

```yaml
default_profile: bluechip_dividend

universe_defaults:
  exchanges: [HOSE, HNX]
  min_quarters_history: 12
  min_data_quality_score: 60

profiles:
  bluechip_dividend:
    label: "Bluechip cổ tức — tích sản dài hạn"
    universe:
      min_market_cap_vnd: 5_000_000_000_000
      min_avg_turnover_20d_vnd: 5_000_000_000
    weights: {value: 0.25, quality: 0.30, dividend: 0.30, growth: 0.05, safety: 0.10}
    require:
      dividend_years_min: 3
      roe_avg_8q_min: 0.12

  deep_value:
    label: "Định giá sâu — mở rộng xuống mid-cap"
    universe:
      min_market_cap_vnd: 500_000_000_000
      min_avg_turnover_20d_vnd: 1_000_000_000
    weights: {value: 0.45, quality: 0.25, dividend: 0.10, growth: 0.05, safety: 0.15}
    require:
      is_loss_making: false

  quality_growth:
    label: "Chất lượng & tăng trưởng"
    universe:
      min_market_cap_vnd: 2_000_000_000_000
      min_avg_turnover_20d_vnd: 3_000_000_000
    weights: {value: 0.15, quality: 0.35, dividend: 0.05, growth: 0.35, safety: 0.10}
    require:
      roe_avg_8q_min: 0.15
```

**Lý do thiết kế:** đổi trọng số → chạy lại screener trong vài giây, không cần chạy lại dbt. Đây là điều kiện để người dùng *dò ra gu đầu tư* của mình bằng cách so sánh kết quả giữa các profile.

`src/scoring.py` là bản cài đặt **duy nhất**, được cả MCP server và job báo cáo (mảng C) import → hai luồng không bao giờ lệch kết quả.

Nếu một mã có điểm thành phần NULL mà profile gán trọng số > 0 cho thành phần đó, mã bị loại khỏi bảng xếp hạng và liệt kê riêng trong mục "không chấm được", kèm lý do.

---

## 8. MCP server

### 8.1 Bộ tool

Tất cả **read-only**.

| Tool | Tham số | Trả về |
|---|---|---|
| `search_stocks` | `profile`, `filters`, `limit` | Danh sách xếp hạng + 5 điểm thành phần + `facts` + `peer_basis` |
| `get_stock_profile` | `symbol` | Hồ sơ, ngành, `com_class`, 5 điểm, `data_quality` |
| `get_valuation_history` | `symbol`, `years` | P/E, P/B, P/S theo quý + percentile + nhãn vùng |
| `get_financial_history` | `symbol`, `quarters` | Tỷ số + doanh thu/LNST suy ra + tăng trưởng |
| `compare_stocks` | `symbols[]` | So sánh cạnh nhau; **cảnh báo rõ nếu khác `com_class`** |
| `get_sector_snapshot` | `icb_level`, `period` | Trung vị P/E, P/B, ROE, return theo ngành |
| `run_sql` | `query` | Cửa thoát cho câu hỏi ngoài dự kiến |

### 8.2 Ràng buộc kỹ thuật

- Kết nối DuckDB/MotherDuck ở chế độ **read-only**.
- `run_sql`: chặn mọi từ khoá DDL/DML (`INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`, `ATTACH`, `COPY`, `INSTALL`, `LOAD`); giới hạn 1.000 dòng; timeout 30 giây.
- **Mọi tool trả kèm `as_of` và `data_quality`.**

### 8.3 Luật cho agent (`mcp_server/instructions.md`)

1. Không bịa số. Mọi con số phải đến từ `facts` hoặc kết quả tool.
2. Luôn nêu `as_of` khi phát biểu về một mã.
3. Luôn nêu `peer_basis` khi nói "rẻ hơn ngành" — người đọc cần biết đang so với 15 mã hay 300 mã.
4. **Không đưa khuyến nghị mua/bán.** Nêu luận điểm đầu tư kèm **rủi ro đối trọng**.
5. Khi `data_quality_score < 60`, phải nói rõ dữ liệu không đủ để kết luận chắc chắn.
6. Khi so sánh mã khác `com_class`, phải nêu rõ rằng chỉ tiêu không tương đương.

---

## 9. Kiểm chứng dữ liệu

### 9.1 Tầng 1 — Ingestion guard

- **Assertion schema:** kiểm tra các cột bắt buộc tồn tại trong response. Thiếu → **raise, ghi `etl_load_log` với `status='failed'`**. Hành vi hiện tại (in cảnh báo rồi trả DataFrame rỗng) đã che giấu bug V3 suốt nhiều tháng — phải bỏ.
- **Range check:** `close` ∈ `[100, 5.000.000]`; `volume ≥ 0`; `pe` ∈ `[-1000, 1000]`; các tỉ lệ `[-10, 10]`. Dòng ngoài ngưỡng bị loại và **đếm**.
- `etl_load_log` ghi thêm `rows_rejected`. Nếu `rows_rejected / rows_total > 5%` → `status = 'degraded'`.

### 9.2 Tầng 2 — dbt source freshness

| Nguồn | Ngưỡng cảnh báo | Ngưỡng lỗi |
|---|---|---|
| `raw_price_daily` | 2 ngày làm việc | 4 ngày làm việc |
| `raw_financial_ratio` | 10 ngày | 20 ngày |
| `raw_company_info` | 40 ngày | 70 ngày |

### 9.3 Tầng 3 — dbt tests

**Generic:** `unique` + `not_null` cho mọi khoá chính; `relationships` cho `symbol → dim_stock`, `icb_code → dim_industry`; `accepted_values` cho `com_class`, `period_type`, nhãn vùng định giá.

**Singular:**

| Test | Nội dung |
|---|---|
| `assert_price_in_vnd_range` | `stg_price_daily.close` ∈ `[100, 5.000.000]` |
| `assert_value_matches_volume` | Khi cả `value_vnd` và `close × volume` non-null: sai lệch tương đối < 30% |
| `assert_no_weekend_or_future_dates` | Không có `trade_date` rơi vào T7/CN hoặc ở tương lai |
| **`assert_no_bank_sentinel_leak`** | Không dòng `com_class='BANK'` nào còn `roic = 0` hoặc `current_ratio = 0` sau staging (phải là NULL) |
| `assert_no_nonfin_sentinel_leak` | Không dòng `NONFIN` nào còn `npl = 0` hoặc `net_interest_margin = 0` |
| `assert_percentile_in_bounds` | Mọi cột percentile ∈ `[0, 1]` hoặc NULL |
| `assert_peer_group_min_size` | Mọi dòng có percentile peer phải có `peer_count ≥ 8` |
| `assert_scorecard_coverage` | `mart_stock_scorecard` có ≥ 800 mã |
| `assert_derived_revenue_sanity` | `revenue_ttm > 0` và `revenue_ttm` ∈ `[market_cap / 100, market_cap × 100]` |
| `assert_index_not_scaled` | `stg_index_daily.close` của VNINDEX ∈ `[500, 5.000]` |

`assert_no_bank_sentinel_leak` là test quan trọng nhất của spec này — nó chính là lỗi V1, và nếu không có test, lỗi sẽ tái diễn mà không ai biết.

### 9.4 Tầng 4 — Đối chiếu chéo

`scripts/reconcile_warehouse.py`, chạy sau mỗi lần build đầy đủ:

1. **Đếm qua từng layer:** số mã và số dòng ở `raw → staging → mart`. Sụt > 5% giữa hai layer liền kề → cảnh báo.
2. **Đối chiếu với API gốc:** chọn ngẫu nhiên 5 mã, gọi lại `ratio_summary()` và `Quote.history()`, so kỳ gần nhất với warehouse. Sai lệch > 1% → cảnh báo.
3. In báo cáo dạng bảng và trả exit code khác 0 khi có cảnh báo.

### 9.5 Unit test

Theo pattern [`tests/`](../../../tests/) hiện có: `_normalize_company`, `_normalize_financials`, `fetch_index_history`, các hàm chuẩn hoá đơn vị, và `src/scoring.py` (đặc biệt quy tắc chuẩn hoá lại trọng số §7.1-6 và xử lý NULL).

---

## 10. Vận hành

| Workflow | Lịch | Ingest | Transform |
|---|---|---|---|
| `warehouse-daily` | T2–T6, 08:30 UTC | giá EOD + chỉ số | `dbt build --select tag:daily` |
| `warehouse-weekly` | T7, 08:30 UTC | + tỷ số tài chính | `dbt build` toàn bộ |
| `warehouse-monthly` | Ngày 1, 09:00 UTC | + hồ sơ DN + ICB + refresh universe | `dbt build` toàn bộ + `reconcile_warehouse.py` |

`dbt build` chạy model **và** test cùng lúc; test fail → workflow đỏ và không có bước nào chạy tiếp. Dữ liệu hỏng bị chặn **trước khi** agent dùng nó.

MCP server chạy local, đọc `md:vn_market` ở chế độ read-only.

---

## 11. Tiêu chí nghiệm thu

| # | Tiêu chí |
|---|---|
| 1 | `raw_financial_ratio` có ≥ 1.500 mã với đầy đủ 50 cột; 27 mã ngân hàng có `net_interest_margin`, `npl`, `cir` khác NULL ở kỳ gần nhất |
| 2 | `raw_company_info.exchange`, `.icb_code_lv2`, `.com_type_code` khác NULL cho ≥ 95% số mã; `dim_symbols.exchange` khác NULL cho ≥ 95% |
| 3 | `dim_industry` có 177 dòng, đủ 4 cấp |
| 4 | `raw_index_daily` có VNINDEX, VN30, HNXINDEX với ≥ 2.000 phiên mỗi mã; `close` VNINDEX phiên gần nhất trong `[500, 5.000]` — nếu bị nhân nhầm ×1000 sẽ ra ~1.768.000 và tiêu chí này fail |
| 5 | `dbt build` chạy sạch: **mọi model thành công và mọi test pass**, đặc biệt `assert_no_bank_sentinel_leak` |
| 6 | `mart_stock_scorecard` có ≥ 800 mã với ít nhất 3 trong 5 điểm thành phần khác NULL |
| 7 | `src/scoring.py` chạy được cả 3 profile mẫu; mỗi profile trả danh sách xếp hạng khác nhau |
| 8 | Với profile `bluechip_dividend`, **có ít nhất 3 ngân hàng trong top 30** — chứng minh lỗi V1 đã được sửa |
| 9 | MCP server phản hồi đủ 7 tool; `run_sql` từ chối câu lệnh DDL/DML |
| 10 | `reconcile_warehouse.py` chạy sạch với 5 mã ngẫu nhiên |
| 11 | Toàn bộ test pytest hiện có vẫn pass; pipeline bản tin cũ (`main.py`) vẫn chạy được |

Tiêu chí #8 là phép thử trực tiếp cho lỗi nghiêm trọng nhất đã phát hiện.

---

## 12. Rủi ro & giả định

| Rủi ro | Mức | Xử lý |
|---|---|---|
| Nạp lại `raw_financial_ratio` mất ~82 phút, có thể timeout GitHub Actions (giới hạn 6 giờ/job) | Thấp | Nạp lại lần đầu **chạy local**, không qua GHA. Job weekly chỉ cập nhật tăng dần |
| `Company.ratio_summary()` đổi schema ở bản vnstock mới | Trung bình | Assertion schema (§9.1) sẽ fail to thay vì âm thầm hỏng. Ghim `vnstock==4.0.4` trong `requirements.txt` |
| Chỉ tiêu suy ra (doanh thu/LNST) sai với doanh nghiệp có cấu trúc đặc biệt | Trung bình | `assert_derived_revenue_sanity` chặn giá trị vô lý. Mảng B sẽ có số gốc từ BCTC để đối chiếu chéo |
| Ngành ICB lv2 có < 15 mã → percentile peer kém tin cậy | Trung bình | Cơ chế lùi về `com_class` toàn thị trường + ghi `peer_basis`, `peer_count` để agent nêu rõ |
| MotherDuck free tier 10 GB | Thấp | Hiện dùng rất ít so với hạn mức; theo dõi qua `storage_info` |
| Người dùng hiểu điểm số là khuyến nghị mua | **Cao** | Luật §8.3-4 cấm khuyến nghị; mọi đầu ra kèm rủi ro đối trọng và tuyên bố miễn trừ trách nhiệm |

**Giả định:**

- Nguồn VCI miễn phí tiếp tục hoạt động và giữ nguyên schema trong thời gian triển khai.
- `ratio_summary()` không bị giới hạn 8 kỳ như `Finance.*` — đã xác minh: HPG trả 41 dòng từ 2018.
- Người dùng có `VNSTOCK_API_KEY` bậc Community (60 req/phút).

---

## 13. Các mảng tiếp theo

| Mảng | Nội dung | Phụ thuộc |
|---|---|---|
| **B** | BCTC 3 báo cáo · sự kiện DN & cổ tức · khối ngoại · cơ cấu cổ đông | Cần `dim_stock`, `dim_industry` từ mảng A |
| **C** | Job báo cáo luận điểm định kỳ (tháng/quý) · thay bản tin hằng ngày bằng cảnh báo theo sự kiện | Cần `mart_stock_scorecard` và `src/scoring.py` từ mảng A |
| **D** | Vĩ mô (CPI, lãi suất, tỷ giá, tín dụng) · kho tin tức & cơ chế scan | Độc lập, nhưng giá trị cao nhất khi đã có mảng A + B |

Mỗi mảng có spec → plan → triển khai riêng.
