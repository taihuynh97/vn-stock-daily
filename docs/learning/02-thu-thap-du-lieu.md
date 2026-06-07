# 02 — Thu thập dữ liệu (Data Ingestion)

## Files liên quan
- `src/ingest.py` — gọi API cho job bản tin
- `src/ingest_market.py` — gọi API bulk cho job warehouse
- `backfill.py` — nạp lịch sử 3 năm (one-time)

---

## vnstock là gì?

`vnstock` là Python library gói lại các API dữ liệu thị trường chứng khoán Việt Nam. Thay vì bạn phải tự gọi HTTPS tới VCI, TCBS, SSI, thư viện làm việc đó giúp.

```python
from vnstock.api.quote import Quote
from vnstock.api.financial import Finance
from vnstock.api.company import Company
from vnstock.api.listing import Listing
from vnstock.api.trading import Trading
```

**Các API chính dùng trong repo:**

| Class | Method | Trả về | Dùng để |
|---|---|---|---|
| `Quote` | `.history(start, end, interval)` | DataFrame OHLCV | Lịch sử giá từng mã |
| `Finance` | `.ratio()` | DataFrame tỷ số tài chính | P/E, P/B, ROE, EPS |
| `Company` | `.overview()` | DataFrame 1 dòng | Tên công ty, sàn, ngành |
| `Company` | `.news()` | DataFrame tin tức | Tin gần nhất |
| `Listing` | `.all_symbols()` | DataFrame danh sách | Tất cả mã niêm yết |
| `Listing` | `.symbols_by_group()` | DataFrame/Series | Mã theo nhóm VN30, VN100 |
| `Trading` | `.price_board(symbols_list)` | DataFrame giá hiện tại | Giá EOD nhiều mã 1 lần |

**Tầng Community (miễn phí):** 60 requests/phút. Nếu không có API key: 20 req/phút.

---

## Rate Limiting là gì và tại sao phải quan tâm?

**Rate limit** = giới hạn số lần gọi API trong 1 khoảng thời gian. Server dùng để tránh bị quá tải.

Nếu bạn gọi quá nhanh → nhận HTTP 429 (Too Many Requests) → dữ liệu bị thiếu.

### Cách xử lý trong repo

```python
# src/ingest.py
_last_call_time: float = 0.0
_MIN_CALL_INTERVAL = 3.1  # giây

def _throttle() -> None:
    global _last_call_time
    wait = _MIN_CALL_INTERVAL - (time.monotonic() - _last_call_time)
    if wait > 0:
        time.sleep(wait)
    _last_call_time = time.monotonic()
```

**Cơ chế**: Mỗi lần gọi API, kiểm tra thời gian kể từ lần gọi trước. Nếu chưa đủ 3.1s → sleep phần còn lại.

**Tại sao 3.1s thay vì 1s (60 req/min)?**
- 60 req/min = 1 req/giây về mặt lý thuyết.
- Nhưng các server thường dùng **sliding window** (cửa sổ trượt) hoặc **burst limit** — 3.1s là an toàn cho cả account không có key (20 req/min = 3s/req).

### Tính toán: Bao lâu để chạy xong?

```
Bản tin: ~10 mã portfolio + 30 mã VN30 screener = ~40 lần gọi
40 × 3.1s ≈ 2 phút → hoàn toàn chấp nhận được

Backfill 1,500 mã:
1,500 × 3.1s ≈ 4,650s ≈ 77 phút mỗi batch
```

Đây là lý do backfill phải chạy theo batch (200 mã/lần) và resumable.

### So sánh các chiến lược rate limiting

| Chiến lược | Cách làm | Ưu/nhược |
|---|---|---|
| **Sleep cố định** (repo dùng) | `time.sleep(3.1)` sau mỗi call | Đơn giản, an toàn, không tận dụng tốc độ tối đa |
| **Token bucket** | Dùng `limits` hoặc `ratelimit` library | Burst-friendly, phức tạp hơn |
| **Exponential backoff** | Sleep tăng dần khi bị 429 | Tốt cho retry sau lỗi |
| **Async + semaphore** | asyncio + giới hạn số task song song | Nhanh nhất, khó debug |

