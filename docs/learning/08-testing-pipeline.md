# 08 — Testing Pipeline (đọc hiểu toàn bộ `tests/`)

## Tại sao DE cần biết test?

DA thường không viết test — kết quả là con số, nhìn vào biết đúng hay sai. Nhưng DE xây pipeline tự động chạy lúc không có người nhìn. Không có test → không biết pipeline bị vỡ cho đến khi data sai lên dashboard.

**Hai loại lỗi pipeline thường gặp:**
- **Logic error**: Code chạy được nhưng tính sai (MA50 tính trên 30 ngày thay vì 50).
- **Contract error**: API trả cột tên khác → `_find()` không tìm được → kết quả rỗng âm thầm.

Test bắt cả hai loại này trước khi chạy production.

---

## Cấu trúc test trong repo

```
tests/
├── test_warehouse_backfill.py      ← test warehouse.py (backfill functions)
├── test_warehouse_phase2a.py       ← test warehouse.py (new tables Phase 2A)
├── test_warehouse_read.py          ← test warehouse.read_price_history
├── test_ingest_history.py          ← test ingest_market.fetch_history_one
├── test_ingest_financials.py       ← test fetch_financials, fetch_company_info
└── test_ingest_warehouse_fallback.py ← test ingest.fetch_history (warehouse-first)
```

---

## Khái niệm 1: pytest fixture

**Fixture** = hàm chuẩn bị "môi trường" để test dùng. Fixture chạy trước mỗi test, dọn dẹp sau khi xong.

```python
# tests/test_warehouse_backfill.py
@pytest.fixture
def con():
    c = duckdb.connect(":memory:")   # tạo database trong RAM, không phải file
    warehouse.init_warehouse(c)
    warehouse.init_backfill_status(c)
    return c                         # trả về connection cho test dùng
```

Khi test khai báo `con` là tham số, pytest tự động gọi fixture và inject kết quả:

```python
def test_init_creates_table(con):   # pytest thấy "con" → tự gọi fixture ở trên
    rows = con.execute("SELECT count(*) FROM backfill_status").fetchone()[0]
    assert rows == 0
```

**`:memory:`** là keyword của DuckDB (và SQLite): tạo database trong RAM thay vì file. Test xong → database biến mất. Mỗi test có database sạch, độc lập.

### yield fixture — dọn dẹp sau test

```python
# tests/test_warehouse_phase2a.py
@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c          # ← yield thay vì return
    c.close()        # ← chạy SAU khi test xong (cleanup)
```

`yield` fixture hoạt động như context manager:
- Code trước `yield` → chạy trước test (setup)
- `yield value` → đưa value cho test dùng
- Code sau `yield` → chạy sau test (teardown)

**Khi nào dùng `return` vs `yield`?**
- `return`: không cần dọn dẹp (`:memory:` database tự biến mất)
- `yield`: cần đóng connection, xóa file, reset state

### autouse fixture — chạy cho mọi test trong file

```python
# tests/test_ingest_history.py
@pytest.fixture(autouse=True)
def reset_module_state():
    import src.ingest_market as m
    m._printed_hist_cols = False   # reset trước test
    yield
    m._printed_hist_cols = False   # reset sau test
```

`autouse=True`: fixture này tự động áp dụng cho **tất cả** test trong file, không cần khai báo tham số.

**Tại sao cần reset `_printed_hist_cols`?**

`_printed_hist_cols` là module-level global — tồn tại xuyên suốt process. Nếu test 1 set nó thành `True`, test 2 chạy trong cùng process sẽ thấy `True` → hành vi khác. Reset về `False` trước/sau mỗi test đảm bảo tests độc lập.

---

## Khái niệm 2: Mock và patch

**Mock** = đối tượng giả, thay thế dependency thật để test không phụ thuộc API, database, network.

**Vấn đề không có mock**: Test `fetch_financials` sẽ gọi API vnstock thật → chậm, tốn rate limit, có thể fail do network.

**Giải pháp**: Thay `Finance` class bằng mock trả dữ liệu cố định.

### `patch` — thay thế object trong context

