# D — Tỷ giá & kho tin tức Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm 2 bảng warehouse mới (`raw_exchange_rate`, `raw_news`) + 2 tool MCP mới (`get_exchange_rate_history`, `get_recent_news`), ingest hằng ngày qua nguồn miễn phí đã xác nhận thật (`vcb_exchange_rate`, `Company.news()`).

**Architecture:** Theo đúng khuôn mẫu B1/B2 — Task 1 là cổng chặn kiểm `id` tin tức ổn định trước khi dùng append-only; Task 2 xây bảng + fetch/normalize/upsert + nối `build_warehouse.py`; Task 3 tầng dbt staging; Task 4 tool MCP; Task 5 nghiệm thu đầu-cuối trên production thật.

**Tech Stack:** Python 3.12 · vnstock 4.0.4 (`vnstock.explorer.misc.exchange_rate.vcb_exchange_rate`, `vnstock.api.company.Company.news`) · pandas · DuckDB/MotherDuck · dbt-duckdb · FastMCP · pytest

**Spec:** `docs/superpowers/specs/2026-08-23-d-vi-mo-tin-tuc-design.md`

## Global Constraints

- **Task 1 là cổng chặn**: phải xác nhận `id` tin tức ổn định giữa 2 lần gọi API thật (≥60 giây) trước khi bất kỳ task nào khác dùng append-only cho `raw_news`.
- **`raw_news` CHỈ fetch cho 5 mã trong `config/portfolio.yml`** (HPG, IDV, MLS, PHP, VNR) — không mở rộng ra toàn bộ universe.
- **`raw_exchange_rate`** ghi `INSERT OR REPLACE` theo `(currency_code, rate_date)`; **`raw_news`** ghi append-only (`INSERT ... WHERE NOT EXISTS`), giống hệt 2 mẫu đã có (`upsert_prices` kiểu OR REPLACE, `insert_corporate_events` kiểu append-only).
- **`buy_cash`/`buy_transfer`/`sell` = `"-"` từ nguồn → parse thành `NULL`**, không phải `0.0`.
- **Không dùng LLM.** Không đổi hệ thống bot cũ (`main.py`/`digest.py`/`src/ingest.py`/`storage.py`/`daily.yml`). Không làm CPI/lãi suất/tín dụng (không có nguồn miễn phí — xem spec §1.3). Không làm "cơ chế scan thị trường" (spec §1.4).
- Toàn bộ docstring, comment, commit message viết bằng tiếng Việt.
- Chạy test: `.venv/bin/python -m pytest tests/ -q`.
- Branch làm việc: `feat/d-vi-mo-tin-tuc` (đã tạo từ `main`, đã có commit spec).
- Nghiệm thu bắt buộc trên MotherDuck production thật (`WAREHOUSE_DB=md:vn_market`).

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `scripts/probe_news_id_stability.py` | **Mới.** Kiểm chứng `id` tin tức ổn định — chặn Task 2 | 1 |
| `src/warehouse.py` | **Sửa.** DDL `raw_exchange_rate`/`raw_news` + `upsert_exchange_rate`/`insert_news` | 2 |
| `src/ingest_market.py` | **Sửa.** `fetch_exchange_rate`, `fetch_news`, `_normalize_news` | 2 |
| `build_warehouse.py` | **Sửa.** Nối 2 bước mới, chạy mọi mode (giống bước 2b) | 2 |
| `transforms/models/staging/_sources.yml` | **Sửa.** Khai báo 2 source mới | 2 |
| `transforms/models/staging/stg_exchange_rate.sql` | **Mới.** View làm sạch nhẹ | 3 |
| `transforms/models/staging/stg_news.sql` | **Mới.** View làm sạch nhẹ | 3 |
| `transforms/models/staging/_staging.yml` | **Sửa.** Test schema cho 2 model mới | 3 |
| `mcp_server/tools.py` | **Sửa.** `get_exchange_rate_history`, `get_recent_news` | 4 |
| `mcp_server/server.py` | **Sửa.** Đăng ký 2 tool (11 → 13) | 4 |
| `tests/test_warehouse_macro.py` | **Mới.** Test DDL + upsert/insert | 2 |
| `tests/test_ingest_macro.py` | **Mới.** Test fetch/normalize | 2 |
| `tests/conftest_mart.py` | **Sửa.** Fixture `stg_exchange_rate`/`stg_news` | 4 |
| `tests/test_mcp_tools.py` | **Sửa.** Test 2 tool mới | 4 |
| `tests/test_mcp_server.py` | **Sửa.** Test qua `mcp.call_tool()` | 4 |
| `scripts/check_mcp_tools.py` | **Sửa.** Nghiệm thu 13 tool | 5 |
| `README.md` | **Sửa.** Cập nhật kiến trúc | 5 |

---

## Task 1: Kiểm chứng `id` tin tức ổn định — CHẶN

**Files:**
- Create: `scripts/probe_news_id_stability.py`

**Interfaces:**
- Consumes: `vnstock.api.company.Company`
- Produces: kết luận đi/không đi cho Task 2 trở đi. Không có code nào khác phụ thuộc file này.

> **Vì sao task này đứng riêng và đi trước:** thiết kế append-only của `raw_news` (Task 2) dựa vào giả định "`id` tin tức ổn định giữa các lần gọi, và cửa sổ 50-tin trượt theo thời gian chứ không đổi nội dung tin cũ". Nếu sai, `INSERT ... WHERE NOT EXISTS` có thể bỏ sót cập nhật hoặc (tệ hơn) hiểu nhầm 1 tin đã đổi nội dung là tin cũ không cần ghi lại. Xem spec §5.

- [ ] **Step 1: Viết script kiểm chứng**

