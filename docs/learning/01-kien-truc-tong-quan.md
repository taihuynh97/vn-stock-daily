# 01 — Kiến trúc tổng quan

## Hệ thống này làm gì?

Hai luồng hoạt động song song, hoàn toàn độc lập:

```
┌─────────────────────────────────────────────────────────────┐
│  LUỒNG 1 — BẢN TIN (main.py)              chạy T2-T6 15:30 │
│                                                              │
│  vnstock API ──► signals.py ──► screener.py ──► digest.py  │
│                                                  (Claude)    │
│                                             ──► notify.py   │
│                                                  (Telegram)  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  LUỒNG 2 — WAREHOUSE (build_warehouse.py)  chạy hằng ngày  │
│                                                              │
│  vnstock API ──► ingest_market.py ──► warehouse.py         │
│                                       (DuckDB/MotherDuck)   │
│                                                              │
│  Daily:   giá EOD + danh sách mã                            │
│  Weekly:  + tỷ số tài chính (P/E, ROE...)                   │
│  Monthly: + thông tin công ty                               │
└─────────────────────────────────────────────────────────────┘
```

**Tại sao tách hai luồng?**
- Luồng bản tin cần nhanh (~2-3 phút) để gửi kịp sau phiên.
- Warehouse nạp toàn thị trường (~1,500 mã), chạy riêng không ảnh hưởng bản tin.
- Kể từ Phase 2B: luồng bản tin **ưu tiên đọc từ warehouse** (nhanh hơn nhiều) thay vì gọi API lại.

---

## Ba lớp kiến trúc

### Lớp 1 — Data Ingestion (Thu thập)
**Files:** `src/ingest.py`, `src/ingest_market.py`

Nhiệm vụ: gọi API → parse dữ liệu thô → chuẩn hoá cột → trả DataFrame.

Không lưu trữ gì. Không biết warehouse hay SQLite là gì.

### Lớp 2 — Storage (Lưu trữ)
**Files:** `src/warehouse.py`, `src/storage.py`

- `warehouse.py` → DuckDB (OHLCV lịch sử, tỷ số tài chính, thông tin công ty)
- `storage.py` → SQLite (snapshot danh mục, log bản tin, seen_news)

Không biết gì về vnstock hay Claude.

### Lớp 3 — Application Logic (Xử lý & Output)
**Files:** `src/signals.py`, `src/screener.py`, `src/digest.py`, `src/notify.py`

Đọc dữ liệu → tính toán → tạo output. Không gọi API (signals, screener là pure functions).

---

## Data Flow chi tiết — Luồng bản tin

```
main.py
  │
  ├─ ingest.fetch_index("VNINDEX")     → dict {close, change_pct, change_5d_pct}
  │     │
  │     └─ warehouse ──► API (fallback)
  │
  ├─ for each symbol in portfolio.yml:
  │     ingest.fetch_history(sym, days=120)  → DataFrame [trade_date, open, high, low, close, volume]
  │     │     └─ warehouse ──► API (fallback)
  │     │
  │     signals.analyze(df)            → dict {rsi, ma20, ma50, change_pct, vol_ratio, return_1m}
  │     ingest.fetch_ratios(sym)       → dict {pe, pb, roe}
  │     ingest.fetch_industry(sym)     → str "Bất động sản"
  │     ingest.fetch_news(sym, limit=3)→ list[dict]
  │
  ├─ screener.run(cfg, source, run_date, exclude=held)
  │     └─ ingest.fetch_universe("VN30") → list[str]
  │        for each sym: fetch_history + analyze + fetch_ratios
  │        filter: value(PE,PB,ROE) AND momentum(MA50,RSI,return_1m)
  │
  ├─ storage.filter_new_news(all_news) → deduplicate
  │
  ├─ digest.build(...)                 → str (Claude API)
  │
  └─ notify.send(content)             → Telegram
```

---

## Tại sao có hai file ingest?

| | `ingest.py` | `ingest_market.py` |
|---|---|---|
| Dùng cho | Luồng bản tin (`main.py`) | Luồng warehouse (`build_warehouse.py`) |
| Gọi API | Per-symbol | Bulk (price_board cho nhiều mã 1 lần) |
| Output | Thông tin cho 1 mã | DataFrame nhiều mã |
| Rate limit | `_throttle()` (3.1s) | Dùng chung `ingest._throttle()` |

Thiết kế này có trade-off:
- **Ưu điểm**: mỗi file có trách nhiệm rõ ràng, dễ test độc lập.
- **Nhược điểm**: duplicate một số logic (ví dụ `_find`, `_col` helper).

---

## So sánh kiến trúc: Single Job vs. Multi-Job

**Cách đơn giản nhất** (không dùng ở đây): 1 script làm tất cả — nạp data, tính signals, gửi bản tin.

```python
# Đơn giản nhưng có vấn đề
def run():
    for sym in all_symbols:
        data = fetch(sym)
        store(data)
        signals = analyze(data)
        send(signals)
```

**Vấn đề**: Nếu bước store chậm (1,500 mã × 3.1s = 77 phút), bản tin gửi trễ rất nhiều.

**Cách này dùng** (Multi-Job architecture):
```
Job 1 (Warehouse): nạp TOÀN BỘ thị trường mỗi ngày → lưu vào DuckDB
Job 2 (Newsletter): đọc từ warehouse (< 1 giây) → tính signals → gửi bản tin
```

**Kết quả**: Job bản tin chạy nhanh hơn nhiều vì không cần gọi API lại cho từng mã.

---

## Khái niệm nền tảng: ETL vs. ELT

Hai mô hình phổ biến trong data engineering:

