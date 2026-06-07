# VN Market Data Platform — Master Roadmap & Task Spec

> **Source of truth** cho cả lộ trình. Giao cho Claude Code (VS Code) thực thi theo từng phase.
> Đọc phần *Cách dùng* + *Kiến trúc* trước. Làm tuần tự, dừng & báo cáo cuối mỗi phase.

---

## Cách dùng tài liệu này (cho Claude Code)

- Làm **lần lượt từng phase**, không nhảy cóc. Mỗi phase có Goal → Tasks → Acceptance → Báo cáo.
- **DỪNG ở cuối mỗi phase**, báo cáo theo mục "Báo cáo", chờ người dùng xác nhận trước khi sang phase sau.
- Việc cần con người (đăng ký dịch vụ, lấy token) nằm ở mục *Human-only* — KHÔNG tự làm.
- Khi gọi API vnstock lần đầu cho một loại dữ liệu mới: **in ra tên cột thật** rồi mới map (vì cột tuỳ nguồn).
- Test local trước, lên cloud (MotherDuck) sau.

---

## Kiến trúc & nguyên tắc (bối cảnh)

Hai pipeline độc lập trong repo `vn-stock-daily`:

1. **News pipeline** (`main.py`): ingest → signals → screener → digest(Claude) → notify(Telegram).
2. **Warehouse pipeline** (`build_warehouse.py`): ingest_market → warehouse(DuckDB). Thu dữ liệu toàn thị trường để tái sử dụng.

Layering dữ liệu: `raw_*` (immutable, Python ghi) → `stg_*` (dbt clean) → `mart_*` (dbt business, nơi mọi phân tích query vào).

Nguyên tắc: tách ingestion/consumption · supply-driven · raw immutable · idempotent (upsert) · incremental (watermark) · transform bằng dbt · observability (etl_load_log).

DB: DuckDB, kết nối qua env `WAREHOUSE_DB` (local file mặc định, `md:vn_market` cho MotherDuck cloud).

---

## Trạng thái hiện tại

- ✅ News pipeline: chạy ổn (SQLite tạm, gửi Telegram OK).
- ✅ Phase 1 files đã tạo: `src/warehouse.py`, `src/ingest_market.py`, `build_warehouse.py`, `config/warehouse.yml`, `.github/workflows/warehouse.yml`, `requirements.txt`(+duckdb).
- ⏳ Đang tích hợp & test Phase 1.

---

## PHASE 1 — Nền warehouse (giá EOD toàn thị trường)

**Status: files đã có, cần tích hợp + verify.** Chi tiết đầy đủ ở `PHASE1_TASKS.md`.

**Goal:** chạy `build_warehouse.py` local → tạo `data/warehouse.duckdb` với `dim_symbols`, `raw_price_daily`, `etl_load_log`; xác nhận tên cột thật của `price_board`.

**Tasks tóm tắt:**
- [ ] Verify 6 file Phase 1 đúng vị trí; `requirements.txt` có `duckdb`.
- [ ] `pip install -r requirements.txt`.
- [ ] `python build_warehouse.py`.
- [ ] Query kiểm tra 3 bảng.

**Acceptance:** `dim_symbols` > 500 mã; `raw_price_daily.close` không null cho phần lớn mã; có dòng trong `etl_load_log`.

**Báo cáo:** dòng `[price_board] cột thật: [...]` + số mã + số dòng giá.

**DE concepts:** layered warehouse · upsert/idempotency · bulk ingestion · load log.

---

## PHASE 1.5 — Backfill lịch sử giá (một lần)

**Goal:** nạp lịch sử OHLCV (mặc định 3 năm) cho mọi mã trong `dim_symbols`, **resumable** (chạy lại không nạp lại mã đã xong). Lưu ý: `Quote.history` cho OHLC đầy đủ (price_board chỉ có close).

**Tasks:**
- [ ] Thêm bảng control `backfill_status (symbol, status, last_date, updated_at)` trong `warehouse.py`.
- [ ] Thêm `ingest_market.fetch_history_one(symbol, start, end)` (wrap `Quote.history`, chuẩn hoá cột về schema `raw_price_daily`).
- [ ] Tạo `backfill.py` (entry point): lấy mã chưa `done` từ `backfill_status`, loop, upsert vào `raw_price_daily`, đánh dấu done. Tôn trọng `_throttle()`. Có thể chạy nhiều lần để hoàn tất.
- [ ] Tham số `--years` (default 3) và `--limit` (số mã mỗi lần chạy, để chia nhỏ).

**Acceptance:** sau khi chạy đủ, `SELECT count(DISTINCT symbol) FROM raw_price_daily WHERE trade_date < today` ≈ số mã; mỗi mã có ~250 phiên/năm.

**Báo cáo:** số mã đã backfill / tổng số; số dòng `raw_price_daily`; mã nào fail.

**Human-only:** không có.

**DE concepts:** resumable backfill · checkpoint/idempotency · chunking để né rate limit.

---

## PHASE 2 — Ingestion đa nhịp + refactor consumer

### 2A. Thu dữ liệu chậm hơn (weekly / monthly)

**Goal:** thêm báo cáo tài chính (weekly) và hồ sơ DN (monthly) vào warehouse.

**Tasks:**
- [ ] Bảng mới trong `warehouse.py`: `raw_financial_ratio (symbol, period, period_type, pe, pb, roe, roa, eps, ...)` PK `(symbol,period,period_type)`; `raw_company_info (symbol, company_name, exchange, industry_icb, sector, listed_date, loaded_at)`.
- [ ] `ingest_market.fetch_financials(symbols)` — wrap `Finance.ratio` (in cột thật lần đầu, map mềm).
- [ ] `ingest_market.fetch_company_info(symbols)` — wrap `Company.overview`.
- [ ] Gộp vào `build_warehouse.py` qua tham số `--mode {daily|weekly|monthly}`; daily = giá, weekly = +financials, monthly = +company_info + refresh universe.
- [ ] Workflows mới: `.github/workflows/warehouse-weekly.yml` (cron T7), `warehouse-monthly.yml` (ngày 1 hằng tháng).

