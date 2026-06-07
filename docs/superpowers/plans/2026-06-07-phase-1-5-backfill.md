# Phase 1.5 — Backfill Lịch Sử Giá Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nạp lịch sử OHLCV 3 năm (~1.2M dòng) cho toàn bộ mã trong `dim_symbols` vào `raw_price_daily`, resumable — chạy lại an toàn, không nạp lại mã đã xong.

**Architecture:** Thêm bảng `backfill_status` làm checkpoint (pending/done/error per symbol). `backfill.py` đọc danh sách pending, gọi `fetch_history_one()` per symbol, upsert vào `raw_price_daily`, đánh dấu done. Tham số `--limit` chia nhỏ số mã mỗi lần chạy để không bị timeout.

**Tech Stack:** Python 3.12, DuckDB 1.5, vnstock 4.x (`Quote.history`), argparse, pytest

**Free tier impact:**
- vnstock Community (60 req/phút, throttle 3.1s/call): ~19 calls/phút → 1594 mã ≈ 82 phút. Hoàn toàn free.
- MotherDuck: ~1.2M dòng × DuckDB compression ≈ 15–20MB. Xa giới hạn 10GB.
- GitHub Actions: backfill chạy **local một lần duy nhất**, không dùng Actions minutes.

---

## File Structure

| File | Thay đổi |
|---|---|
| `src/warehouse.py` | Thêm 4 hàm backfill_status (init, get_pending, mark_done, mark_error) |
| `src/ingest_market.py` | Thêm `fetch_history_one(symbol, start, end)` |
| `backfill.py` | Tạo mới — entry point với `--years`, `--limit` |
| `tests/test_warehouse_backfill.py` | Tạo mới — test backfill_status CRUD |
| `tests/test_ingest_history.py` | Tạo mới — test fetch_history_one với mock |

**Ràng buộc:** KHÔNG sửa `main.py`, `ingest.py`, `signals.py`, `screener.py`, `digest.py`, `notify.py`, `storage.py`.

---

## Task 1: Thêm backfill_status vào warehouse.py

**Files:**
- Modify: `src/warehouse.py` (cuối file, sau hàm `log_load`)
- Test: `tests/test_warehouse_backfill.py`

- [ ] **Step 1: Tạo file test**

```python
# tests/test_warehouse_backfill.py
import duckdb
import pytest
from src import warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    warehouse.init_backfill_status(c)
    return c


def test_init_creates_table(con):
    rows = con.execute("SELECT count(*) FROM backfill_status").fetchone()[0]
    assert rows == 0


def test_get_pending_returns_symbols_not_done(con):
    con.execute("INSERT INTO dim_symbols VALUES ('AAA','HOSE','Test',TRUE,'2020-01-01','2026-01-01')")
    con.execute("INSERT INTO dim_symbols VALUES ('BBB','HNX','Test2',TRUE,'2020-01-01','2026-01-01')")
    con.execute("INSERT INTO backfill_status VALUES ('BBB','done','2026-06-01',now())")
    pending = warehouse.get_pending_symbols(con)
    assert pending == ['AAA']


def test_mark_done_updates_status(con):
    con.execute("INSERT INTO dim_symbols VALUES ('VNM','HOSE','Vinamilk',TRUE,'2020-01-01','2026-01-01')")
    warehouse.mark_backfill_done(con, 'VNM', '2026-06-07')
    row = con.execute("SELECT status, last_date FROM backfill_status WHERE symbol='VNM'").fetchone()
    assert row[0] == 'done'
    assert str(row[1]) == '2026-06-07'


def test_mark_error_sets_error_status(con):
    con.execute("INSERT INTO dim_symbols VALUES ('XYZ','HOSE','XYZ Co',TRUE,'2020-01-01','2026-01-01')")
    warehouse.mark_backfill_error(con, 'XYZ', 'timeout')
    row = con.execute("SELECT status, notes FROM backfill_status WHERE symbol='XYZ'").fetchone()
    assert row[0] == 'error'
    assert row[1] == 'timeout'


def test_mark_done_idempotent(con):
    con.execute("INSERT INTO dim_symbols VALUES ('FPT','HOSE','FPT',TRUE,'2020-01-01','2026-01-01')")
    warehouse.mark_backfill_done(con, 'FPT', '2026-06-06')
    warehouse.mark_backfill_done(con, 'FPT', '2026-06-07')
    count = con.execute("SELECT count(*) FROM backfill_status WHERE symbol='FPT'").fetchone()[0]
    assert count == 1
```

