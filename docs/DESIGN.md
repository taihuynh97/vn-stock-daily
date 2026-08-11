# VN Market Data Platform — Tài liệu thiết kế

> Mục tiêu: xây dựng cơ sở dữ liệu toàn thị trường chứng khoán Việt Nam, thu thập một lần và **tái sử dụng** cho nhiều phân tích/báo cáo: theo dõi danh mục, screener, phân tích ngành, theo dõi thị trường, backtest.

---

## 1. Nguyên tắc cốt lõi (cũng là các khái niệm DE nền tảng)

1. **Tách ingestion khỏi consumption.** Pipeline thu thập dữ liệu hoạt động độc lập với các phân tích dùng dữ liệu đó. Đổi danh mục cá nhân không ảnh hưởng việc thu thập.
2. **Supply-driven, không demand-driven.** Thu *tất cả* mã, không chỉ mã đang cần. Kho dữ liệu là tài sản, không phải sản phẩm phụ của bản tin.
3. **Raw layer là immutable / append-only.** Không bao giờ transform tại chỗ. Raw là source of truth; logic đổi thì chạy lại transform, raw giữ nguyên.
4. **Idempotency.** Mọi job chạy lại được an toàn nhờ upsert theo khóa tự nhiên (vd `symbol + date`).
5. **Incremental processing.** Chỉ xử lý dữ liệu mới (dùng watermark / load log), không quét lại toàn bộ.
6. **Một source of truth.** Tất cả consumer đọc từ cùng một warehouse.
7. **Transform bằng dbt.** SQL được version control, test, document, có lineage.
8. **Observability.** Log mọi lần load (bảng `etl_load_log`) để debug và theo dõi độ tươi của dữ liệu.

---

## 2. Catalog nguồn dữ liệu

Tất cả qua thư viện **vnstock 4.x** (kết nối các API công khai). Phân theo *tần suất cập nhật thực tế* của từng loại — đây là điểm mấu chốt: không phải cái gì cũng thu hằng ngày.

| Nhóm dữ liệu | vnstock method | Tần suất thu | Vì sao |
|---|---|---|---|
| Giá EOD (toàn TT) | `Trading.price_board(symbols)` | **Hằng ngày** | Bulk — lấy nhiều mã/call, rẻ |
| Chỉ số | `Quote.history('VNINDEX'…)` | Hằng ngày | Bối cảnh thị trường |
| Khối ngoại | `Trading.foreign_trade` | Hằng ngày | Tín hiệu dòng tiền ngoại |
| Báo cáo tài chính | `Finance.ratio / income_statement / balance_sheet / cash_flow` | **Hằng tuần** | Quý mới đổi (~4 lần/năm/mã), refresh tuần để bắt báo cáo mới |
| Sự kiện · cổ tức | `Company.events` | Hằng tuần | Điều chỉnh giá, ex-date |
| Danh sách mã | `Listing.all_symbols / symbols_by_exchange` | **Hằng tháng** | Bắt mã mới niêm yết / huỷ niêm yết |
| Hồ sơ DN, ngành | `Company.overview / officers / shareholders` | Hằng tháng | Gần như tĩnh |
| Tin tức | `Company.news` | **On-demand** | Chỉ thu cho watchlist, KHÔNG cho cả 1.600 mã (quá tốn) |
| Backfill lịch sử giá | `Quote.history(symbol)` | **Một lần** | Chạy chia nhỏ để nạp lịch sử ban đầu |

### Lưu ý quan trọng về tin tức
Thu tin per-mã cho 1.600 mã mỗi ngày là không khả thi (mỗi mã 1 call). Chiến lược: chỉ thu tin cho **watchlist** (mã đang giữ + mã screener quan tâm), hoặc thu luân phiên. Tin tức là nhóm duy nhất *không* thu toàn thị trường.

---

## 3. Chi phí — chỗ nào free, chỗ nào trả phí

| Thành phần | Free? | Ghi chú |
|---|---|---|
| vnstock — Guest | Free | 20 req/phút — quá chậm cho warehouse |
| vnstock — **Community** | **Free** (chỉ cần đăng ký key) | 60 req/phút — **đủ cho toàn bộ warehouse EOD** |
| vnstock — Sponsor | Trả phí | 180-600 req/phút — chỉ cần nếu muốn intraday hoặc backfill cực nhanh |
| DuckDB / MotherDuck | Free 10GB | Vài triệu dòng vẫn còn xa giới hạn |
| GitHub Actions | Free 2.000 phút/tháng | Job daily ~vài phút → dư sức |
| Streamlit Community Cloud | Free | Public repo |
| Prefect Cloud | Free tier | Khi thêm orchestration |
| **Claude API (digest)** | **Trả phí** | Chi phí rất nhỏ (~vài cent/ngày). Là phần trả phí duy nhất, và **tuỳ chọn** (có thể làm digest bằng rule thuần) |

