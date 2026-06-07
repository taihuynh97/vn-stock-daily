# 03 — Warehouse & DuckDB

## Files liên quan
- `src/warehouse.py` — tất cả read/write vào DuckDB
- `config/warehouse.yml` — cấu hình sàn và nguồn dữ liệu
- `.env` — chứa `WAREHOUSE_DB=md:vn_market` và `motherduck_token`

---

## DuckDB là gì?

DuckDB là một **analytical database** (cơ sở dữ liệu phân tích) nhúng vào ứng dụng — không cần server riêng, không cần Docker, không cần cài thêm gì. Chỉ cần `pip install duckdb`.

```python
import duckdb
con = duckdb.connect("data/warehouse.duckdb")  # tạo/mở file
con.execute("SELECT COUNT(*) FROM raw_price_daily").fetchone()
```

### Sự khác biệt cốt lõi: OLTP vs. OLAP

| | OLTP | OLAP |
|---|---|---|
| Ví dụ | PostgreSQL, MySQL, SQLite | DuckDB, BigQuery, Snowflake |
| Thiết kế cho | Nhiều transaction nhỏ (INSERT/UPDATE) | Query analytics trên nhiều dòng |
| Lưu trữ | Row-based (dòng liền nhau) | Column-based (cột liền nhau) |
| Ví dụ query | `SELECT * WHERE id=123` (1 dòng) | `SELECT AVG(close) WHERE year=2024` (hàng triệu dòng) |
| Phù hợp với repo này | SQLite (storage.py — log, seen_news) | DuckDB (warehouse — OHLCV lịch sử) |

**Tại sao DuckDB nhanh cho analytics?**
Khi bạn `SELECT AVG(close) FROM raw_price_daily`, DuckDB chỉ đọc cột `close` — không đọc open, high, low, volume... Column storage cho phép điều này.

---

## Schema của Warehouse

### `dim_symbols` — Danh mục mã

```sql
CREATE TABLE dim_symbols (
    symbol       VARCHAR PRIMARY KEY,
    exchange     VARCHAR,       -- HOSE / HNX / UPCOM
    company_name VARCHAR,
    is_active    BOOLEAN DEFAULT TRUE,
    first_seen   DATE,
    last_seen    DATE
);
```

**Naming convention `dim_`**: Trong data warehouse, bảng "dimension" chứa thông tin mô tả (ai, cái gì, ở đâu) — không chứa sự kiện theo thời gian.

### `raw_price_daily` — Giá EOD (End of Day)

```sql
CREATE TABLE raw_price_daily (
    symbol     VARCHAR,
    trade_date DATE,
    open       DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    close      DOUBLE,
    volume     BIGINT,
    value      DOUBLE,       -- giá trị giao dịch (VND)
    loaded_at  TIMESTAMP,    -- khi nào nạp vào warehouse
    PRIMARY KEY (symbol, trade_date)
);
```

**Naming convention `raw_`**: Data thô chưa qua transform. Trong pipeline ELT, đây là landing zone đầu tiên.

**OHLCV là gì?**
- **O**pen: giá mở cửa
- **H**igh: giá cao nhất trong phiên
- **L**ow: giá thấp nhất trong phiên
- **C**lose: giá đóng cửa
- **V**olume: khối lượng (số cổ phiếu)

Đây là dữ liệu chuẩn trong mọi hệ thống phân tích chứng khoán trên thế giới.

### `raw_financial_ratio` — Tỷ số tài chính (Phase 2A)

```sql
CREATE TABLE raw_financial_ratio (
    symbol      VARCHAR,
    period      VARCHAR,      -- "2023", "2022"...
    period_type VARCHAR,      -- "year" hoặc "quarter"
    pe          DOUBLE,       -- Price/Earnings
    pb          DOUBLE,       -- Price/Book
    roe         DOUBLE,       -- Return on Equity
    roa         DOUBLE,       -- Return on Assets
    eps         DOUBLE,       -- Earnings per Share
    loaded_at   TIMESTAMP,
    PRIMARY KEY (symbol, period, period_type)
);
```

### `raw_company_info` — Thông tin công ty (Phase 2A)

```sql
CREATE TABLE raw_company_info (
    symbol        VARCHAR PRIMARY KEY,
    company_name  VARCHAR,
    exchange      VARCHAR,
    industry_icb  VARCHAR,    -- phân loại theo ICB (Industry Classification Benchmark)
    sector        VARCHAR,
    listed_date   DATE,
    loaded_at     TIMESTAMP
);
```