```python
# tests/test_ingest_financials.py
def test_fetch_financials_returns_expected_schema():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.return_value = _mock_finance_ratio()
        result = fetch_financials(["AAA"])
```

**Đọc từng dòng:**

`patch("src.ingest_market.Finance")`:
- Trong suốt `with` block, tên `Finance` trong module `src.ingest_market` bị thay bằng `MagicMock`.
- `as MockFin`: đặt tên cho mock đó để configure.

`MockFin.return_value.ratio.return_value = _mock_finance_ratio()`:
- `Finance(symbol=...)` → trả `MockFin.return_value` (instance giả).
- `.ratio()` gọi trên instance đó → trả `_mock_finance_ratio()` (DataFrame cố định).

`patch("src.ingest_market.ingest._throttle")`:
- Thay `_throttle` bằng mock không làm gì → test chạy không cần đợi 3 giây.

### Tại sao patch path là `"src.ingest_market.Finance"` chứ không phải `"vnstock.api.financial.Finance"`?

Đây là rule quan trọng nhất của `unittest.mock`:

> **Patch WHERE IT'S USED, not where it's defined.**

```python
# src/ingest_market.py
from vnstock.api.financial import Finance  # Finance được import vào đây

# Khi code chạy:
df = Finance(symbol=symbol, ...).ratio()   # dùng tên "Finance" trong module này
```

`patch("src.ingest_market.Finance")` thay thế cái tên `Finance` trong namespace của `src.ingest_market`. Nếu patch `"vnstock.api.financial.Finance"`, module `src.ingest_market` vẫn giữ reference cũ — mock không có hiệu lực.

### `MagicMock` — mock linh hoạt

```python
# tests/test_ingest_history.py
mock_quote = MagicMock()
mock_quote.history.return_value = _make_history_df()

with patch('src.ingest_market.Quote', return_value=mock_quote):
```

`MagicMock()`: object giả có thể được gọi như function, truy cập attribute tùy ý, không raise error.

`mock_quote.history.return_value = df`: khi code gọi `mock_quote.history(...)`, nó trả `df`.

`patch('...Quote', return_value=mock_quote)`: khi code gọi `Quote(symbol=...)`, trả `mock_quote` (không tạo instance mới).

### `side_effect` — kiểm soát hành vi phức tạp

```python
# Thay vì trả giá trị cố định, raise exception:
mock_quote.history.side_effect = Exception("API error")

# Hoặc trả các giá trị khác nhau theo lần gọi:
mock_quote.history.side_effect = [df1, df2, Exception("fail")]
# Lần 1 → df1, lần 2 → df2, lần 3 → raise Exception
```

### Verify mock được gọi

```python
# tests/test_ingest_warehouse_fallback.py
mock_wh.read_price_history.assert_called_once()
MockQuote.return_value.history.assert_called_once()
```

`assert_called_once()`: kiểm tra mock được gọi đúng 1 lần. Nếu không gọi hoặc gọi 2 lần → test fail. Dùng để kiểm tra "warehouse path được dùng" hay "API fallback được kích hoạt".

---

## Khái niệm 3: Đọc từng test file — tư duy test design

### `test_warehouse_backfill.py` — Test state machine

```python
def test_get_pending_returns_symbols_not_done(con):
    # Setup: AAA chưa có trong backfill_status, BBB đã done
    con.execute("INSERT INTO dim_symbols VALUES ('AAA', ...)")
    con.execute("INSERT INTO dim_symbols VALUES ('BBB', ...)")
    con.execute("INSERT INTO backfill_status VALUES ('BBB','done', ...)")

    pending = warehouse.get_pending_symbols(con)

    assert pending == ['AAA']   # chỉ AAA là pending
```

**Tư duy**: Test không test SQL — test **hành vi** của function. "Khi BBB đã done, `get_pending_symbols` phải trả về chỉ AAA." SQL là implementation detail.

```python
def test_error_to_done_clears_notes(con):
    warehouse.mark_backfill_error(con, 'HPG', 'timeout')  # lỗi trước
    warehouse.mark_backfill_done(con, 'HPG', '2026-06-07') # sau đó done
    row = con.execute("SELECT status, notes ...").fetchone()
    assert row[0] == 'done'
    assert row[1] is None   # notes phải bị xóa
```