**Kết luận chi phí:** bản thân warehouse có thể chạy **100% free** với vnstock Community + DuckDB/MotherDuck + GitHub Actions. Phần trả phí duy nhất là Claude cho bản tin AI — nhỏ và không bắt buộc.

Nếu sau này cần dữ liệu chuyên sâu hơn (backtest nghiêm túc, dữ liệu đã điều chỉnh đầy đủ), có các nhà cung cấp thương mại VN (FiinPro, Wichart…) nhưng đắt và **chưa cần** cho mục tiêu hiện tại.

---

## 4. Kiến trúc giải pháp

Ba job ingestion theo lịch khác nhau, cùng ghi vào một warehouse, nhiều consumer đọc ra. (Xem sơ đồ `architecture-v2.html`.)

```
INGESTION (theo cadence)              WAREHOUSE                 CONSUMERS
  job_daily    ──┐                    raw_*  (immutable)        ├─ digest/Telegram
  job_weekly   ──┼──►  upsert/append ─► stg_*  (dbt clean)  ──► ├─ Streamlit dashboard
  job_monthly  ──┘                     mart_* (dbt business) ─► ├─ DBeaver ad-hoc
  job_backfill (1 lần)                 control: dim_symbols,    └─ báo cáo / backtest
                                                etl_load_log
ORCHESTRATION: GitHub Actions (cron) → sau này Prefect Cloud (monitoring/retry)
```

---

## 5. Thiết kế database

### 5.1 RAW layer (Python ghi trực tiếp)

```
raw_price_daily        symbol, trade_date, open, high, low, close, volume, value
                       PK (symbol, trade_date)              -- append/upsert daily

raw_index_daily        index_code, trade_date, open, high, low, close, volume
                       PK (index_code, trade_date)

raw_foreign_trade      symbol, trade_date, buy_vol, sell_vol, net_value
                       PK (symbol, trade_date)

raw_financial_ratio    symbol, year, quarter, period_type, ratio_type + 44 chỉ tiêu
                       PK (symbol, year, quarter)           -- upsert weekly
                       50 cột. quarter 1-4 = TTM kết thúc tại quý đó;
                       quarter = 5 = cả năm.
                       Ba nhóm chỉ tiêu theo khả dụng (xem warehouse.RATIO_*):
                         COMMON (13) — cả ngân hàng lẫn phi tài chính đều có thật
                         NONFIN (15) — ngân hàng trả sentinel 0.0, phải NULL hoá
                         BANK   (16) — phi tài chính trả sentinel 0.0/None
                       LƯU Ý: sentinel 0.0 được GIỮ NGUYÊN ở raw. Việc NULL hoá
                       theo com_class diễn ra ở tầng staging (mảng A2).

raw_financial_stmt     symbol, period, period_type, stmt_type, line_item, value
                       PK (symbol, period, period_type, stmt_type, line_item)

raw_company_info       symbol, company_name, short_name, exchange, com_type_code,
                       is_bank, icb_code_lv2, icb_code_lv4, sector, market_cap,
                       issue_share, free_float_percentage, foreigner_percentage,
                       maximum_foreign_percentage, state_percentage,
                       avg_match_value_1m, avg_match_volume_1m,
                       highest_price_1y, lowest_price_1y, listed_date, loaded_at
                       PK (symbol)                          -- upsert monthly
                       com_type_code phân loại CT/NH/BH/CK (thường/ngân hàng/
                       bảo hiểm/chứng khoán) — nguồn chính suy ra com_class.
                       exchange lấy từ com_group_code qua _map_exchange():
                       VNINDEX→HOSE, HNXIndex→HNX, UpcomIndex→UPCOM, OTC→OTC.

dim_industry           icb_code, icb_name (tiếng Việt), en_icb_name, level (1-4),
                       loaded_at    PK (icb_code)           -- refresh monthly

raw_index_daily        index_code, trade_date, open, high, low, close, volume
                       PK (index_code, trade_date)          -- append daily
                       VNINDEX, VN30, HNXINDEX. LƯU Ý: giá trị chỉ số KHÔNG
                       nhân ×1000 như giá cổ phiếu — dùng fetch_index_history()
                       chứ không phải fetch_history_one().

raw_corporate_event    symbol, event_type, ex_date, record_date, ratio, description
raw_news               news_id, symbol, title, published_date, url, source, loaded_at
                       PK (news_id)
```

#### 5.1.1 Lưu ý chất lượng dữ liệu — `raw_price_daily`