```python
"""Kiểm chứng id tin tức (Company.news()) có ổn định giữa các lần gọi hay
không, trước khi dùng làm khoá append-only cho raw_news.

Company.news() trả ĐÚNG 50 dòng cho HPG (đã đo 2026-08-23) — trùng khớp
cửa sổ 50-sự-kiện đã biết của Company.events() (B1), cùng họ API
`Company`. Nếu id không ổn định hoặc cửa sổ không trượt như dự đoán, thiết
kế append-only ở Task 2 sẽ sai.

Chạy:
    set -a && source .env && set +a
    .venv/bin/python -m scripts.probe_news_id_stability

Exit code 0 = id ổn định, dùng append-only được.
Exit code 1 = KHÔNG ổn định, phải đổi khoá trước khi đi tiếp.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()
if os.getenv("VNSTOCK_API_KEY"):
    from vnstock import vnai
    vnai.setup_api_key(os.getenv("VNSTOCK_API_KEY"))

from vnstock.api.company import Company

# 5 mã portfolio thật (config/portfolio.yml) — đúng phạm vi raw_news sẽ dùng.
SAMPLES = ["HPG", "IDV", "MLS", "PHP", "VNR"]
SLEEP_BETWEEN_CALLS = 1.05
SLEEP_BETWEEN_ROUNDS = 60


def snapshot(symbol: str) -> dict[str, str]:
    """Trả {id: news_title} cho tin tức hiện có của 1 mã."""
    df = Company(symbol=symbol, source="VCI").news()
    if df is None or len(df) == 0:
        return {}
    df.columns = [str(c).lower() for c in df.columns]
    return dict(zip(df["id"].astype(str), df["news_title"].astype(str)))


def main() -> int:
    print(f"Vòng 1: gọi {len(SAMPLES)} mã...")
    first = {}
    for sym in SAMPLES:
        first[sym] = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"Chờ {SLEEP_BETWEEN_ROUNDS} giây trước vòng 2...")
    time.sleep(SLEEP_BETWEEN_ROUNDS)

    print("Vòng 2: gọi lại và đối chiếu...")
    ok = True
    for sym in SAMPLES:
        second = snapshot(sym)
        time.sleep(SLEEP_BETWEEN_CALLS)
        a, b = first[sym], second
        # Tin CÙNG id ở cả 2 vòng phải giữ NGUYÊN tiêu đề — id không được
        # tái sử dụng cho nội dung khác.
        common_ids = set(a) & set(b)
        changed = [i for i in common_ids if a[i] != b[i]]
        if changed:
            print(f"  {sym}: THẤT BẠI — {len(changed)} id giữ nguyên nhưng "
                  f"đổi tiêu đề. Ví dụ id={changed[0]!r}: "
                  f"vòng 1={a[changed[0]]!r} vòng 2={b[changed[0]]!r}")
            ok = False
        else:
            print(f"  {sym}: {len(common_ids)} id chung giữ nguyên tiêu đề, "
                  f"{len(set(b) - set(a))} id mới xuất hiện ở vòng 2, "
                  f"{len(set(a) - set(b))} id rơi khỏi cửa sổ — OK")

    print()
    if ok:
        print("KẾT LUẬN: id tin tức ỔN ĐỊNH — dùng append-only được. "
              "Tiếp tục Task 2.")
        return 0
    print("KẾT LUẬN: id tin tức KHÔNG ổn định — PHẢI xem lại thiết kế "
          "trước khi đi tiếp. BÁO CONTROLLER, KHÔNG tự đổi thiết kế.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Chạy script trên API thật**

```bash
set -a && source .env && set +a
.venv/bin/python -m scripts.probe_news_id_stability
```

Expected: in ra kết quả từng mã và một dòng KẾT LUẬN. Script chạy ~70 giây (60 giây chờ + 10 lần gọi × 1,05s + thời gian request thật).

- [ ] **Step 3: Ghi kết quả, dừng nếu thất bại**

Nếu exit code = 1: **DỪNG LẠI**, báo controller kèm output đầy đủ. Không tự đổi thiết kế.

Nếu exit code = 0: ghi vào báo cáo "id tin tức ổn định, xác nhận trên 5 mã portfolio" kèm output, rồi tiếp Task 2.

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_news_id_stability.py
git commit -m "test(d): script kiểm chứng id tin tức ổn định trước khi dùng append-only

Company.news() trả đúng 50 dòng cho HPG — trùng khớp cửa sổ 50-sự-kiện đã
biết của Company.events() (B1). Kiểm trước, chưa xong không xây bảng raw.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: `raw_exchange_rate` + `raw_news` + fetch/normalize/upsert + nối build_warehouse.py

**Files:**
- Modify: `src/warehouse.py`
- Modify: `src/ingest_market.py`
- Modify: `build_warehouse.py`
- Modify: `transforms/models/staging/_sources.yml`
- Create: `tests/test_warehouse_macro.py`
- Create: `tests/test_ingest_macro.py`

**Interfaces:**
- Consumes: `src.ingest._throttle()`, `src.dq.assert_columns`, `src.dq.SchemaError`, `vnstock.explorer.misc.exchange_rate.vcb_exchange_rate`, `vnstock.api.company.Company`
- Produces:
  - `warehouse.upsert_exchange_rate(con, df) -> int` — `INSERT OR REPLACE` theo `(currency_code, rate_date)`, trả số dòng.
  - `warehouse.insert_news(con, df) -> int` — append-only, trả số dòng THỰC SỰ thêm.
  - `ingest_market.fetch_exchange_rate(rate_date: str) -> pd.DataFrame` — cột `currency_code, currency_name, buy_cash, buy_transfer, sell, rate_date`.
  - `ingest_market.fetch_news(symbols: list[str], source: str = "VCI") -> pd.DataFrame` — cột `id, symbol, news_title, news_short_content, news_source_link, public_date`.
  - Bảng `raw_exchange_rate` (PK `(currency_code, rate_date)`), `raw_news` (PK `id`).

> **Bối cảnh không có trong Task 1**: Task 1 chỉ kiểm chứng giả định, KHÔNG tạo code sản xuất nào. `init_warehouse` (dòng 163-...) hiện có khối DDL cuối cùng là `alert_sent_log` (C2), ngay trước `def upsert_symbols`. `insert_corporate_events` (dòng 461) là template CHÍNH XÁC cho `insert_news` (cùng cơ chế append-only `WHERE NOT EXISTS`). `fetch_corporate_events`/`_normalize_events` (dòng 488/538) là template cho `fetch_news`/`_normalize_news` — đọc kỹ 2 hàm này trước khi viết, đặc biệt closure `text()`/`num()` và bài học "id qua text() không phải astype(str) trần" (M1, comment tại dòng 554-559).

- [ ] **Step 1: Viết test thất bại cho `upsert_exchange_rate`/`insert_news`**

Tạo `tests/test_warehouse_macro.py`:

```python
"""Test cho raw_exchange_rate (OR REPLACE) và raw_news (append-only, D)."""
import duckdb
import pandas as pd
import pytest

from src.warehouse import init_warehouse, insert_news, upsert_exchange_rate


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _rate_row(currency_code="USD", currency_name="US DOLLAR", buy_cash=25000.0,
             buy_transfer=25100.0, sell=25400.0, rate_date="2026-08-20", **kw):
    row = {"currency_code": currency_code, "currency_name": currency_name,
           "buy_cash": buy_cash, "buy_transfer": buy_transfer, "sell": sell,
           "rate_date": rate_date}
    row.update(kw)
    return row