### `etl_load_log` — Nhật ký load

```sql
CREATE TABLE etl_load_log (
    job_name     VARCHAR,     -- "warehouse_daily", "warehouse_weekly"...
    target_table VARCHAR,
    run_at       TIMESTAMP,
    rows_loaded  BIGINT,
    status       VARCHAR,     -- "ok" / "empty" / "skipped"
    watermark    VARCHAR,     -- thường là run_date
    notes        VARCHAR
);
```

**Tại sao cần log?**
Trong data engineering, **observability** (khả năng quan sát) rất quan trọng:
- Biết job chạy thành công hay fail
- Biết đã load bao nhiêu dòng
- Debug khi data không như kỳ vọng
- Phát hiện schema drift (API bỗng trả ít cột hơn → rows_loaded = 0)

---

## Upsert Pattern trong DuckDB

**Upsert** = UPDATE nếu đã tồn tại, INSERT nếu chưa có. (UP-date + in-SERT)

```python
def upsert_prices(con, df) -> int:
    con.register("df_px", df)
    con.execute("""
        INSERT OR REPLACE INTO raw_price_daily
        SELECT symbol, trade_date, open, high, low, close, volume, value, now()
        FROM df_px;
    """)
    con.unregister("df_px")
    return len(df)
```

**`con.register()` và `con.unregister()`**:
DuckDB cho phép đăng ký một Python DataFrame như một "bảng ảo" để dùng trong SQL query. Đây là cách hiệu quả để INSERT nhiều dòng cùng lúc thay vì loop.

**`con.unregister()`**: giải phóng bộ nhớ sau khi dùng xong. Thiếu bước này → memory leak nếu chạy nhiều lần.

### So sánh các cách upsert trong Python + database

| Cách | Ví dụ | Ưu/nhược |
|---|---|---|
| **INSERT OR REPLACE** (DuckDB/SQLite) | Code trên | Đơn giản, atomic, thay cả dòng |
| **ON CONFLICT DO UPDATE** (PostgreSQL) | `INSERT ... ON CONFLICT ... DO UPDATE SET col=excluded.col` | Update từng cột, giữ cột khác |
| **Merge/Upsert** (Spark/dbt) | `MERGE INTO target USING source ON ...` | Linh hoạt, dùng cho big data |
| **Delete + Insert** | Xóa cũ, insert mới | Đơn giản nhưng không atomic |

---

## Kết nối: Local vs. MotherDuck

```python
# src/warehouse.py
def get_conn():
    db = os.getenv("WAREHOUSE_DB", DEFAULT_DB)
    if db.startswith("md:"):
        return duckdb.connect(db)  # MotherDuck
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(db)     # File local
```

**Biến môi trường điều khiển**:
- `WAREHOUSE_DB` không set → `data/warehouse.duckdb` (local, dùng để test)
- `WAREHOUSE_DB=md:vn_market` + `motherduck_token=...` → MotherDuck cloud

**Tại sao pattern này tốt?**
- Code không thay đổi dù chạy local hay cloud.
- Dev: dùng local, không tốn quota MotherDuck.
- Production (GitHub Actions): dùng MotherDuck cloud, lưu trữ bền vững.

### MotherDuck là gì?

MotherDuck = DuckDB as a Service. Bạn upload dữ liệu lên cloud, query từ bất cứ đâu.

**Free tier limits:**
- Storage: 10 GB (ổn)
- Compute: DPU (DuckDB Processing Units) hằng ngày — có giới hạn
- Backfill 1.1M dòng dùng nhiều DPU trong 1 ngày → thấy warning "daily compute limit"
- Job daily thông thường (~1,500 mã × 1 ngày) dùng rất ít DPU → nằm thoải mái trong free tier

### So sánh các lựa chọn lưu trữ

| Giải pháp | Loại | Chi phí | Phù hợp với project |
|---|---|---|---|
| **DuckDB local file** | Embedded DB | Free | Dev/test |
| **MotherDuck** (đang dùng) | Cloud DuckDB | Free tier | Small-medium project |
| **BigQuery** | Cloud OLAP | Pay per query | Enterprise, nhiều user |
| **Snowflake** | Cloud OLAP | Subscription | Enterprise |
| **PostgreSQL (Supabase)** | Cloud OLTP | Free tier | Nếu cần many-write |
| **Parquet files trên S3** | File storage | Rất rẻ | Nếu chỉ cần đọc batch |

---

## Layered Warehouse Architecture