---

## Soft Column Mapping — Vấn đề thực tế với API

Cột mà API trả về **thay đổi tùy nguồn và tùy phiên bản**. Ví dụ:

```python
# VCI có thể trả:
["symbol", "match_price", "accumulated_volume", ...]

# Nguồn khác có thể trả:
["ticker", "last_price", "nmtotaltradedqty", ...]
```

Nếu code `df["match_price"]` cứng, khi nguồn đổi tên → vỡ pipeline.

### Giải pháp: `_find()` helper

```python
# src/ingest_market.py
def _find(cols, *keys):
    for c in cols:
        if any(k in c for k in keys):
            return c
    return None

# Sử dụng:
close = _find(cols, "match_price", "matchprice", "last_price", "close", "price")
```

**Cách hoạt động**: Duyệt danh sách tên cột, kiểm tra xem cột nào *chứa* bất kỳ key nào. Trả về cột đầu tiên match.

**In ra lần đầu để debug:**
```python
_printed_cols = False

if not _printed_cols:
    print(f"cột thật: {list(df.columns)}")
    _printed_cols = True
```

Khi API đổi cột, log này cho bạn biết ngay cột thực là gì, từ đó cập nhật `_find()`.

### So sánh với cách khác

| Cách | Ví dụ | Phù hợp khi |
|---|---|---|
| **Hard-code tên cột** | `df["match_price"]` | API bạn tự kiểm soát, không đổi |
| **Soft mapping** (repo dùng) | `_find(cols, "match_price", ...)` | API bên thứ 3 hay đổi |
| **Schema validation** | `pydantic`, `pandera` | Cần strict validation, production-grade |
| **Column alias config** | Đặt trong YAML | Nhiều nguồn, cần thay đổi không cần deploy |

---

## MultiIndex Columns — Bẫy phổ biến với pandas

`Finance.ratio()` đôi khi trả về DataFrame có **MultiIndex columns** (cột lồng nhau):

```python
# Thay vì:
["yearreport", "pe", "pb", "roe"]

# Có thể là:
[("yearreport", ""), ("financialRatio", "pe"), ("financialRatio", "pb")]
```

**Cách xử lý:**
```python
df.columns = [
    '.'.join(map(str, c)).lower() if isinstance(c, tuple) else str(c).lower()
    for c in df.columns
]
```

Sau bước này: `("financialRatio", "pe")` → `"financialratio.pe"` → `_find` tìm được với key `"pe"`.

---

## Backfill — Nạp dữ liệu lịch sử

**Vấn đề**: Warehouse mới tạo ra chỉ có giá hôm nay. Cần 3 năm lịch sử để tính MA50, backtest.

**Thiết kế backfill** (`backfill.py`):

### Checkpoint table

```sql
CREATE TABLE backfill_status (
    symbol     VARCHAR PRIMARY KEY,
    status     VARCHAR DEFAULT 'pending',  -- pending / done / error
    last_date  DATE,
    notes      VARCHAR,
    updated_at TIMESTAMP
);
```

**Tại sao cần checkpoint?**
- 1,500 mã × 3.1s = 77 phút mỗi batch.
- Nếu script crash ở mã thứ 500 → không cần bắt đầu lại từ đầu.
- Chạy lại → `get_pending_symbols()` chỉ trả mã chưa có `status='done'`.

**Resumable pattern:**
```python
pending = warehouse.get_pending_symbols(con)
for sym in pending[:limit]:
    df = fetch_history_one(sym, start, end)
    if df.empty:
        mark_backfill_error(sym, "empty")  # skip, không retry
    else:
        upsert_prices(con, df)
        mark_backfill_done(sym, df["trade_date"].max())
```

### Kết quả thực tế

Sau 9 batch (200 mã/batch):
- **1,180,578 dòng** trong `raw_price_daily`
- 1,561 mã thành công
- 33 mã `no_data_vci` — không có dữ liệu trên nguồn VCI (niêm yết quá mới, mã bị hủy...)

### So sánh với các chiến lược backfill khác