def test_upsert_exchange_rate_ghi_dung_so_dong(con):
    df = pd.DataFrame([_rate_row(), _rate_row(currency_code="EUR")])
    assert upsert_exchange_rate(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_exchange_rate").fetchone()[0] == 2


def test_upsert_exchange_rate_cung_ngay_cung_ma_ghi_de(con):
    df1 = pd.DataFrame([_rate_row(sell=25400.0)])
    upsert_exchange_rate(con, df1)
    df2 = pd.DataFrame([_rate_row(sell=25500.0)])  # cùng khoá, giá trị mới
    upsert_exchange_rate(con, df2)
    row = con.execute(
        "SELECT sell FROM raw_exchange_rate WHERE currency_code='USD' AND rate_date='2026-08-20'"
    ).fetchone()
    assert row[0] == 25500.0
    assert con.execute("SELECT count(*) FROM raw_exchange_rate").fetchone()[0] == 1


def test_upsert_exchange_rate_buy_cash_null_giu_nguyen_null(con):
    """buy_cash NULL (nguồn trả '-') phải VẪN LÀ NULL sau khi ghi — không
    được biến thành 0.0 (khác 'không áp dụng' với 'tỷ giá bằng 0')."""
    df = pd.DataFrame([_rate_row(currency_code="DKK", buy_cash=None)])
    upsert_exchange_rate(con, df)
    row = con.execute(
        "SELECT buy_cash FROM raw_exchange_rate WHERE currency_code='DKK'"
    ).fetchone()
    assert row[0] is None


def test_upsert_exchange_rate_df_rong_tra_0(con):
    assert upsert_exchange_rate(con, pd.DataFrame()) == 0


def _news_row(id_="n1", symbol="HPG", news_title="Tiêu đề 1",
              news_short_content="Nội dung ngắn", news_source_link="https://x.com/1",
              public_date="2026-08-01T10:00:00"):
    return {"id": id_, "symbol": symbol, "news_title": news_title,
            "news_short_content": news_short_content,
            "news_source_link": news_source_link, "public_date": public_date}


def test_insert_news_them_moi_tra_dung_so_dong(con):
    df = pd.DataFrame([_news_row(id_="n1"), _news_row(id_="n2")])
    assert insert_news(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_news").fetchone()[0] == 2


def test_insert_news_khong_ghi_lai_id_da_co(con):
    """Append-only: gọi lại với id đã tồn tại KHÔNG tạo dòng mới, KHÔNG lỗi."""
    df = pd.DataFrame([_news_row(id_="n1", news_title="Bản gốc")])
    insert_news(con, df)
    df2 = pd.DataFrame([_news_row(id_="n1", news_title="Bản khác (không được ghi)"),
                        _news_row(id_="n2")])
    n = insert_news(con, df2)
    assert n == 1  # chỉ n2 thực sự mới
    assert con.execute(
        "SELECT news_title FROM raw_news WHERE id='n1'"
    ).fetchone()[0] == "Bản gốc"
    assert con.execute("SELECT count(*) FROM raw_news").fetchone()[0] == 2


def test_insert_news_tin_cu_khong_mat_khi_cua_so_truot(con):
    """Mô phỏng đúng ca thật: cửa sổ 50-tin trượt, tin cũ (n_old) rơi khỏi
    lần fetch mới nhưng PHẢI vẫn còn trong bảng."""
    insert_news(con, pd.DataFrame([_news_row(id_="n_old")]))
    insert_news(con, pd.DataFrame([_news_row(id_="n_new")]))  # n_old không có trong lần này
    ids = {r[0] for r in con.execute("SELECT id FROM raw_news").fetchall()}
    assert ids == {"n_old", "n_new"}


def test_insert_news_df_rong_tra_0(con):
    assert insert_news(con, pd.DataFrame()) == 0
    assert insert_news(con, None) == 0
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_warehouse_macro.py -q`
Expected: FAIL — `ImportError: cannot import name 'upsert_exchange_rate' from 'src.warehouse'`

- [ ] **Step 3: Thêm DDL + 2 hàm vào `src/warehouse.py`**

Thêm hằng cột ngay sau các hằng `*_COLS` hiện có (ví dụ sau `EVENT_COLS`):

```python
EXCHANGE_RATE_COLS = ["currency_code", "currency_name", "buy_cash", "buy_transfer", "sell", "rate_date"]
NEWS_COLS = ["id", "symbol", "news_title", "news_short_content", "news_source_link", "public_date"]
```

Thêm DDL vào cuối `init_warehouse` (ngay sau khối `alert_sent_log`, trước `def upsert_symbols`):

```python
    # --- D: tỷ giá VCB (OR REPLACE theo ngày+loại tiền — tỷ giá có thể
    # cập nhật lại trong cùng ngày, không phải dữ liệu sự kiện) ---
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_exchange_rate (
            currency_code   VARCHAR,
            currency_name   VARCHAR,
            buy_cash        DOUBLE,
            buy_transfer    DOUBLE,
            sell            DOUBLE,
            rate_date       DATE,
            ingested_at     TIMESTAMP,
            PRIMARY KEY (currency_code, rate_date)
        );
        """
    )
    # --- D: tin tức 5 mã portfolio (append-only) ---
    # id ổn định (xác nhận Task 1) — Company.news() chỉ trả 50 tin GẦN NHẤT
    # mỗi mã, cửa sổ trượt giống Company.events() (B1) — append-only để
    # không mất tin cũ khi cửa sổ trượt qua các lần fetch.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_news (
            id                  VARCHAR PRIMARY KEY,
            symbol              VARCHAR,
            news_title          VARCHAR,
            news_short_content  VARCHAR,
            news_source_link    VARCHAR,
            public_date         TIMESTAMP,
            ingested_at         TIMESTAMP
        );
        """
    )
```

Thêm 2 hàm ghi (đặt sau `insert_corporate_events`):

```python
def upsert_exchange_rate(con, df) -> int:
    """Ghi tỷ giá VCB. INSERT OR REPLACE theo (currency_code, rate_date) —
    tỷ giá có thể cập nhật lại trong cùng ngày, chạy lại an toàn."""
    if df is None or df.empty:
        return 0
    cols = ", ".join(EXCHANGE_RATE_COLS)
    con.register("df_fx", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_exchange_rate ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_fx;
        """
    )
    con.unregister("df_fx")
    return len(df)


def insert_news(con, df) -> int:
    """Ghi tin tức — APPEND-ONLY, giống hệt insert_corporate_events (B1).

    Company.news() chỉ trả 50 tin GẦN NHẤT mỗi mã, cửa sổ trượt theo thời
    gian (xác nhận Task 1, D) — nếu thay thế theo mỗi mẻ fetch, tin cũ rơi
    khỏi cửa sổ sẽ mất vĩnh viễn. Cộng dồn thì lịch sử dày lên theo thời
    gian bất kể giới hạn 50-tin của nguồn.

    Trả về số dòng THỰC SỰ được thêm (không phải len(df)).
    """
    if df is None or df.empty:
        return 0
    before = con.execute("SELECT count(*) FROM raw_news").fetchone()[0]
    cols = ", ".join(NEWS_COLS)
    con.register("df_news", df)
    con.execute(
        f"""
        INSERT INTO raw_news ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_news src
        WHERE src.id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM raw_news t WHERE t.id = src.id);
        """
    )
    con.unregister("df_news")
    after = con.execute("SELECT count(*) FROM raw_news").fetchone()[0]
    return after - before
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_warehouse_macro.py -q`
Expected: PASS — 9 passed

- [ ] **Step 5: Viết test thất bại cho fetch/normalize**

Tạo `tests/test_ingest_macro.py`:

```python
"""Test fetch/normalize tỷ giá + tin tức (D)."""
from unittest.mock import patch

import pandas as pd
import pytest

from src import dq
from src.ingest_market import fetch_exchange_rate, fetch_news
from src.warehouse import EXCHANGE_RATE_COLS, NEWS_COLS


def _fake_vcb_df():
    return pd.DataFrame({
        "CurrencyCode": ["USD", "DKK"],
        "CurrencyName": ["US DOLLAR", "DANISH KRONE"],
        "Buy Cash": [25000.0, "-"],
        "Buy Transfer": [25100.0, 4012.10],
        "Sell": [25400.0, 4165.55],
        "date": ["2026-08-20", "2026-08-20"],
    })


def test_fetch_exchange_rate_tra_dung_cot(monkeypatch):
    def _fake(date):
        df = _fake_vcb_df()
        df.columns = ["currency_code", "currency_name", "buy_cash",
                     "buy_transfer", "sell", "date"]
        return df
    monkeypatch.setattr("src.ingest_market.vcb_exchange_rate", _fake)
    out = fetch_exchange_rate("2026-08-20")
    assert list(out.columns) == EXCHANGE_RATE_COLS


def test_fetch_exchange_rate_dash_thanh_null(monkeypatch):
    def _fake(date):
        df = _fake_vcb_df()
        df.columns = ["currency_code", "currency_name", "buy_cash",
                     "buy_transfer", "sell", "date"]
        return df
    monkeypatch.setattr("src.ingest_market.vcb_exchange_rate", _fake)
    out = fetch_exchange_rate("2026-08-20")
    dkk = out[out["currency_code"] == "DKK"].iloc[0]
    assert pd.isna(dkk["buy_cash"])
    assert dkk["buy_transfer"] == 4012.10


def test_fetch_exchange_rate_nguon_loi_tra_df_rong(monkeypatch):
    def _fake(date):
        raise Exception("network error")
    monkeypatch.setattr("src.ingest_market.vcb_exchange_rate", _fake)
    out = fetch_exchange_rate("2026-08-20")
    assert list(out.columns) == EXCHANGE_RATE_COLS
    assert len(out) == 0


def _fake_news_df(ids):
    return pd.DataFrame({
        "id": ids,
        "news_title": [f"Tiêu đề {i}" for i in ids],
        "news_short_content": [f"Nội dung {i}" for i in ids],
        "news_source_link": [f"https://x.com/{i}" for i in ids],
        "public_date": ["2026-08-01T10:00:00"] * len(ids),
    })


def test_fetch_news_tra_dung_cot(monkeypatch):
    class FakeCompany:
        def __init__(self, symbol, source):
            self.symbol = symbol
        def news(self):
            return _fake_news_df(["n1", "n2"])
    monkeypatch.setattr("src.ingest_market.Company", FakeCompany)
    out = fetch_news(["HPG"])
    assert list(out.columns) == NEWS_COLS
    assert (out["symbol"] == "HPG").all()


def test_fetch_news_mot_ma_loi_giua_nhieu_ma_tot_bi_bo_qua(monkeypatch):
    class FakeCompany:
        def __init__(self, symbol, source):
            self.symbol = symbol
        def news(self):
            if self.symbol == "BAD":
                raise Exception("API lỗi")
            return _fake_news_df([f"{self.symbol}-n1"])
    monkeypatch.setattr("src.ingest_market.Company", FakeCompany)
    out = fetch_news(["HPG", "BAD", "VNR"])
    assert set(out["symbol"]) == {"HPG", "VNR"}


def test_fetch_news_id_none_bi_loai_qua_dq_schema_error(monkeypatch):
    """id thiếu cột (schema đổi) phải bị dq.SchemaError bắt theo TỪNG mã,
    không sập cả hàm — giống fetch_corporate_events (B1)."""
    class FakeCompany:
        def __init__(self, symbol, source):
            self.symbol = symbol
        def news(self):
            df = _fake_news_df(["n1"])
            return df.drop(columns=["id"])  # thiếu cột bắt buộc
    monkeypatch.setattr("src.ingest_market.Company", FakeCompany)
    out = fetch_news(["HPG"])
    assert len(out) == 0
```

- [ ] **Step 6: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_macro.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_exchange_rate' from 'src.ingest_market'`

- [ ] **Step 7: Thêm import + 3 hàm vào `src/ingest_market.py`**

Thêm import ở đầu file, cạnh các import `vnstock` hiện có:

```python
from vnstock.explorer.misc.exchange_rate import vcb_exchange_rate
```

Thêm vào cuối file:

```python
_NEWS_REQUIRED = ["id", "news_title"]
_printed_news_cols = False


def fetch_exchange_rate(rate_date: str) -> pd.DataFrame:
    """Tỷ giá VCB 1 ngày, qua vcb_exchange_rate() — API export thật của
    Vietcombank, không phải scrape HTML.

    buy_cash/buy_transfer/sell = '-' từ nguồn (loại tiền không áp dụng
    giao dịch đó) -> NULL, KHÔNG PHẢI 0.0 (missing != wrong, xem dq.py).
    """
    try:
        df = vcb_exchange_rate(date=rate_date)
    except Exception as e:
        print(f"[exchange_rate] {rate_date}: {e}")
        return pd.DataFrame(columns=warehouse.EXCHANGE_RATE_COLS)
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=warehouse.EXCHANGE_RATE_COLS)
    df.columns = [str(c).lower() for c in df.columns]
    dq.assert_columns(df, ["currency_code", "currency_name"], "vcb_exchange_rate")

    def num(col):
        # '-' và các chuỗi không parse được -> NaN qua errors='coerce',
        # to_numeric trên chuỗi '-' không tự nhận là số nên coerce về NaN
        # đúng ý muốn (NULL), không phải 0.0.
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else float("nan")

    out = pd.DataFrame({
        "currency_code": df["currency_code"].astype(str).str.strip(),
        "currency_name": df["currency_name"].astype(str).str.strip(),
        "buy_cash": num("buy_cash"),
        "buy_transfer": num("buy_transfer"),
        "sell": num("sell"),
        "rate_date": rate_date,
    })
    return out[warehouse.EXCHANGE_RATE_COLS]


def _normalize_news(df, symbol) -> pd.DataFrame:
    dq.assert_columns(df, _NEWS_REQUIRED, f"Company.news({symbol})")

    def text(col):
        if col not in df.columns:
            return None
        s = df[col]
        return s.astype(str).str.strip().where(s.notna(), None)

    out = pd.DataFrame({
        "id": text("id"),
        "symbol": symbol.upper().strip(),
        "news_title": text("news_title"),
        "news_short_content": text("news_short_content"),
        "news_source_link": text("news_source_link"),
    })
    # public_date CỐ Ý không qua text()/_date_col() — 2 helper đó ép về
    # CHUỖI ISO ngày (_date_col: "%Y-%m-%d", mất phần giờ), trong khi
    # public_date là cột TIMESTAMP thật (nguồn trả "2026-08-01T10:00:00",
    # cần giữ giờ). Giữ nguyên kiểu pandas.Timestamp (không stringify) —
    # con.register()+INSERT sẽ để DuckDB tự chuyển NaT thành SQL NULL đúng
    # cách; lỗi "NaT" bị stringify thành chuỗi literal (A3 fix round 1) chỉ
    # xảy ra khi gọi .astype(str)/.dt.strftime() TRÊN cột có NaT — ở đây
    # không gọi hàm nào như vậy nên không rơi vào bẫy đó.
    out["public_date"] = pd.to_datetime(df["public_date"], errors="coerce") if "public_date" in df.columns else pd.NaT
    return out[warehouse.NEWS_COLS]


def fetch_news(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    """Tin tức 5 mã portfolio qua Company.news().

    Nguồn chỉ trả 50 TIN GẦN NHẤT mỗi mã, cửa sổ trượt theo thời gian
    (xác nhận Task 1, D) — xem docstring warehouse.insert_news.

    Bắt dq.SchemaError theo TỪNG MÃ, giống fetch_corporate_events (B1) —
    một mã dị thường không được xoá sổ cả mẻ.
    """
    global _printed_news_cols
    frames = []
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Company(symbol=symbol, source=source).news()
        except Exception as e:
            print(f"[news] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [str(c).lower() for c in df.columns]
        if not _printed_news_cols:
            print(f"[news] cột thật ({symbol}): {list(df.columns)}")
            _printed_news_cols = True
        try:
            frames.append(_normalize_news(df, symbol))
        except dq.SchemaError as e:
            print(f"[news] {symbol}: {e}")
            continue
    if not frames:
        return pd.DataFrame(columns=warehouse.NEWS_COLS)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates("id")
```

**LƯU Ý cho implementer:** `Company`, `pd`, `warehouse`, `ingest`, `dq` đã được import sẵn ở đầu `src/ingest_market.py` (dùng bởi các hàm hiện có) — chỉ cần thêm dòng import `vcb_exchange_rate` như trên, không import lại các tên khác.

- [ ] **Step 8: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_ingest_macro.py tests/test_warehouse_macro.py -q`
Expected: PASS — 16 passed

- [ ] **Step 9: Nối vào `build_warehouse.py`**

Chèn khối này ngay **sau** khối `# 2b) Chỉ số thị trường — mọi mode` và **trước** khối `# 3) Financial ratios — weekly và monthly` (chạy MỌI mode, giống bước 2b — 2 nguồn này rẻ, không cần gate theo mode):

```python
    # 2c) Tỷ giá VCB — mọi mode (D). 1 lần gọi API/ngày, rẻ.
    fx = ingest_market.fetch_exchange_rate(run_date)
    n_fx = warehouse.upsert_exchange_rate(con, fx)
    warehouse.log_load(con, f"warehouse_{args.mode}", "raw_exchange_rate",
                       n_fx, "ok" if n_fx else "empty", watermark=run_date)
    print(f"raw_exchange_rate: {n_fx} dòng cho {run_date}")

    # 2d) Tin tức 5 mã portfolio — mọi mode (D). Rẻ (5 mã), append-only.
    portfolio_cfg = yaml.safe_load(open(ROOT / "config" / "portfolio.yml", encoding="utf-8"))
    portfolio_symbols = [h["symbol"] for h in portfolio_cfg["holdings"]]
    news = ingest_market.fetch_news(portfolio_symbols, source)
    n_news = warehouse.insert_news(con, news)
    warehouse.log_load(con, f"warehouse_{args.mode}", "raw_news",
                       n_news, "ok" if n_news else "empty", watermark=run_date,
                       notes=f"append-only; fetch {len(news)} dong")
    print(f"raw_news: +{n_news} dòng mới (fetch {len(news)})")
```

**LƯU Ý cho implementer:** đọc đầu `build_warehouse.py` để xác nhận `yaml`/`ROOT` đã import/định nghĩa sẵn ở top-level (dùng bởi `load_yaml`/`cfg` hiện có) — nếu đã có, dùng lại đúng tên biến đó, không tự tạo biến trùng tên khác.

- [ ] **Step 10: Khai báo 2 source cho dbt**

Trong `transforms/models/staging/_sources.yml`, thêm vào cuối danh sách `tables`:

```yaml
      - name: raw_exchange_rate
        loaded_at_field: ingested_at
        freshness:
          warn_after: {count: 3, period: day}
          error_after: {count: 10, period: day}
      - name: raw_news
        loaded_at_field: ingested_at
        freshness:
          warn_after: {count: 10, period: day}
          error_after: {count: 20, period: day}
```

- [ ] **Step 11: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — tăng đúng 16 test mới so với baseline trước Task 2, không mất test nào.

- [ ] **Step 12: Commit**

```bash
git add src/warehouse.py src/ingest_market.py build_warehouse.py \
        transforms/models/staging/_sources.yml \
        tests/test_warehouse_macro.py tests/test_ingest_macro.py
git commit -m "feat(d): bảng raw_exchange_rate + raw_news, fetch tỷ giá VCB + tin tức 5 mã

raw_exchange_rate: INSERT OR REPLACE theo (currency_code, rate_date), buy_cash
'-' parse thành NULL không phải 0.0. raw_news: append-only giống hệt
insert_corporate_events (B1) — Company.news() trả 50 tin gần nhất mỗi mã,
cửa sổ trượt (xác nhận Task 1). Cả hai chạy mọi mode trong build_warehouse.py
(rẻ, không cần gate theo weekly/monthly).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `stg_exchange_rate` + `stg_news`

**Files:**
- Create: `transforms/models/staging/stg_exchange_rate.sql`
- Create: `transforms/models/staging/stg_news.sql`
- Modify: `transforms/models/staging/_staging.yml`

**Interfaces:**
- Consumes: `source('warehouse', 'raw_exchange_rate')`, `source('warehouse', 'raw_news')` (Task 2)
- Produces: model `stg_exchange_rate` (6 cột giống raw), `stg_news` (6 cột giống raw) — view, không tính toán thêm.

- [ ] **Step 1: Viết 2 model**

`transforms/models/staging/stg_exchange_rate.sql`:

```sql
{{ config(materialized='view') }}

select
    currency_code,
    currency_name,
    buy_cash,
    buy_transfer,
    sell,
    rate_date
from {{ source('warehouse', 'raw_exchange_rate') }}
```

`transforms/models/staging/stg_news.sql`:

```sql
{{ config(materialized='view') }}

select
    id,
    symbol,
    news_title,
    news_short_content,
    news_source_link,
    public_date
from {{ source('warehouse', 'raw_news') }}
```

- [ ] **Step 2: Khai báo test schema**

Thêm vào cuối `models` của `transforms/models/staging/_staging.yml`:

```yaml
  - name: stg_exchange_rate
    description: "Tỷ giá VCB hằng ngày. Khoá (currency_code, rate_date)."
    columns:
      - name: currency_code
        tests: [not_null]
      - name: rate_date
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: [currency_code, rate_date]

  - name: stg_news
    description: >
      Tin tức 5 mã portfolio (config/portfolio.yml). id ổn định qua
      Company.news(), append-only ở tầng raw — xem Task 1/2 kế hoạch D.
    columns:
      - name: id
        tests: [not_null, unique]
      - name: symbol
        tests: [not_null]
      - name: news_title
        tests: [not_null]
```

- [ ] **Step 3: Chạy dbt build**

```bash
cd transforms
set -a && source ../.env && set +a
export motherduck_token="$MOTHERDUCK_TOKEN"
export WAREHOUSE_DB="md:vn_market"
dbt build --profiles-dir . --no-partial-parse --select stg_exchange_rate+ stg_news+
```

Expected: PASS toàn bộ — nếu `raw_exchange_rate`/`raw_news` chưa có dữ liệu thật (Task 2 mới chạy test local, chưa ingest production), model VIEW vẫn build được (view không cần bảng có dữ liệu), nhưng test `not_null`/`unique` sẽ báo 0 dòng — bình thường, chưa phải lỗi, sẽ có dữ liệu thật sau Task 5.

> **Bẫy đã biết:** `--no-partial-parse` bắt buộc.

- [ ] **Step 4: Commit**

```bash
git add transforms/models/staging/stg_exchange_rate.sql \
        transforms/models/staging/stg_news.sql \
        transforms/models/staging/_staging.yml
git commit -m "feat(d): stg_exchange_rate + stg_news — view làm sạch nhẹ

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: 2 tool MCP `get_exchange_rate_history` + `get_recent_news`

**Files:**
- Modify: `mcp_server/tools.py`
- Modify: `mcp_server/server.py`
- Modify: `tests/conftest_mart.py`
- Modify: `tests/test_mcp_tools.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `mcp_server.db.run_query`, `mcp_server.db.as_of`, `mcp_server.tools._clean`, `mcp_server.tools._date_str`, model `stg_exchange_rate`/`stg_news` (Task 3)
- Produces: `tools.get_exchange_rate_history(con, currency_code="USD", days=30) -> dict`, `tools.get_recent_news(con, symbol, limit=10) -> dict`

> **Bối cảnh không có trong Task 1-3**: `mcp_server/tools.py` hiện có 11 hàm tool — đọc `get_valuation_history` (chuỗi theo ngày, template gần nhất cho `get_exchange_rate_history`) và `get_distribution_history` (data_quality rõ ràng cho "không có gì", template cho `get_recent_news`'s "mã ngoài portfolio") TRƯỚC khi viết code mới.

- [ ] **Step 1: Mở rộng fixture `tests/conftest_mart.py`**

Thêm vào cuối hàm `build_fake_mart`, ngay trước `con.close()`:

```python
    # --- D: tỷ giá + tin tức ---
    con.execute("""
        CREATE TABLE stg_exchange_rate (
            currency_code VARCHAR, currency_name VARCHAR, buy_cash DOUBLE,
            buy_transfer DOUBLE, sell DOUBLE, rate_date DATE
        );
        INSERT INTO stg_exchange_rate VALUES
          ('USD','US DOLLAR',25000.0,25100.0,25400.0,DATE '2026-08-19'),
          ('USD','US DOLLAR',25050.0,25150.0,25450.0,DATE '2026-08-20'),
          ('DKK','DANISH KRONE',NULL,4012.10,4165.55,DATE '2026-08-20');

        CREATE TABLE stg_news (
            id VARCHAR, symbol VARCHAR, news_title VARCHAR,
            news_short_content VARCHAR, news_source_link VARCHAR,
            public_date TIMESTAMP
        );
        INSERT INTO stg_news VALUES
          ('n1','HPG','Tiêu đề mới nhất','Nội dung ngắn 1','https://x.com/1',
           TIMESTAMP '2026-08-20 10:00:00'),
          ('n2','HPG','Tiêu đề cũ hơn','Nội dung ngắn 2','https://x.com/2',
           TIMESTAMP '2026-08-19 09:00:00');
    """)
```

- [ ] **Step 2: Viết test thất bại**

Thêm vào cuối `tests/test_mcp_tools.py`:

```python
def test_get_exchange_rate_history_tra_dung_chuoi_theo_ngay(con):
    res = tools.get_exchange_rate_history(con, "USD", 30)
    assert res["currency_code"] == "USD"
    history = res["history"]
    assert len(history) == 2
    assert history[0]["rate_date"] == "2026-08-20"  # mới nhất trước


def test_get_exchange_rate_history_buy_cash_null_giu_none(con):
    res = tools.get_exchange_rate_history(con, "DKK", 30)
    assert res["history"][0]["buy_cash"] is None


def test_get_exchange_rate_history_ma_khong_ton_tai_tra_has_data_false(con):
    res = tools.get_exchange_rate_history(con, "ZZZ", 30)
    assert res["data_quality"]["has_data"] is False


def test_get_recent_news_tra_dung_thu_tu_moi_nhat_truoc(con):
    res = tools.get_recent_news(con, "HPG", 10)
    assert res["data_quality"]["has_data"] is True
    titles = [n["news_title"] for n in res["news"]]
    assert titles == ["Tiêu đề mới nhất", "Tiêu đề cũ hơn"]


def test_get_recent_news_ma_ngoai_portfolio_has_data_false_co_ghi_chu(con):
    res = tools.get_recent_news(con, "VCB", 10)
    assert res["data_quality"]["has_data"] is False
    assert "portfolio" in res["data_quality"]["note"].lower() or "danh mục" in res["data_quality"]["note"].lower()


def test_get_recent_news_cat_short_content_toi_da_300_ky_tu(con):
    con.execute("""
        INSERT INTO stg_news VALUES
          ('n3','HPG','Tin dài','""" + "x" * 500 + """','https://x.com/3',
           TIMESTAMP '2026-08-21 08:00:00')
    """)
    res = tools.get_recent_news(con, "HPG", 10)
    n3 = next(n for n in res["news"] if n["news_title"] == "Tin dài")
    assert len(n3["news_short_content"]) <= 300
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: FAIL — `AttributeError: module 'mcp_server.tools' has no attribute 'get_exchange_rate_history'`

- [ ] **Step 4: Cài đặt 2 hàm vào `mcp_server/tools.py`**

Thêm vào cuối file:

```python
_PORTFOLIO_SYMBOLS = None


def _load_portfolio_symbols() -> set[str]:
    """5 mã config/portfolio.yml — cache trong tiến trình, không đọc lại
    file mỗi lần gọi tool (đường dẫn cố định, không đổi khi server chạy)."""
    global _PORTFOLIO_SYMBOLS
    if _PORTFOLIO_SYMBOLS is None:
        import yaml
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "config" / "portfolio.yml"
        cfg = yaml.safe_load(open(path, encoding="utf-8"))
        _PORTFOLIO_SYMBOLS = {h["symbol"].upper() for h in cfg["holdings"]}
    return _PORTFOLIO_SYMBOLS


def get_exchange_rate_history(con, currency_code: str = "USD", days: int = 30) -> dict:
    """Chuỗi tỷ giá VCB theo ngày cho 1 loại ngoại tệ, mặc định USD."""
    code = currency_code.upper().strip()
    rows = db.run_query(
        con,
        """
        SELECT rate_date, buy_cash, buy_transfer, sell
        FROM stg_exchange_rate
        WHERE currency_code = ?
        ORDER BY rate_date DESC
        """,
        params=[code],
        limit=days,
    )
    if not rows:
        return {"currency_code": code, "data_quality": {"has_data": False},
                **db.as_of(con)}
    history = [
        {**r, "rate_date": _date_str(r["rate_date"])}
        for r in _clean(rows)
    ]
    return {
        "currency_code": code,
        "history": history,
        "data_quality": {"has_data": True},
        **db.as_of(con),
    }


def get_recent_news(con, symbol: str, limit: int = 10) -> dict:
    """Tin tức gần đây nhất đã lưu cho 1 mã — CHỈ hoạt động cho 5 mã trong
    config/portfolio.yml (D chỉ ingest tin cho danh mục, xem spec D §3.2)."""
    sym = symbol.upper().strip()
    if sym not in _load_portfolio_symbols():
        return {
            "symbol": sym,
            "data_quality": {
                "has_data": False,
                "note": f"{sym} không nằm trong danh mục theo dõi (portfolio.yml) — "
                        "D chỉ lưu tin tức cho các mã trong danh mục.",
            },
            **db.as_of(con),
        }
    rows = db.run_query(
        con,
        """
        SELECT news_title, news_short_content, news_source_link, public_date
        FROM stg_news
        WHERE symbol = ?
        ORDER BY public_date DESC
        """,
        params=[sym],
        limit=limit,
    )
    if not rows:
        return {"symbol": sym, "data_quality": {"has_data": False}, **db.as_of(con)}
    news = []
    for r in _clean(rows):
        content = r.get("news_short_content") or ""
        news.append({
            "news_title": r["news_title"],
            "news_short_content": content[:300],
            "news_source_link": r.get("news_source_link"),
            "public_date": _date_str(r["public_date"]),
        })
    return {
        "symbol": sym,
        "news": news,
        "data_quality": {"has_data": True},
        **db.as_of(con),
    }
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: PASS (tăng đúng 6 test mới so với baseline trước Task 4 — chạy `pytest tests/test_mcp_tools.py -q` trước khi bắt đầu Task 4 để biết baseline chính xác).

- [ ] **Step 6: Đăng ký 2 tool trong `mcp_server/server.py`**

Đọc 1-2 khối `@mcp.tool()` gần cuối file (ví dụ `get_thesis_update`) để bám đúng docstring style, rồi thêm vào cuối file, trước `if __name__ == "__main__":`:

```python
@mcp.tool()
@_safe_tool
def get_exchange_rate_history(currency_code: str = "USD", days: int = 30) -> dict:
    """Chuỗi tỷ giá VCB (Vietcombank) theo ngày cho 1 loại ngoại tệ.

    currency_code: mã ISO 3 ký tự (USD, EUR, JPY...), mặc định USD.
    buy_cash có thể NULL — loại tiền đó Vietcombank không giao dịch tiền
    mặt ngày đó, KHÔNG PHẢI tỷ giá bằng 0.

    Kiểm data_quality.has_data trước khi kết luận — mã ngoại tệ không có
    trong bảng trả về has_data=false.
    """
    return tools.get_exchange_rate_history(conn(), currency_code, days)


@mcp.tool()
@_safe_tool
def get_recent_news(symbol: str, limit: int = 10) -> dict:
    """Tin tức gần đây nhất cho 1 mã — CHỈ hoạt động cho các mã trong danh
    mục theo dõi (config/portfolio.yml), không phải toàn bộ thị trường.

    Mã ngoài danh mục trả data_quality.has_data=false kèm ghi chú rõ ràng
    — không phải mã không tồn tại, chỉ là chưa được theo dõi tin tức.
    """
    return tools.get_recent_news(conn(), symbol, limit)
```

- [ ] **Step 7: Viết + chạy test qua `mcp.call_tool()` thật**

Đọc `tests/test_mcp_server.py` hiện có trước để xác nhận đúng tên fixture đang dùng cho các test tool mới nhất (ví dụ `b1_con` hay tên khác — dùng ĐÚNG tên thật, KHÔNG đoán). Thêm vào cuối file:

```python
def test_get_exchange_rate_history_via_mcp_call_tool(b1_con, monkeypatch):
    monkeypatch.setattr(server, "conn", lambda: b1_con)
    content = asyncio.run(
        server.mcp.call_tool("get_exchange_rate_history", {"currency_code": "USD"})
    )
    payload = json.loads(content[0].text)
    assert "error" not in payload
    assert payload["data_quality"]["has_data"] is True


def test_get_recent_news_via_mcp_call_tool(b1_con, monkeypatch):
    monkeypatch.setattr(server, "conn", lambda: b1_con)
    content = asyncio.run(
        server.mcp.call_tool("get_recent_news", {"symbol": "HPG"})
    )
    payload = json.loads(content[0].text)
    assert "error" not in payload
    assert payload["data_quality"]["has_data"] is True
```

**LƯU Ý cho implementer:** nếu fixture `b1_con` đã đổi tên trong file thật lúc triển khai, dùng đúng tên mới — KHÔNG tự tạo fixture riêng trùng lặp.

- [ ] **Step 8: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — tăng đúng 8 test mới so với baseline trước Task 4 (6 test hàm trần + 2 test qua `mcp.call_tool()`).

- [ ] **Step 9: Commit**

```bash
git add mcp_server/tools.py mcp_server/server.py \
        tests/conftest_mart.py tests/test_mcp_tools.py tests/test_mcp_server.py
git commit -m "feat(d): tool get_exchange_rate_history + get_recent_news

get_recent_news chỉ hoạt động cho 5 mã portfolio (đúng phạm vi ingest D) —
mã ngoài danh mục trả has_data=false kèm ghi chú rõ ràng, không phải lỗi
mập mờ. news_short_content cắt tối đa 300 ký tự.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Nghiệm thu đầu-cuối trên dữ liệu thật

**Files:**
- Modify: `scripts/check_mcp_tools.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: toàn bộ Task 1-4.
- Produces: bằng chứng cho 6 tiêu chí hoàn thành trong spec §9.

- [ ] **Step 1: Mở rộng script nghiệm thu**

Trong `scripts/check_mcp_tools.py`, thêm vào hàm `main()` ngay sau lần gọi `get_thesis_update`, trước `run_sql`:

```python
    ok &= show("get_exchange_rate_history(USD)",
               tools.get_exchange_rate_history(con, "USD"))
    ok &= show("get_recent_news(HPG)",
               tools.get_recent_news(con, "HPG"))
```

- [ ] **Step 2: Chạy ingest thật trên production**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python build_warehouse.py --mode daily
```

Expected: chạy nhanh (job daily hiện tại vốn đã ngắn, D chỉ thêm ~10-15 giây). In ra `raw_exchange_rate: N dòng` và `raw_news: +N dòng mới`.

- [ ] **Step 3: Chạy dbt build**

```bash
cd transforms
dbt build --profiles-dir . --no-partial-parse 2>&1 | tail -20
```

Expected: PASS, ERROR=0.

- [ ] **Step 4: Nghiệm thu 13 tool trên dữ liệu thật**

```bash
.venv/bin/python -m scripts.check_mcp_tools
```

Expected: `TẤT CẢ ĐẠT`, exit code 0, cả 13 tool trả dữ liệu (11 tool cũ + 2 tool mới).

- [ ] **Step 5: Đối chiếu tay dữ liệu thật**

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market')
print('Tỷ giá USD hôm nay:', con.execute(\"SELECT * FROM raw_exchange_rate WHERE currency_code='USD' ORDER BY rate_date DESC LIMIT 1\").fetchone())
print('Tin tức HPG gần nhất:', con.execute(\"SELECT news_title, public_date FROM raw_news WHERE symbol='HPG' ORDER BY public_date DESC LIMIT 3\").fetchall())
"
```

Đối chiếu con số này với output của `get_exchange_rate_history`/`get_recent_news` ở Step 4 — phải khớp.

- [ ] **Step 6: Kiểm không đổi hành vi 11 tool cũ, không đụng hệ thống bot cũ**

```bash
git diff --stat main...HEAD -- mcp_server/tools.py mcp_server/server.py \
  main.py src/digest.py src/signals.py src/screener.py src/storage.py .github/workflows/daily.yml
```

Expected: `mcp_server/tools.py`/`server.py` chỉ có dòng THÊM; 6 file còn lại rỗng (không đụng). Nếu có dòng sửa/xoá ngoài dự kiến, dừng lại và báo controller.

- [ ] **Step 7: Cập nhật README**

Trong phần "Kiến trúc", đổi dòng mô tả `mcp_server/`:

```markdown
- `mcp_server/` — 13 tool read-only cho luồng hội thoại
```

- [ ] **Step 8: Chạy toàn bộ test lần cuối**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, không giảm so với baseline trước Task 5.

- [ ] **Step 9: Commit**

```bash
git add scripts/check_mcp_tools.py README.md
git commit -m "feat(d): nghiệm thu 13 tool trên production + cập nhật README

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành D (đối chiếu spec §9)

| # | Tiêu chí | Task |
|---|---|---|
| 1 | `id` tin tức ổn định (Task 1) | 1 |
| 2 | Toàn bộ pytest pass, không hỏng test cũ | 1-5 |
| 3 | `raw_exchange_rate`/`raw_news` có dữ liệu thật trên production | 5 |
| 4 | 13/13 tool đạt qua `check_mcp_tools.py` trên production | 5 |
| 5 | Đối chiếu tay khớp dữ liệu thật | 5 |
| 6 | Không đổi hành vi 11 tool cũ, không đụng hệ thống bot cũ | 5 (Step 6) |