Test **transition**: error → done phải xóa notes cũ. Đây là upsert behavior.

### `test_warehouse_read.py` — Test boundary conditions

```python
def test_read_price_history_respects_days_limit(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    assert len(result) <= 30   # ≤ chứ không phải ==
```

Tại sao `<=` thay vì `==`? Vì fixture tạo 60 ngày nhưng `days=30` nghĩa là "tối đa 30 phiên giao dịch". Nếu có ngày nghỉ hoặc trading halt, có thể ít hơn 30. `<=` flexible hơn, không bị fragile.

```python
def test_read_price_history_sorted_ascending(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    dates = result["trade_date"].tolist()
    assert dates == sorted(dates)
```

Test **sort order** — quan trọng vì downstream (tính MA, RSI) phụ thuộc vào thứ tự thời gian.

### `test_ingest_warehouse_fallback.py` — Test branching logic

```python
def test_fetch_history_uses_warehouse_when_enough_data():
    wh_df = _make_wh_df(n_rows=60)  # 60 rows > days//2 = 15 → dùng warehouse
    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest._throttle"):
        mock_wh.get_conn.return_value = mock_con
        mock_wh.read_price_history.return_value = wh_df

        result = fetch_history("AAA", days=30)

    assert not result.empty
    mock_wh.read_price_history.assert_called_once()  # warehouse được dùng
    # Không assert API được gọi → ngầm nghĩa API KHÔNG được gọi
```

```python
def test_fetch_history_falls_back_to_api_when_warehouse_empty():
    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest.Quote") as MockQuote, \
         patch("src.ingest._throttle"):
        mock_wh.read_price_history.return_value = pd.DataFrame()  # warehouse rỗng
        MockQuote.return_value.history.return_value = api_df

        result = fetch_history("AAA", days=30)

    MockQuote.return_value.history.assert_called_once()  # API ĐƯỢC gọi
```

**Pattern**: Một test cho happy path, một test cho mỗi failure mode. Cùng nhau, chúng map toàn bộ if/else branches trong code.

---

## Khái niệm 4: Unit test vs Integration test

| | Unit test | Integration test |
|---|---|---|
| Test gì | Một function, isolated | Nhiều component phối hợp |
| Dependencies | Mock tất cả | Dùng thật (DuckDB :memory:, real pandas) |
| Tốc độ | Rất nhanh (<1ms) | Chậm hơn (vài ms-giây) |
| Ví dụ trong repo | `test_ingest_warehouse_fallback.py` (mock warehouse) | `test_warehouse_backfill.py` (DuckDB :memory: thật) |

**Repo này mix cả hai:**
- Tests với `patch(...)` → unit tests (mọi external dependency bị mock)
- Tests với `duckdb.connect(":memory:")` → integration tests nhẹ (DuckDB thật, nhưng in-memory)

**Không có test nào chạm MotherDuck thật** — đây là lý do tests chạy được offline, không tốn quota.

---

## Chạy tests

```bash
# Chạy tất cả
python -m pytest tests/ -v

# Chạy 1 file
python -m pytest tests/test_warehouse_backfill.py -v

# Chạy 1 test cụ thể
python -m pytest tests/test_warehouse_backfill.py::test_mark_done_idempotent -v

# Xem coverage (cần pip install pytest-cov)
python -m pytest tests/ --cov=src --cov-report=term-missing
```

**Output `-v`:**
```
tests/test_warehouse_backfill.py::test_init_creates_table PASSED
tests/test_warehouse_backfill.py::test_get_pending_returns_symbols_not_done PASSED
...
36 passed in 4.32s
```

---

## Tự kiểm tra

1. Tại sao `duckdb.connect(":memory:")` tốt hơn `duckdb.connect("test.db")` trong tests?
2. Sự khác nhau giữa `return` và `yield` trong fixture là gì?
3. Tại sao patch `"src.ingest_market.Finance"` chứ không phải `"vnstock.api.financial.Finance"`?
4. `mock.assert_called_once()` và `mock.assert_not_called()` dùng để kiểm tra gì?
5. `autouse=True` có ý nghĩa gì? Khi nào cần dùng?