- [ ] **Step 2: Chạy test để confirm fail**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
source .venv/bin/activate
python -m pytest tests/test_warehouse_backfill.py -v
```

Expected: FAIL với `AttributeError: module 'src.warehouse' has no attribute 'init_backfill_status'`

- [ ] **Step 3: Thêm 4 hàm vào src/warehouse.py**

Thêm vào cuối file, sau hàm `log_load`:

```python
def init_backfill_status(con):
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS backfill_status (
            symbol     VARCHAR PRIMARY KEY,
            status     VARCHAR DEFAULT 'pending',
            last_date  DATE,
            notes      VARCHAR,
            updated_at TIMESTAMP
        );
        """
    )


def get_pending_symbols(con) -> list[str]:
    """Trả danh sách mã chưa backfill xong (không có trong backfill_status hoặc status != done)."""
    return [r[0] for r in con.execute(
        """
        SELECT d.symbol
        FROM dim_symbols d
        LEFT JOIN backfill_status b ON d.symbol = b.symbol
        WHERE d.is_active AND (b.symbol IS NULL OR b.status != 'done')
        ORDER BY d.symbol
        """
    ).fetchall()]


def mark_backfill_done(con, symbol: str, last_date: str):
    con.execute(
        """
        INSERT INTO backfill_status (symbol, status, last_date, updated_at)
        VALUES (?, 'done', ?, now())
        ON CONFLICT (symbol) DO UPDATE SET
            status     = 'done',
            last_date  = excluded.last_date,
            updated_at = excluded.updated_at
        """,
        [symbol, last_date],
    )


def mark_backfill_error(con, symbol: str, note: str):
    con.execute(
        """
        INSERT INTO backfill_status (symbol, status, notes, updated_at)
        VALUES (?, 'error', ?, now())
        ON CONFLICT (symbol) DO UPDATE SET
            status     = 'error',
            notes      = excluded.notes,
            updated_at = excluded.updated_at
        """,
        [symbol, note],
    )
```

- [ ] **Step 4: Chạy test để confirm pass**

```bash
python -m pytest tests/test_warehouse_backfill.py -v
```

Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/warehouse.py tests/test_warehouse_backfill.py
git commit -m "feat: add backfill_status table and CRUD to warehouse"
```

---

## Task 2: Thêm fetch_history_one vào ingest_market.py

**Files:**
- Modify: `src/ingest_market.py` (thêm hàm mới + biến `_printed_hist_cols`)
- Test: `tests/test_ingest_history.py`

- [ ] **Step 1: Tạo file test**

```python
# tests/test_ingest_history.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from src import ingest_market


def _make_history_df():
    """DataFrame giả lập Quote.history trả về (cột phổ biến của vnstock 4.x)."""
    return pd.DataFrame({
        'time':   ['2024-01-02', '2024-01-03', '2024-01-04'],
        'open':   [50000.0,  51000.0,  49000.0],
        'high':   [52000.0,  53000.0,  51000.0],
        'low':    [49000.0,  50000.0,  48000.0],
        'close':  [51000.0,  49500.0,  50000.0],
        'volume': [100000,   120000,   90000],
        'value':  [5.1e9,    5.94e9,   4.5e9],
    })


def test_fetch_history_one_returns_correct_schema():
    mock_quote = MagicMock()
    mock_quote.history.return_value = _make_history_df()

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        df = ingest_market.fetch_history_one('VNM', '2024-01-01', '2024-01-31')

    assert list(df.columns) == ['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'value']
    assert len(df) == 3
    assert (df['symbol'] == 'VNM').all()


def test_fetch_history_one_drops_rows_without_close():
    df_raw = _make_history_df()
    df_raw.loc[1, 'close'] = None
    mock_quote = MagicMock()
    mock_quote.history.return_value = df_raw

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        df = ingest_market.fetch_history_one('AAA', '2024-01-01', '2024-01-31')

    assert len(df) == 2


def test_fetch_history_one_returns_empty_on_exception():
    mock_quote = MagicMock()
    mock_quote.history.side_effect = Exception("API error")

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        df = ingest_market.fetch_history_one('ERR', '2024-01-01', '2024-01-31')

    assert df.empty
```

- [ ] **Step 2: Chạy test để confirm fail**

```bash
python -m pytest tests/test_ingest_history.py -v
```

Expected: FAIL với `AttributeError: module 'src.ingest_market' has no attribute 'fetch_history_one'`

- [ ] **Step 3: Thêm fetch_history_one vào src/ingest_market.py**

Thêm biến module và hàm mới vào cuối file (sau `_col`):

```python
_printed_hist_cols = False


def fetch_history_one(symbol: str, start: str, end: str, source: str = "VCI") -> pd.DataFrame:
    """Lịch sử OHLCV một mã qua Quote.history. Trả DataFrame schema raw_price_daily.
    In tên cột thật lần đầu để dễ debug nếu cần chỉnh mapping."""
    global _printed_hist_cols
    ingest._throttle()
    try:
        df = Quote(symbol=symbol, source=source).history(start=start, end=end, interval="1D")
    except Exception as e:
        print(f"[history] {symbol}: {e}")
        return pd.DataFrame()

    if df is None or len(df) == 0:
        return pd.DataFrame()

    df.columns = [str(c).lower() for c in df.columns]
    if not _printed_hist_cols:
        print(f"[history] cột thật ({symbol}): {list(df.columns)}")
        _printed_hist_cols = True

    cols = list(df.columns)
    date_col = _find(cols, "time", "date", "trading_date")
    close_col = _find(cols, "close")
    open_col  = _find(cols, "open")
    high_col  = _find(cols, "high")
    low_col   = _find(cols, "low")
    vol_col   = _find(cols, "volume")
    val_col   = _find(cols, "value")

    if date_col is None or close_col is None:
        print(f"[history] {symbol}: thiếu cột date/close. Cột có: {cols}")
        return pd.DataFrame()

    out = pd.DataFrame({
        "symbol":     symbol,
        "trade_date": pd.to_datetime(df[date_col]).dt.date,
        "open":       _col(df, open_col),
        "high":       _col(df, high_col),
        "low":        _col(df, low_col),
        "close":      pd.to_numeric(df[close_col], errors="coerce"),
        "volume":     pd.to_numeric(df[vol_col], errors="coerce") if vol_col else None,
        "value":      _col(df, val_col),
    })
    return out.dropna(subset=["close"]).drop_duplicates(["symbol", "trade_date"]).reset_index(drop=True)
```

- [ ] **Step 4: Chạy test để confirm pass**

```bash
python -m pytest tests/test_ingest_history.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingest_market.py tests/test_ingest_history.py
git commit -m "feat: add fetch_history_one for OHLCV backfill"
```

---

## Task 3: Tạo backfill.py

**Files:**
- Create: `backfill.py` (gốc repo)

- [ ] **Step 1: Tạo file backfill.py**

```python
"""Backfill lịch sử giá OHLCV cho toàn bộ dim_symbols — Phase 1.5.