**Acceptance:** `raw_financial_ratio` có pe/pb/roe cho phần lớn mã; `raw_company_info` có industry.

### 2B. Refactor news pipeline đọc từ warehouse

**Goal:** digest/screener KHÔNG gọi API lịch sử nữa, đọc từ warehouse (nhanh, hết rate limit).

**Tasks:**
- [ ] `warehouse.read_price_history(symbol, days)` → DataFrame OHLCV từ `raw_price_daily`.
- [ ] `ingest.fetch_history` → đọc warehouse; chỉ gọi API lấy candle hôm nay nếu thiếu (delta).
- [ ] `screener.run` → query warehouse cho cả universe thay vì loop API từng mã.
- [ ] Giữ `signals.py`, `digest.py`, `notify.py` nguyên (chỉ đổi nguồn dữ liệu, không đổi logic).

**Acceptance:** `python main.py` chạy nhanh hơn rõ rệt, không phát sinh rate limit; bản tin vẫn gửi Telegram đúng.

**Báo cáo:** thời gian chạy `main.py` trước/sau; số call API còn lại.

**Human-only:** thêm secrets cho workflow mới (dùng lại `MOTHERDUCK_TOKEN`, `VNSTOCK_API_KEY`).

**DE concepts:** incremental/delta load · cadence-aware scheduling · tách ingestion↔consumption thật sự.

---

## PHASE 3 — dbt transforms + dashboard

### 3A. dbt project

**Goal:** layer staging + mart bằng dbt-duckdb trên warehouse.

**Tasks:**
- [ ] `pip install dbt-duckdb`; `dbt init transforms` (thư mục `transforms/` trong repo).
- [ ] `profiles.yml` trỏ vào `WAREHOUSE_DB` (local hoặc `md:vn_market`).
- [ ] `sources.yml` khai báo các bảng `raw_*`.
- [ ] Staging: `stg_price_daily`, `stg_financial_ratio`, `stg_company_info` (cast, dedup, chuẩn hoá).
- [ ] Mart: `dim_stock`, `fct_price_daily` (+MA20/50/200, RSI, return), `mart_sector_daily`, `mart_market_breadth`, `mart_screener`.
- [ ] `schema.yml`: test `unique`, `not_null`, `relationships`.
- [ ] Thêm bước `dbt run` vào workflow sau ingestion (hoặc workflow riêng).

**Acceptance:** `dbt run` + `dbt test` pass; mart tables có dữ liệu hợp lý.

### 3B. Streamlit dashboard

**Goal:** dashboard đọc từ mart layer, deploy free.

**Tasks:**
- [ ] `app.py` (Streamlit) kết nối DuckDB/MotherDuck, đọc mart.
- [ ] Trang: Tổng quan thị trường (breadth, top tăng/giảm) · Danh mục · Phân tích ngành · Screener tương tác.
- [ ] Deploy Streamlit Community Cloud từ GitHub.

**Acceptance:** dashboard chạy local (`streamlit run app.py`) và bản deploy mở được.

**Human-only:** kết nối Streamlit Community Cloud với GitHub repo; cấu hình secret token.

**DE concepts:** dbt modeling/testing/lineage · semantic mart layer · data product (dashboard).

---

## PHASE 4 — Orchestration & observability

**Goal:** vận hành như platform thật (monitoring, retry, lineage) thay cho cron trần.

**Tasks:**
- [ ] `pip install prefect`; chuyển các job thành Prefect `@flow`/`@task`.
- [ ] Tạo deployments có schedule (daily/weekly/monthly) trên Prefect Cloud.
- [ ] Retry tự động + thông báo lỗi qua Telegram (tái dùng `notify.py`).
- [ ] (Tuỳ chọn) data freshness check: cảnh báo nếu `raw_price_daily` không có dữ liệu hôm nay.

**Acceptance:** flow chạy theo lịch trên Prefect Cloud, có log/retry; alert khi fail.

**Human-only:** tạo tài khoản Prefect Cloud, lấy API key, cấu hình work pool.

**DE concepts:** orchestration · retry/alerting · data freshness/SLA · lineage.

---

## Ràng buộc toàn cục (cho Claude Code)

- **Trước Phase 2B**, KHÔNG sửa news pipeline (`main.py`, `ingest.py`, `signals.py`, `screener.py`, `digest.py`, `notify.py`, `storage.py`). Phase 2B mới được đổi *nguồn dữ liệu* của `ingest.py`/`screener.py`, vẫn giữ logic.
- Mọi ingestion mới: in cột thật lần đầu, map mềm, bọc try/except, không để 1 mã lỗi làm vỡ job.
- Mọi ghi DB: upsert idempotent + ghi `etl_load_log`.
- Test local trước; lên MotherDuck/cloud sau.
- Dừng & báo cáo cuối mỗi phase.

## Human-only tasks (tổng hợp)

- [ ] (Phase 1) MotherDuck: tạo `vn_market`, lấy token → secret `MOTHERDUCK_TOKEN`.
- [ ] (Có sẵn) `VNSTOCK_API_KEY`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- [ ] (Phase 3B) Kết nối Streamlit Community Cloud ↔ GitHub.
- [ ] (Phase 4) Tài khoản Prefect Cloud + API key.