- **Đơn vị**: `open/high/low/close` luôn ở đơn vị **VNĐ** (không phải nghìn VNĐ).
  `Trading.price_board` (daily, nguồn VCI) trả VND, còn `Quote.history` (backfill)
  trả nghìn VNĐ — `ingest_market.fetch_history_one` nhân lại ×1000 để hai nguồn
  đồng nhất. (Dữ liệu cũ đã được sửa qua `scripts/fix_backfill_units.py`.)
- **`value` (giá trị khớp lệnh) thường NULL cho các dòng backfill**: endpoint
  `Quote.history` của VCI không trả turnover/giá trị giao dịch, nên các dòng nạp
  qua `backfill.py` có `value = NULL`. Chỉ các dòng nạp qua `price_board`
  (job daily) mới có `value`. Đây là giới hạn của API nguồn, không phải lỗi —
  không cố tính xấp xỉ giá trị này.
- **Lịch giao dịch**: `ingest_market.is_trading_day()` hiện chỉ kiểm tra
  Thứ 2–6, **chưa loại trừ ngày lễ VN**. `build_warehouse.py` bỏ qua việc nạp
  giá EOD vào Thứ 7/CN. Một lần chạy thủ công vào Chủ Nhật 2026-06-07 (trước khi
  có guard này) đã tạo ra 1.573 dòng `trade_date=2026-06-07` với dữ liệu không
  nhất quán (close không khớp OHLV) — đã xoá qua `scripts/fix_phantom_sunday.py`.

### 5.2 CONTROL layer (metadata — quản trị pipeline)

```
dim_symbols      symbol, exchange, company_name, is_active, first_seen, last_seen
                 -- danh sách mã chuẩn, refresh hằng tháng; đánh dấu mã huỷ niêm yết

etl_load_log     job_name, run_at, target_table, rows_loaded, status, watermark, notes
                 -- log mỗi lần load → resumable backfill + theo dõi độ tươi
```

> `etl_load_log` + `watermark` là khái niệm DE quan trọng: nó cho biết "đã load tới đâu", giúp incremental và phục hồi khi job fail giữa chừng.

### 5.3 STAGING layer (dbt — clean, cast, dedup)

```
stg_price_daily        cast kiểu, loại trùng, thêm prev_close, daily_return
stg_financial_ratio    chuẩn hoá tên cột, dedup theo (symbol, period)
stg_company_info       latest snapshot mỗi mã (SCD type 1)
stg_foreign_trade
```

### 5.4 MART layer (dbt — business-ready, đây là phần TÁI SỬ DỤNG)

```
dim_stock              1 dòng/mã: info + ngành + ratios mới nhất
fct_price_daily        giá sạch + chỉ báo (MA20/50/200, RSI, return 1m/3m/ytd)
fct_financials         chỉ số tài chính theo thời gian mỗi mã
mart_sector_daily      tổng hợp cấp ngành: P/E trung vị, return ngành, dòng tiền
mart_market_breadth    độ rộng thị trường: số mã tăng/giảm, % mã trên MA50
mart_portfolio         hiệu suất danh mục (join holdings ↔ fct_price_daily)
mart_screener          quét toàn thị trường bằng SQL theo bộ tiêu chí
```

Bất kỳ phân tích/báo cáo mới nào sau này chỉ cần query mart layer — đó là ý nghĩa của "tái sử dụng".

---

## 6. Roadmap theo phase

| Phase | Nội dung | Kết quả |
|---|---|---|
| **1** | Warehouse + `dim_symbols` + job thu giá EOD toàn TT (bulk) | Mỗi ngày kho tự đầy thêm |
| **1.5** | Backfill lịch sử giá (một lần, chia nhỏ) | Có chiều sâu lịch sử |
| **2** | Thêm job weekly (tài chính) + monthly (info). Refactor digest/screener đọc từ kho | Consumer hết phụ thuộc API |
| **3** | dbt staging + mart. Build Streamlit dashboard | Nền cho mọi phân tích |
| **4** | Prefect Cloud: monitoring, retry, lineage | Vận hành như platform thật |

---

## 7. Những khái niệm DE bạn sẽ học qua dự án này

- **Layered architecture** (raw → staging → mart) và vì sao tách layer.
- **Incremental load + watermark** — chỉ xử lý dữ liệu mới.
- **Idempotency & upsert** — chạy lại an toàn.
- **Slowly Changing Dimension (SCD)** — xử lý dữ liệu thay đổi chậm (company info).
- **Bulk vs per-row ingestion** — đánh đổi giữa tốc độ và độ chi tiết.
- **Cadence-aware scheduling** — thu mỗi loại dữ liệu theo tần suất riêng.
- **Orchestration & observability** — lịch chạy, retry, log, lineage.
- **dbt modeling & testing** — transform có kỷ luật, có test, có doc.
- **Separation of ingestion vs consumption** — nền tảng của data platform.