Trong data engineering, warehouse thường có nhiều lớp:

```
Raw Layer     → Staging Layer → Mart Layer
(raw_*)         (stg_*)          (mart_*)
               (dbt transform)  (dbt transform)
```

**Repo này hiện ở đâu:**
- **Raw layer**: ✅ Đã có — `raw_price_daily`, `raw_financial_ratio`, `raw_company_info`
- **Staging layer**: ❌ Chưa có — Phase 3 (dbt) sẽ tạo các view/table đã clean, join, chuẩn hoá
- **Mart layer**: ❌ Chưa có — Phase 3: `mart_daily_signals` (mỗi mã × ngày có đủ RSI, MA...)

**Ví dụ mart layer tương lai:**
```sql
-- mart_daily_signals (sau Phase 3)
SELECT
    p.symbol,
    p.trade_date,
    p.close,
    AVG(p.close) OVER (PARTITION BY p.symbol ORDER BY p.trade_date ROWS 19 PRECEDING) AS ma20,
    f.pe,
    f.roe,
    c.industry_icb
FROM raw_price_daily p
LEFT JOIN raw_financial_ratio f ON p.symbol = f.symbol AND f.period_type = 'year'
LEFT JOIN raw_company_info c ON p.symbol = c.symbol
```

---

## Pattern SQL quan trọng: LEFT JOIN + IS NULL — "Tìm cái chưa được xử lý"

Đây là pattern SQL xuất hiện khắp nơi trong DE: tìm những bản ghi ở bảng A mà **chưa có** trong bảng B.

Trong repo, dùng trong `get_pending_symbols()`:

```sql
SELECT d.symbol
FROM dim_symbols d
LEFT JOIN backfill_status b ON d.symbol = b.symbol
WHERE d.is_active
  AND (b.symbol IS NULL OR b.status != 'done')
```

**Đọc từng phần:**

`LEFT JOIN backfill_status b`: Lấy tất cả mã từ `dim_symbols`, kèm theo row tương ứng từ `backfill_status` nếu có. Nếu không có → tất cả cột của `b` là `NULL`.

`b.symbol IS NULL`: Mã chưa có dòng nào trong `backfill_status` → chưa bắt đầu backfill.

`b.status != 'done'`: Mã đã có dòng nhưng chưa hoàn thành (đang `error` hoặc `pending`).

**Visualize:**

```
dim_symbols          backfill_status       Kết quả LEFT JOIN
───────────          ───────────────       ──────────────────────────────
AAA                  BBB | done            AAA | NULL (chưa có → pending)
BBB                  HPG | error           BBB | done  (có, đã xong)
HPG                                        HPG | error (có, chưa xong)
VNM                                        VNM | NULL (chưa có → pending)
```

Query trả về: AAA, HPG, VNM — bỏ qua BBB.

**Tại sao không dùng `NOT IN`?**

```sql
-- Cách naive (có vấn đề với NULL):
WHERE d.symbol NOT IN (SELECT symbol FROM backfill_status WHERE status = 'done')
```

`NOT IN` với subquery trả về `NULL` → toàn bộ `WHERE` clause trả về `FALSE` — một bug khó debug. LEFT JOIN + IS NULL là idiomatic và an toàn hơn.

**Gặp pattern này ở đâu trong thực tế:**
- Tìm order chưa được ship
- Tìm user chưa nhận email
- Tìm bản ghi trong staging chưa được load vào mart
- Reconciliation: tìm record ở source nhưng thiếu trong target

---

## Khái niệm: Watermark và Incremental Load

**Watermark** = mốc thời gian để biết đã load đến đâu.

```python
warehouse.log_load(
    con, "warehouse_daily", "raw_price_daily",
    n_px, "ok",
    watermark=run_date   # "2026-06-07"
)
```

Trong incremental load: "Lần tới, chỉ nạp data từ watermark trở đi."

**Full reload vs. Incremental:**
- **Full reload**: Mỗi lần chạy, nạp toàn bộ lịch sử. Chậm, an toàn.
- **Incremental**: Chỉ nạp dữ liệu mới. Nhanh, nhưng cần xử lý late arrival (data đến muộn).

Repo này dùng **hybrid**:
- `fetch_eod_prices`: chỉ lấy giá HÔM NAY → incremental tự nhiên.
- `backfill`: nạp toàn bộ lịch sử → full reload một lần.
- `upsert_prices`: `INSERT OR REPLACE` → dù nạp lại cũng không bị trùng.
