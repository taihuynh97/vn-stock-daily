# 07 — Nền tảng Data Engineer

Đây là tài liệu quan trọng nhất nếu bạn muốn chuyển từ Data Analyst sang Data Engineer. Mọi khái niệm đều được liên kết trực tiếp với code trong repo này để bạn có anchor cụ thể khi học.

---

## Data Engineer là ai?

| | Data Analyst | Data Engineer |
|---|---|---|
| **Câu hỏi chính** | "Dữ liệu nói lên điều gì?" | "Dữ liệu ở đâu, làm sao lấy được, lưu sao?" |
| **Công cụ chính** | SQL, Excel, Tableau, Python (pandas) | Python, SQL, Spark, Airflow, dbt, cloud |
| **Output** | Report, chart, insight | Pipeline, warehouse, data product |
| **Làm việc với** | Data đã được clean | Raw data, APIs, databases |

**Bạn đã có nền tảng DA** → bước sang DE là học thêm: pipeline design, data modeling, orchestration, infrastructure.

Repo này là **mini DE project** — bạn đang học DE bằng cách xây một hệ thống thật.

---

## Các khái niệm DE cốt lõi có trong repo

### 1. Data Pipeline

**Pipeline** = chuỗi bước biến đổi dữ liệu từ nguồn (source) đến đích (sink).

```
Source (vnstock API)
    → Extract (ingest.py / ingest_market.py)
    → Load (warehouse.py → DuckDB)
    → Transform (signals.py → dicts)
    → Serve (digest.py → Telegram)
```

**Thuộc tính pipeline tốt:**
- **Idempotent**: Chạy lại nhiều lần → kết quả như nhau (có trong repo qua INSERT OR REPLACE).
- **Observable**: Có log để biết chuyện gì đang xảy ra (có `etl_load_log`).
- **Resumable**: Nếu fail, tiếp tục từ chỗ dừng (có `backfill_status`).
- **Testable**: Có unit tests cho từng bước (có trong `tests/`).

### 2. ETL vs. ELT (đã nói trong doc 01 và 03)

**Repo này dùng cả hai:**
- `ingest_market.py → warehouse.py`: Load raw data trước (ELT) → transform sau.
- `ingest.py → signals.py → digest.py`: Transform rồi mới dùng (ETL on the fly).

### 3. Data Modeling

**Data modeling** = thiết kế schema của database. Hai trường phái phổ biến:

**Star Schema (phổ biến trong DW):**
```
         dim_symbols          dim_date
              │                  │
              └──── raw_price_daily ────┘
              (fact table)
```

**Kimball Methodology** (trong repo):
- **Fact table**: Sự kiện theo thời gian → `raw_price_daily` (mỗi dòng = 1 giao dịch 1 mã 1 ngày)
- **Dimension table**: Thực thể mô tả → `dim_symbols` (thông tin về mã cổ phiếu)
- **Naming convention**: `fact_*`, `dim_*`, `raw_*`, `stg_*`, `mart_*`

**Trong repo:**
```
dim_symbols ←── raw_price_daily (fact)
dim_symbols ←── raw_financial_ratio (fact-like)
dim_symbols ←── raw_company_info (slowly changing dimension)
```

### 4. Slowly Changing Dimensions (SCD)

`raw_company_info` là ví dụ về **SCD Type 1** (overwrite):

```python
def upsert_company_info(con, df) -> int:
    # INSERT OR REPLACE → ghi đè giá trị cũ
    # Không giữ lịch sử thay đổi
```

Nếu cần giữ lịch sử (SCD Type 2), schema sẽ cần thêm `valid_from`, `valid_to`, `is_current`:
```sql
-- SCD Type 2 (chưa implement, nhưng đây là pattern cần biết)
CREATE TABLE dim_company_scd2 (
    symbol       VARCHAR,
    company_name VARCHAR,
    industry_icb VARCHAR,
    valid_from   DATE,
    valid_to     DATE,   -- NULL = đang hiệu lực
    is_current   BOOLEAN
);
```

### 5. Partitioning

**Partitioning** = chia bảng theo một tiêu chí để query nhanh hơn.

Repo hiện không implement partitioning (DuckDB tự optimize), nhưng trong production với BigQuery/Snowflake:

```sql
-- Partitioned by trade_date
CREATE TABLE raw_price_daily
PARTITION BY DATE_TRUNC(trade_date, MONTH)
...
```

Lợi ích: Query `WHERE trade_date = '2026-06-07'` chỉ scan partition của tháng 6/2026 thay vì toàn bộ bảng.

### 6. Incremental vs. Full Refresh

**Repo này dùng cả hai:**