Chạy nhiều lần để hoàn tất (resumable nhờ backfill_status):

    python backfill.py               # 100 mã đầu, 3 năm lịch sử
    python backfill.py --limit 200   # 200 mã mỗi lần
    python backfill.py --years 5     # 5 năm lịch sử

Biến môi trường:
  WAREHOUSE_DB       (tuỳ chọn) mặc định data/warehouse.duckdb
  motherduck_token   (nếu dùng MotherDuck)
  VNSTOCK_API_KEY    (khuyến nghị) nâng rate limit lên 60 req/phút
"""
import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()
ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Backfill lịch sử giá OHLCV")
    parser.add_argument("--years", type=int, default=3, help="Số năm lịch sử (mặc định 3)")
    parser.add_argument("--limit", type=int, default=100, help="Số mã tối đa mỗi lần chạy (mặc định 100)")
    args = parser.parse_args()

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")

    end_date   = date.today().isoformat()
    start_date = (date.today() - timedelta(days=args.years * 365)).isoformat()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)
    warehouse.init_backfill_status(con)

    pending = warehouse.get_pending_symbols(con)
    total_pending = len(pending)
    batch = pending[:args.limit]

    print(f"Backfill: {len(batch)}/{total_pending} mã còn pending | {start_date} → {end_date}")

    done = error = skipped = 0
    for i, symbol in enumerate(batch, 1):
        df = ingest_market.fetch_history_one(symbol, start_date, end_date, source)
        if df.empty:
            warehouse.mark_backfill_error(con, symbol, "empty response")
            error += 1
            print(f"  [{i}/{len(batch)}] {symbol}: empty — skip")
            continue

        warehouse.upsert_prices(con, df)
        warehouse.mark_backfill_done(con, symbol, end_date)
        done += 1
        if i % 10 == 0 or i == len(batch):
            print(f"  [{i}/{len(batch)}] {symbol}: {len(df)} phiên — OK")

    warehouse.log_load(
        con, "backfill", "raw_price_daily",
        done,
        "ok" if error == 0 else "partial",
        watermark=end_date,
        notes=f"done={done} error={error} pending_after={total_pending - done}",
    )

    total_rows = con.execute("SELECT count(*) FROM raw_price_daily").fetchone()[0]
    print(f"\nXong batch: done={done} error={error}")
    print(f"raw_price_daily tổng: {total_rows:,} dòng")
    still_pending = len(warehouse.get_pending_symbols(con))
    if still_pending > 0:
        print(f"Còn {still_pending} mã chưa xong — chạy lại: python backfill.py --limit {args.limit}")
    else:
        print("Backfill hoàn tất!")

    con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Chạy thử smoke test với --limit 3**

```bash
source .venv/bin/activate
python backfill.py --limit 3 --years 1
```

Expected output gồm:
- Dòng `[history] cột thật (XXX): [...]` (in cột thật lần đầu)
- `[1/3] AAA: N phiên — OK` (hoặc `empty — skip`)
- `raw_price_daily tổng: X dòng`

Nếu cột bị thiếu (thiếu `close`/`date`), xem dòng `[history] cột thật` và chỉnh `_find(...)` trong `fetch_history_one`.

- [ ] **Step 3: Commit**

```bash
git add backfill.py
git commit -m "feat: add backfill.py for Phase 1.5 historical price backfill"
```

---

## Task 4: Chạy backfill đầy đủ và verify

- [ ] **Step 1: Chạy toàn bộ (chia batch 200)**

```bash
# Lần 1
python backfill.py --limit 200

# Lần 2 (chạy tiếp khi lần 1 xong)
python backfill.py --limit 200

# ... tiếp tục cho đến khi in "Backfill hoàn tất!"
# Tổng ~8 lần × ~10-15 phút/lần = ~80-100 phút
```

- [ ] **Step 2: Kiểm tra kết quả**

```python
# Chạy: python -c "..."
import duckdb
con = duckdb.connect("data/warehouse.duckdb")

print("=== Tổng dòng raw_price_daily ===")
print(con.execute("SELECT count(*) FROM raw_price_daily").fetchone())

print("=== Số mã distinct có lịch sử ===")
print(con.execute("SELECT count(DISTINCT symbol) FROM raw_price_daily WHERE trade_date < '2026-06-07'").fetchone())

print("=== Mẫu 5 dòng ===")
print(con.execute("SELECT * FROM raw_price_daily WHERE symbol='VNM' ORDER BY trade_date DESC LIMIT 5").fetchdf())

print("=== etl_load_log backfill ===")
print(con.execute("SELECT * FROM etl_load_log WHERE job_name='backfill'").fetchdf())

print("=== Mã còn lỗi ===")
print(con.execute("SELECT count(*) FROM backfill_status WHERE status='error'").fetchone())
```

Expected:
- `raw_price_daily` > 500,000 dòng
- Số mã distinct ≈ 1400+ (một số mã có thể API không trả lịch sử)
- `VNM` có ~750 phiên (3 năm × 250 phiên/năm)

- [ ] **Step 3: Push lên MotherDuck (tùy chọn — nếu muốn cloud có lịch sử)**

```bash
export WAREHOUSE_DB=md:vn_market
export motherduck_token=<token>
python backfill.py --limit 200
# Chạy lại nhiều lần cho đến khi xong
```

- [ ] **Step 4: Commit final + push**

```bash
git add -A
git commit -m "data: phase 1.5 backfill complete"
git push
```

---

## Báo cáo (dừng ở đây, đưa cho người dùng)

Sau Task 4, tổng hợp:
1. Dòng `[history] cột thật (XXX): [...]`
2. Tổng dòng `raw_price_daily`
3. Số mã distinct có lịch sử (trade_date < hôm nay)
4. Số mã lỗi (status='error') + lý do nếu có pattern