**ETL (Extract → Transform → Load)**
```
API → [transform ngay] → Database
```
Data được làm sạch trước khi lưu. Database chỉ chứa data đã chuẩn.

**ELT (Extract → Load → Transform)**
```
API → Database (raw) → [transform sau]
```
Lưu data thô trước, transform sau bằng SQL (thường dùng dbt).

**Repo này dùng cả hai**:
- `raw_price_daily`, `raw_financial_ratio`, `raw_company_info` → ELT: lưu raw trước
- `signals.py` tính MA/RSI từ data đã load → transform ở application layer
- Phase 3 (chưa làm) sẽ dùng dbt để transform raw → staging → mart trong DuckDB

---

## Khái niệm nền tảng: Idempotency (Tính lũy đẳng)

Một yêu cầu quan trọng với pipeline tự động: **chạy lại nhiều lần cho kết quả như nhau**.

Ví dụ: nếu job thứ Tư fail và chạy lại thứ Năm, kết quả phải đúng.

```sql
-- Không idempotent (chạy lại → thêm dòng trùng)
INSERT INTO raw_price_daily VALUES ...

-- Idempotent (chạy lại → replace dòng cũ)
INSERT OR REPLACE INTO raw_price_daily VALUES ...
```

Repo này dùng `INSERT OR REPLACE` (DuckDB) và `INSERT OR REPLACE` (SQLite) ở khắp nơi — đây là lý do.

---

## SQLite WAL mode — Dòng code ẩn quan trọng trong `storage.py`

```python
# src/storage.py
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")   # ← dòng này làm gì?
    return conn
```

**WAL = Write-Ahead Log** (nhật ký ghi trước). Đây là cơ chế journal của SQLite, ảnh hưởng đến cách database xử lý concurrent access và crash recovery.

**Mặc định của SQLite (DELETE mode):**
```
Writer muốn ghi → lock toàn bộ file → Reader bị block
```

**WAL mode:**
```
Writer ghi vào file WAL riêng → Reader đọc main file KHÔNG bị block
Checkpoint định kỳ → merge WAL vào main file
```

**Lợi ích thực tế với repo này:**
- `storage.py` được gọi nhiều lần trong một job (`save_portfolio`, `save_screener`, `filter_new_news`, `save_digest`).
- WAL cho phép đọc và ghi đồng thời an toàn hơn, giảm nguy cơ "database is locked" error khi nhiều operation xảy ra gần nhau.

**Crash recovery:** Nếu process bị kill giữa chừng khi đang ghi, WAL đảm bảo transaction chưa commit không bao giờ được apply — database luôn ở trạng thái consistent.

**Là một PRAGMA trong SQLite:**
`PRAGMA` là lệnh cấu hình SQLite, không phải SQL chuẩn. `journal_mode=WAL` chỉ cần set một lần per connection là có hiệu lực. Trong production code, luôn set WAL ngay khi mở connection.

---

## argparse — Biến Python script thành CLI tool

`build_warehouse.py` dùng `argparse` để nhận tham số từ command line:

```python
# build_warehouse.py
import argparse

def main():
    parser = argparse.ArgumentParser(description="Warehouse ingestion job")
    parser.add_argument(
        "--mode",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="daily=giá EOD+universe; weekly=+financials; monthly=+company_info",
    )
    args = parser.parse_args()
    # args.mode = "daily" / "weekly" / "monthly"
```

**Cơ chế hoạt động:**

`parser.parse_args()` đọc `sys.argv` (list các argument từ terminal):
- `python build_warehouse.py` → `sys.argv = ['build_warehouse.py']` → `args.mode = "daily"` (default)
- `python build_warehouse.py --mode weekly` → `sys.argv = ['build_warehouse.py', '--mode', 'weekly']` → `args.mode = "weekly"`

**`choices=["daily", "weekly", "monthly"]`**: argparse tự validate — nếu truyền `--mode invalid`, in thông báo lỗi và exit ngay.

**`--help` miễn phí:**
```bash
python build_warehouse.py --help
# usage: build_warehouse.py [-h] [--mode {daily,weekly,monthly}]
# Warehouse ingestion job
# options:
#   --mode {daily,weekly,monthly}
#                     daily=giá EOD+universe; weekly=+financials; ...
```

**Tại sao không dùng environment variable?**
`WAREHOUSE_DB`, `motherduck_token` là credentials → phù hợp với env var (bí mật, inject bởi CI/CD).
`--mode` là runtime behavior → phù hợp với argument (thay đổi theo mục đích chạy, không bí mật).

**argparse là DE skill cơ bản** vì mọi pipeline script đều cần nhận tham số: `--date`, `--env prod/staging`, `--dry-run`, `--backfill-from 2024-01-01`...

---

## Công cụ và lý do chọn

| Công cụ | Thay thế | Lý do chọn |
|---|---|---|
| **DuckDB** | PostgreSQL, BigQuery | Nhúng vào Python, không cần server, query OLAP cực nhanh |
| **MotherDuck** | AWS RDS, Supabase | DuckDB trên cloud, free tier đủ cho project nhỏ |
| **SQLite** | PostgreSQL | Cho log/seen_news — không cần query phức tạp, file-based |
| **vnstock** | TCBS API, SSI API trực tiếp | Python wrapper thống nhất cho nhiều nguồn TTCK VN |
| **GitHub Actions** | Airflow, Prefect, cron server | Free, không cần infra, đủ cho daily job |
| **Claude API** | GPT-4, Gemini | Tích hợp tự nhiên với Claude Code workflow |
| **Telegram Bot** | Email, Slack | Mobile-first, miễn phí, API đơn giản |