```python
# Incremental (build_warehouse.py):
# Mỗi ngày chỉ nạp giá HÔM NAY → không đọc lại lịch sử

# Full refresh (backfill.py):
# Nạp 3 năm lịch sử cho mỗi mã → đọc lại toàn bộ
```

**Rule of thumb:**
- Data thay đổi theo ngày → incremental daily.
- Data hiếm thay đổi (company info) → full refresh monthly.
- Data lịch sử không đổi (giá cũ) → backfill 1 lần.

---

## Các công cụ DE cần học (lộ trình)

### Tier 1 — Bạn đã có kinh nghiệm qua repo này

| Công cụ | Trong repo | Khái niệm đã học |
|---|---|---|
| Python + pandas | `ingest.py`, `signals.py` | DataFrame manipulation, API calls |
| SQL | `warehouse.py` (DuckDB SQL) | INSERT OR REPLACE, window functions |
| DuckDB | `warehouse.py` | OLAP database, column store |
| GitHub Actions | `.github/workflows/` | Scheduled jobs, CI/CD |
| YAML config | `config/*.yml` | Configuration-driven development |
| `python-dotenv` | Mọi nơi | Secrets management, 12-factor app |
| pytest | `tests/` | Unit testing, mocking |

### Tier 2 — Bước tiếp theo (gắn với repo này)

| Công cụ | Mục đích | Cách học qua repo |
|---|---|---|
| **dbt** | Transform raw → mart trong SQL | Phase 3: viết dbt models cho `raw_price_daily` |
| **Pydantic / pandera** | Schema validation | Thêm validation cho ingest output |
| **Airflow / Prefect** | Orchestration thay GitHub Actions | Phase 4: migrate workflows sang Prefect |
| **Docker** | Containerize pipeline | Đóng gói `build_warehouse.py` thành container |

### Tier 3 — Sau khi master Tier 2

| Công cụ | Dùng để |
|---|---|
| **Apache Spark** | Big data processing (>TB scale) |
| **Kafka / Kinesis** | Real-time streaming |
| **dbt Cloud** | Managed dbt, scheduling, docs |
| **Terraform** | Infrastructure as Code |
| **Great Expectations** | Data quality testing |

---

## dbt — Công cụ bạn cần học tiếp theo

**dbt (data build tool)** là công cụ transform data trong warehouse bằng SQL. Viết SQL → dbt compile → chạy trên DuckDB/BigQuery/Snowflake.

**Tại sao quan trọng?**
- Hiện tại, `signals.py` tính MA/RSI trong Python mỗi lần chạy.
- Với dbt, tính 1 lần → lưu vào mart → query nhanh.
- dbt có lineage (biết bảng nào phụ thuộc bảng nào), tests, docs tự động.

**Model dbt ví dụ cho repo này:**

```sql
-- models/staging/stg_price_daily.sql
-- Clean + normalize raw data
SELECT
    symbol,
    CAST(trade_date AS DATE)   AS trade_date,
    close,
    volume,
    value,
    loaded_at
FROM {{ source('warehouse', 'raw_price_daily') }}
WHERE close IS NOT NULL
  AND close > 0
```

```sql
-- models/mart/mart_daily_signals.sql
-- Join price + financial + company, tính MA trong SQL
SELECT
    p.symbol,
    p.trade_date,
    p.close,
    p.volume,
    AVG(p.close) OVER (
        PARTITION BY p.symbol
        ORDER BY p.trade_date
        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
    )                           AS ma20,
    AVG(p.close) OVER (
        PARTITION BY p.symbol
        ORDER BY p.trade_date
        ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
    )                           AS ma50,
    f.pe,
    f.roe,
    c.industry_icb
FROM {{ ref('stg_price_daily') }} p
LEFT JOIN {{ ref('stg_financial_ratio') }} f
    ON p.symbol = f.symbol AND f.period_type = 'year'
    AND f.period = CAST(YEAR(p.trade_date) AS VARCHAR)
LEFT JOIN {{ ref('stg_company_info') }} c
    ON p.symbol = c.symbol
```

**Khi mart_daily_signals có RSI, MA sẵn trong warehouse**, `signals.py` chỉ cần đọc từ mart thay vì tính lại → nhanh hơn, consistent hơn.

---

## Các Pattern DE cần ghi nhớ

### Pattern 1: Configuration-Driven Development

```yaml
# config/screener.yml
value:
  pe_max: 15
  pb_max: 2.5
```

```python
# src/screener.py
cfg = load_yaml("screener.yml")
if pe <= cfg["pe_max"]:  # không hard-code 15
    hits += 1
```

**Lý do**: Thay đổi logic không cần sửa code → không cần deploy lại.

### Pattern 2: Fail Fast + Graceful Degradation