| Chiến lược | Cách làm | Phù hợp |
|---|---|---|
| **Sequential with checkpoint** (repo dùng) | Lần lượt, lưu trạng thái | Simple, dễ debug, đủ cho 1,500 mã |
| **Parallel async** | asyncio / ThreadPoolExecutor | Nhanh hơn 4-10x, khó debug rate limit |
| **Bulk API** (nếu có) | 1 call cho nhiều mã | Lý tưởng nhất, phụ thuộc vào provider |
| **Incremental daily** | Chỉ nạp ngày hôm qua mỗi ngày | Không backfill được quá khứ |

---

## Warehouse-first Pattern (Phase 2B)

Kể từ Phase 2B, `fetch_history` đọc warehouse trước:

```python
def fetch_history(symbol, source="VCI", days=120):
    # 1) Thử warehouse trước
    try:
        con = warehouse.get_conn()
        df = warehouse.read_price_history(con, symbol, days)
        con.close()
        if len(df) >= max(days // 2, 10):  # có đủ data thì dùng
            return df
    except Exception:
        pass  # warehouse không có → fallback

    # 2) Gọi API nếu warehouse thiếu
    _throttle()
    df = Quote(symbol=symbol, source=source).history(...)
    ...
```

**Tại sao threshold `max(days//2, 10)`?**
- Ngưỡng `days//2`: nếu cần 120 phiên mà warehouse chỉ có 30 → vẫn nên gọi API.
- Ngưỡng `10`: tránh trường hợp warehouse có rất ít dòng nhưng vẫn "có data".
- `max(...)`: lấy cái lớn hơn để đảm bảo đủ cả hai điều kiện.

**Tốc độ cải thiện**:
- Trước: 10 mã portfolio × 3.1s = ~31 giây chỉ cho fetch_history.
- Sau: đọc DuckDB local/MotherDuck ≈ <100ms/mã → ~1 giây tổng.

---

## Module-level Singleton — Tại sao `_last_call_time` là global?

```python
# src/ingest.py
_last_call_time: float = 0.0   # ← biến ở cấp module, ngoài mọi function

def _throttle() -> None:
    global _last_call_time     # ← khai báo dùng biến module-level
    wait = _MIN_CALL_INTERVAL - (time.monotonic() - _last_call_time)
    if wait > 0:
        time.sleep(wait)
    _last_call_time = time.monotonic()
```

**Module là singleton trong Python.** Khi Python `import src.ingest`, module được load một lần và tồn tại trong bộ nhớ suốt vòng đời process. Biến `_last_call_time` là một giá trị duy nhất, chia sẻ cho mọi lần gọi `_throttle()`.

**Hệ quả thực tế**: Dù `main.py` và `build_warehouse.py` đều import `ingest`, chúng **chia sẻ cùng một timer**. Nếu `ingest_market.py` gọi `ingest._throttle()` vừa xong, `main.py` gọi ngay sau sẽ phải đợi đủ 3.1s — dùng chung ngân sách rate limit.

**Đây là lý do `ingest_market.py` import `ingest`:**

```python
# src/ingest_market.py
from . import ingest  # tái dùng _throttle — chung ngân sách rate limit

def fetch_eod_prices(...):
    ingest._throttle()   # dùng timer của ingest.py, không tự tạo timer mới
```

Nếu `ingest_market.py` tự tạo timer riêng, hai module có thể gọi API gần như đồng thời → vượt rate limit.

**Vấn đề với singleton khi multi-threading:**

```python
# Nếu dùng ThreadPoolExecutor:
with ThreadPoolExecutor(max_workers=4) as executor:
    executor.map(fetch_history, symbols)
```

4 thread cùng đọc/ghi `_last_call_time` mà không có lock → **race condition**: thread A đọc `_last_call_time`, thread B cũng đọc cùng lúc, cả hai nghĩ đã đủ 3.1s → cùng gọi API → vượt rate limit.

Repo này **không parallelize** vì lý do đó. Đây là trade-off có chủ ý: đơn giản + an toàn, chấp nhận chậm hơn.