```python
# ingest.py: Fail fast trên missing env var
api_key = os.environ["ANTHROPIC_API_KEY"]  # raise KeyError ngay nếu thiếu

# Nhưng graceful trên dữ liệu:
try:
    df = Finance(symbol).ratio()
except Exception as e:
    print(f"[ratios] {symbol}: {e}")
    return {}  # trả về dict rỗng, job tiếp tục
```

**Quy tắc**:
- Infrastructure/config thiếu → fail ngay (không tiếp tục vô nghĩa).
- Data của 1 mã lỗi → log + skip, tiếp tục với mã khác.

### Pattern 3: Separation of Concerns

```
ingest.py    → chỉ biết cách lấy data
signals.py   → chỉ biết cách tính toán
storage.py   → chỉ biết cách lưu
notify.py    → chỉ biết cách gửi
main.py      → orchestrate, không biết detail
```

**Test benefit**: Có thể test từng module mà không cần toàn bộ hệ thống.

### Pattern 4: Schema-first Design

Trong `warehouse.py`, schema được định nghĩa rõ ràng với type:
```sql
CREATE TABLE raw_price_daily (
    symbol     VARCHAR,
    trade_date DATE,      -- không phải TEXT, phải là DATE để sort/filter đúng
    close      DOUBLE,    -- không phải TEXT
    volume     BIGINT,    -- cần BIGINT vì khối lượng có thể > INT_MAX
    ...
);
```

**Lý do dùng đúng type**:
- `DATE` → `WHERE trade_date >= '2024-01-01'` hoạt động đúng.
- `TEXT` → so sánh string, có thể sai kết quả.
- `BIGINT` → volume triệu cổ × 1000 = hàng tỷ, INT bị overflow.

### Pattern 5: Observability — Ba trụ cột

| Trụ cột | Trong repo | Còn thiếu |
|---|---|---|
| **Logs** | `print()` statements, `etl_load_log` | Structured logging (JSON logs) |
| **Metrics** | `rows_loaded` trong log table | Alerting khi rows=0 liên tiếp |
| **Traces** | Chưa có | Distributed tracing nếu scale lên |

**Cải thiện logging** (bạn có thể làm):
```python
import logging
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Thay vì:
print(f"raw_price_daily: {n_px} dòng")

# Dùng:
logger.info(json.dumps({"event": "upsert_prices", "rows": n_px, "date": run_date}))
```

---

## Lộ trình học DE từ repo này

### Giai đoạn 1 — Đang ở đây: Hiểu code hiện tại
- Đọc hết 6 doc trước + doc này.
- Tự tay chạy `python build_warehouse.py --mode daily` với DuckDB local.
- Đọc từng test file, hiểu tại sao mock như vậy.

### Giai đoạn 2 — Extend warehouse
- Cài dbt: `pip install dbt-duckdb`.
- Viết `models/staging/stg_price_daily.sql`.
- Thêm dbt test: `not_null`, `unique` cho (symbol, trade_date).

### Giai đoạn 3 — Improve pipeline
- Thêm data quality checks vào `build_warehouse.py` (cảnh báo nếu rows_loaded = 0).
- Migrate `storage.py` (SQLite) sang DuckDB/MotherDuck (xóa SQLite dependency).
- Thêm Slack/Telegram alert khi workflow GitHub Actions fail.

### Giai đoạn 4 — Orchestration
- Học Prefect Cloud (free tier).
- Migrate GitHub Actions → Prefect flows với retry, alerting.
- Hoặc học Apache Airflow trên local.

### Giai đoạn 5 — Scale out (tương lai xa)
- Thay DuckDB → BigQuery nếu data > 10GB.
- Thêm streaming với Kafka nếu cần real-time.
- Deploy dashboard (Streamlit → Metabase → Looker).

---

## Câu hỏi tự kiểm tra

Sau khi đọc hết tài liệu, bạn nên trả lời được:

1. Tại sao không dùng PostgreSQL thay vì DuckDB?
2. Tại sao `fetch_history` trong `ingest.py` đọc warehouse trước thay vì gọi API?
3. `INSERT OR REPLACE` và `INSERT OR IGNORE` khác nhau như thế nào?
4. Tại sao `_throttle()` không thread-safe khi parallelize?
5. Nếu `raw_financial_ratio` cần thêm cột `revenue`, bạn cần sửa những file nào?
6. Cron `0 9 1 * *` chạy khi nào? Tại sao không dùng `0 9 */30 * *`?
7. Tại sao `signals.py` không có test cần mock?
8. SQLite trong `storage.py` bị mất sau mỗi GitHub Actions run — đây có phải bug không? Fix như thế nào?
