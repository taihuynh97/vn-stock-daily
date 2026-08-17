# B2 — BCTC chi tiết Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa toàn bộ chi tiết BCTC (income_statement/balance_sheet/cash_flow) vào warehouse dạng dài thống nhất, và phơi ra qua 1 tool MCP mới — nâng tổng số tool từ 9 lên 10.

**Architecture:** Một bảng raw duy nhất (`raw_financial_statement`) cho cả 3 báo cáo × 3 `com_class`, khoá theo `(symbol, statement_type, period_type, period_label, row_seq)` — `row_seq` (vị trí dòng trong lần fetch) thay cho `item_id` vì `item_id` không unique trong một báo cáo (đã đo: 22/122 dòng trùng ở balance_sheet HPG). Ghi `INSERT OR REPLACE` theo khoá đầy đủ — an toàn dù cửa sổ 8-kỳ trượt, vì khoá mịn tới từng kỳ.

**Tech Stack:** Python 3.12 · vnstock 4.0.4 (`vnstock.api.financial.Finance`) · pandas (`melt` để unpivot) · DuckDB/MotherDuck · dbt-duckdb · FastMCP · pytest

**Spec:** `docs/superpowers/specs/2026-08-17-b2-bctc-chi-tiet-design.md`

## Global Constraints

- **Task 1 là cổng chặn**: phải xác nhận vị trí dòng (`row_seq`) ổn định giữa 2 lần gọi API cách nhau ≥60 giây trước khi bất kỳ task nào khác dùng nó làm khoá.
- **Không đụng `mart_stock_scorecard`**, không đổi công thức chấm điểm (`src/scoring.py`, `config/scoring_profiles.yml`), không tính lại `revenue_ttm`/`earnings_ttm` suy ra (`int_fundamentals_ttm`, `fct_financial_quarterly`).
- **Không có cột `com_class` ở tầng raw/staging** — `com_class` là cột suy ra ở dbt (`stg_company_info.sql`), không tồn tại lúc Python ingest chạy. Ai cần lọc theo loại hình DN thì `JOIN dim_stock USING (symbol)`.
- **Bảng nguồn bất khả xâm phạm**: không code nào được DROP/ALTER/ghi vào `raw_price_daily`, `raw_financial_ratio`, `raw_company_info`, `raw_index_daily`, `dim_symbols`, `dim_industry`, `etl_load_log`, `backfill_status`, và (từ B1) `raw_corporate_event`, `raw_shareholder`, `raw_officer`.
- **Toàn bộ docstring, comment, commit message, tên test viết bằng tiếng Việt.**
- Chạy test: `.venv/bin/python -m pytest tests/ -q`.
- **Branch làm việc: `feat/b2-bctc-chi-tiet`** — tạo từ `main` TRƯỚC KHI B1 (`feat/b1-events-ownership`) merge. **BẮT BUỘC rebase/merge `main` mới nhất vào nhánh này trước khi dispatch Task 1** — nếu B1 đã merge vào lúc bắt đầu triển khai, nhánh này phải có đủ code B1 (đặc biệt `text()`/`_date_col` helper trong `src/ingest_market.py`, `_safe_tool` không kèm khoá `rows` trong `mcp_server/server.py`) để tránh xung đột và để tái dùng đúng pattern mới nhất.
- **Nghiệm thu bắt buộc trên MotherDuck production thật** (`WAREHOUSE_DB=md:vn_market`) ở mọi bước có `dbt build`/`build_warehouse.py`/gọi tool — không dùng dữ liệu tổng hợp thay cho xác nhận thật khi có thể chạy được.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `scripts/probe_statement_row_stability.py` | **Mới.** Kiểm chứng vị trí dòng ổn định — chặn mọi việc còn lại | 1 |
| `src/warehouse.py` | **Sửa.** `STATEMENT_COLS`, DDL `raw_financial_statement`, `upsert_financial_statements` | 2 |
| `src/ingest_market.py` | **Sửa.** `fetch_financial_statements`, `_unpivot_statement` | 2 |
| `build_warehouse.py` | **Sửa.** Nối `period="quarter"` vào weekly+monthly, `period="year"` vào monthly-only | 2 |
| `transforms/models/staging/_sources.yml` | **Sửa.** Khai báo source `raw_financial_statement` | 2 |
| `transforms/models/staging/stg_financial_statement.sql` | **Mới.** View làm sạch nhẹ | 3 |
| `transforms/models/staging/_staging.yml` | **Sửa.** Test schema cho model mới | 3 |
| `mcp_server/tools.py` | **Sửa.** `get_financial_statement` | 4 |
| `mcp_server/server.py` | **Sửa.** Đăng ký tool | 4 |
| `tests/test_warehouse_statements.py` | **Mới.** Test append/upsert + khử trùng | 2 |
| `tests/test_ingest_statements.py` | **Mới.** Test unpivot/normalize | 2 |
| `tests/conftest_mart.py` | **Sửa.** Thêm bảng giả cho tool mới | 4 |
| `tests/test_mcp_tools.py` | **Sửa.** Test tool mới | 4 |
| `tests/test_mcp_server.py` | **Sửa.** Test qua `mcp.call_tool()` | 4 |
| `scripts/check_mcp_tools.py` | **Sửa.** Nghiệm thu 10 tool | 5 |
| `README.md` | **Sửa.** Cập nhật kiến trúc | 5 |

---

## Task 1: Kiểm chứng vị trí dòng ổn định — CHẶN

**Files:**
- Create: `scripts/probe_statement_row_stability.py`

**Interfaces:**
- Consumes: `vnstock.api.financial.Finance`
- Produces: kết luận đi/không đi cho toàn bộ plan. Không có code nào khác phụ thuộc file này.

> **Vì sao task này đứng riêng và đi trước:** toàn bộ khoá `(symbol, statement_type, period_type, period_label, row_seq)` của Task 2 trở đi phụ thuộc vào giả định "vị trí dòng ổn định giữa các lần gọi API". Nếu sai, ghi `INSERT OR REPLACE` theo `row_seq` sẽ gán nhầm giá trị cho item khác — hỏng âm thầm, không lỗi rõ ràng. Xem spec §5.

- [ ] **Step 1: Viết script kiểm chứng**

```python
"""Kiểm chứng vị trí dòng (row_seq) của income_statement/balance_sheet/
cash_flow có ổn định giữa các lần gọi API hay không.

Toàn bộ thiết kế khoá của B2 (raw_financial_statement) dựa vào giả định
này — item_id KHÔNG unique trong một báo cáo (đã đo: balance_sheet của
HPG có 22/122 dòng trùng item_id, ví dụ "cost"/"accumulated_depreciation"
xuất hiện 4 lần mỗi cái vì 4 nhóm tài sản cố định khác nhau dùng chung
item_id). Chỉ vị trí dòng giữ đúng nhóm ngữ nghĩa — nếu vị trí đó xáo trộn
giữa các lần gọi, khoá `row_seq` sẽ gán nhầm giá trị cho item khác.

Chạy:
    set -a && source .env && set +a
    .venv/bin/python -m scripts.probe_statement_row_stability

Exit code 0 = vị trí dòng ổn định, dùng làm khoá được.
Exit code 1 = KHÔNG ổn định, phải đổi khoá trước khi đi tiếp.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()
if os.getenv("VNSTOCK_API_KEY"):
    from vnstock import vnai
    vnai.setup_api_key(os.getenv("VNSTOCK_API_KEY"))

from vnstock.api.financial import Finance

# Trộn cả 3 com_class — schema khác nhau hoàn toàn theo loại hình DN nên
# phải kiểm cả 3, không suy từ 1 nhóm ra nhóm khác.
SAMPLES = [
    ("HPG", "income_statement"), ("HPG", "balance_sheet"),
    ("VCB", "balance_sheet"), ("VCB", "cash_flow"),
    ("SSI", "income_statement"), ("SSI", "cash_flow"),
]
SLEEP_BETWEEN_CALLS = 1.05      # khớp VNSTOCK_MIN_INTERVAL của job thật
SLEEP_BETWEEN_ROUNDS = 60       # đủ dài để lộ vị trí sinh theo timestamp/session


def snapshot(symbol: str, statement: str) -> list[tuple[str, str]]:
    """Trả [(item_id, item_vi), ...] theo đúng thứ tự dòng trả về."""
    f = Finance(symbol=symbol, source="VCI", period="quarter")
    df = getattr(f, statement)()
    df = df.reset_index(drop=True)
    return list(zip(df["item_id"].astype(str), df["item"].astype(str)))


def main() -> int:
    print(f"Vòng 1: gọi {len(SAMPLES)} tổ hợp (mã, báo cáo)...")
    first = {}
    for sym, stmt in SAMPLES:
        first[(sym, stmt)] = snapshot(sym, stmt)
        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f"Chờ {SLEEP_BETWEEN_ROUNDS} giây trước vòng 2...")
    time.sleep(SLEEP_BETWEEN_ROUNDS)

    print("Vòng 2: gọi lại và đối chiếu theo VỊ TRÍ DÒNG...")
    ok = True
    for sym, stmt in SAMPLES:
        second = snapshot(sym, stmt)
        time.sleep(SLEEP_BETWEEN_CALLS)
        a, b = first[(sym, stmt)], second
        if len(a) != len(b):
            print(f"  {sym}/{stmt}: THẤT BẠI — số dòng đổi ({len(a)} → {len(b)})")
            ok = False
            continue
        lech = [i for i in range(len(a)) if a[i] != b[i]]
        if lech:
            print(f"  {sym}/{stmt}: THẤT BẠI — {len(lech)}/{len(a)} vị trí dòng "
                  f"đổi (item_id/item_vi khác nhau ở cùng vị trí). Ví dụ vị trí "
                  f"{lech[0]}: vòng 1={a[lech[0]]!r} vòng 2={b[lech[0]]!r}")
            ok = False
        else:
            print(f"  {sym}/{stmt}: {len(a)} dòng, TOÀN BỘ vị trí khớp")

    print()
    if ok:
        print("KẾT LUẬN: vị trí dòng ỔN ĐỊNH — dùng row_seq làm khoá được. "
              "Tiếp tục Task 2.")
        return 0
    print("KẾT LUẬN: vị trí dòng KHÔNG ổn định — PHẢI đổi khoá trước khi đi "
          "tiếp (ứng viên: (symbol, statement_type, period_type, "
          "period_label, item_id, item_vi), chấp nhận các dòng thật sự "
          "trùng cả item_id lẫn item_vi bị gộp). BÁO CONTROLLER, KHÔNG tự "
          "đổi thiết kế.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Chạy script trên API thật**

```bash
set -a && source .env && set +a
.venv/bin/python -m scripts.probe_statement_row_stability
```

Expected: in ra kết quả từng tổ hợp (mã, báo cáo) và một dòng KẾT LUẬN. Script chạy ~75 giây (60 giây chờ + 12 lần gọi × 1,05s + thời gian request thật).

- [ ] **Step 3: Ghi kết quả vào báo cáo, dừng nếu thất bại**

Nếu exit code = 1: **DỪNG LẠI**, báo controller kèm output đầy đủ. Không tự đổi khoá sang `(item_id, item_vi)` — đó là quyết định của controller vì nó đổi schema bảng và mọi task sau.

Nếu exit code = 0: ghi vào báo cáo "vị trí dòng ổn định, xác nhận trên 6 tổ hợp (mã, báo cáo) trải cả 3 com_class" kèm output, rồi tiếp Task 2.

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_statement_row_stability.py
git commit -m "test(b2): script kiểm chứng vị trí dòng BCTC ổn định trước khi dùng làm khoá

item_id không unique trong một báo cáo (đã đo balance_sheet HPG: 22/122
dòng trùng). Chỉ vị trí dòng giữ đúng nhóm ngữ nghĩa — kiểm trước, chưa
xong không xây bảng raw.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: `raw_financial_statement` + fetch/normalize/upsert + nối build_warehouse.py

**Files:**
- Modify: `src/warehouse.py` (thêm `STATEMENT_COLS`, DDL, `upsert_financial_statements`)
- Modify: `src/ingest_market.py` (thêm `fetch_financial_statements`, `_unpivot_statement`)
- Modify: `build_warehouse.py` (nối `period="quarter"` vào weekly+monthly, `period="year"` vào monthly-only)
- Modify: `transforms/models/staging/_sources.yml`
- Create: `tests/test_warehouse_statements.py`
- Create: `tests/test_ingest_statements.py`

**Interfaces:**
- Consumes: `src.ingest._throttle()`, `src.dq.assert_columns`, `src.dq.SchemaError`, `src.dq.status_for`
- Produces:
  - `warehouse.STATEMENT_COLS: list[str]` — 9 tên cột, đúng thứ tự: `["symbol", "statement_type", "period_type", "period_label", "row_seq", "item_id", "item_vi", "item_en", "value"]`
  - `warehouse.upsert_financial_statements(con, df) -> int` — `INSERT OR REPLACE`, trả `len(df)`
  - `ingest_market.fetch_financial_statements(symbols: list[str], source: str = "VCI", period: str = "quarter") -> pd.DataFrame` — cột đúng `warehouse.STATEMENT_COLS`
  - Bảng `raw_financial_statement` với `PRIMARY KEY (symbol, statement_type, period_type, period_label, row_seq)`

> **Bối cảnh không có trong Task 1**: Task 1 chỉ kiểm chứng giả định, KHÔNG tạo code sản xuất nào. `com_class` KHÔNG có ở tầng này (xem Global Constraints) — `raw_financial_statement` chỉ có `symbol`, không có cột loại hình DN.

- [ ] **Step 1: Viết test thất bại cho `upsert_financial_statements`**

Tạo `tests/test_warehouse_statements.py`:

```python
"""Test cho raw_financial_statement — cơ chế UPSERT theo khoá 5 cột.

Company.income_statement()/balance_sheet()/cash_flow() luôn trả TOÀN BỘ 8
kỳ gần nhất trong MỘT lần gọi (khác Company.events(), chỉ trả 50 sự kiện
gần nhất). Cửa sổ 8-kỳ CŨNG trượt theo thời gian (kỳ mới xuất hiện, kỳ cũ
nhất rơi khỏi cửa sổ) — nhưng khoá ở đây mịn tới từng KỲ
(period_label nằm trong khoá), nên INSERT OR REPLACE không đụng tới các
kỳ đã rơi khỏi cửa sổ fetch mới, khác hẳn nếu khoá chỉ tới (symbol,
statement_type) mà ghi đè cả khối.
"""
import duckdb
import pandas as pd
import pytest

from src.warehouse import STATEMENT_COLS, init_warehouse, upsert_financial_statements


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _row(symbol="AAA", statement_type="income_statement", period_type="quarter",
         period_label="2026-Q2", row_seq=0, item_id="net_sales",
         item_vi="Doanh thu thuần", value=100.0, **kw) -> dict:
    row = {
        "symbol": symbol, "statement_type": statement_type,
        "period_type": period_type, "period_label": period_label,
        "row_seq": row_seq, "item_id": item_id, "item_vi": item_vi,
        "item_en": "Net sales", "value": value,
    }
    row.update(kw)
    return row


def test_upsert_them_moi_tra_dung_so_dong(con):
    df = pd.DataFrame([_row(row_seq=0), _row(row_seq=1, item_id="cost_of_sales",
                                              item_vi="Giá vốn hàng bán")])[STATEMENT_COLS]
    assert upsert_financial_statements(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_financial_statement").fetchone()[0] == 2


def test_upsert_lai_cung_khoa_ghi_de_khong_them_dong(con):
    df = pd.DataFrame([_row(value=100.0)])[STATEMENT_COLS]
    upsert_financial_statements(con, df)
    df2 = pd.DataFrame([_row(value=200.0)])[STATEMENT_COLS]  # cùng khoá, giá trị mới
    upsert_financial_statements(con, df2)
    row = con.execute(
        "SELECT value FROM raw_financial_statement WHERE symbol='AAA'"
    ).fetchone()
    assert row[0] == 200.0
    assert con.execute("SELECT count(*) FROM raw_financial_statement").fetchone()[0] == 1


def test_ky_cu_khong_mat_khi_cua_so_8_ky_truot(con):
    """Ca thật: lần fetch sau, kỳ cũ nhất (period_label khác) đã rơi khỏi
    cửa sổ 8-kỳ trả về từ API. Bảng PHẢI giữ lại nó — đây chính là lý do
    khoá phải mịn tới period_label, không chỉ tới statement_type."""
    lan_1 = pd.DataFrame([
        _row(period_label="2024-Q3", row_seq=0),
        _row(period_label="2024-Q4", row_seq=0),
    ])[STATEMENT_COLS]
    upsert_financial_statements(con, lan_1)
    # Lần 2: "2024-Q3" đã rơi khỏi cửa sổ API, xuất hiện "2026-Q3"
    lan_2 = pd.DataFrame([
        _row(period_label="2024-Q4", row_seq=0),
        _row(period_label="2026-Q3", row_seq=0),
    ])[STATEMENT_COLS]
    upsert_financial_statements(con, lan_2)

    periods = {r[0] for r in con.execute(
        "SELECT period_label FROM raw_financial_statement"
    ).fetchall()}
    assert periods == {"2024-Q3", "2024-Q4", "2026-Q3"}


def test_hai_dong_khac_row_seq_cung_item_id_khong_de_len_nhau(con):
    """Ca thật: balance_sheet có 4 dòng cùng item_id='cost' (4 nhóm tài
    sản cố định khác nhau), phân biệt bởi row_seq. Khoá phải giữ cả 4."""
    df = pd.DataFrame([
        _row(item_id="cost", item_vi="Nguyên giá TSCĐ hữu hình",
             row_seq=30, value=1.0),
        _row(item_id="cost", item_vi="Nguyên giá tài sản thuê tài chính",
             row_seq=33, value=2.0),
        _row(item_id="cost", item_vi="Nguyên giá TSCĐ vô hình",
             row_seq=36, value=3.0),
        _row(item_id="cost", item_vi="Nguyên giá tài sản đầu tư",
             row_seq=40, value=4.0),
    ])[STATEMENT_COLS]
    assert upsert_financial_statements(con, df) == 4
    assert con.execute("SELECT count(*) FROM raw_financial_statement").fetchone()[0] == 4


def test_df_rong_tra_0(con):
    assert upsert_financial_statements(con, pd.DataFrame()) == 0
    assert upsert_financial_statements(con, None) == 0
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_warehouse_statements.py -q`
Expected: FAIL — `ImportError: cannot import name 'STATEMENT_COLS' from 'src.warehouse'`

- [ ] **Step 3: Thêm `STATEMENT_COLS` + DDL + `upsert_financial_statements` vào `src/warehouse.py`**

Thêm hằng ngay sau khối `OFFICER_COLS`:

```python
# --- Cột raw_financial_statement (nguồn: Company.Finance.income_statement/
# balance_sheet/cash_flow, unpivot wide -> dài) ---
# KHÔNG có cột com_class: đó là cột suy ra ở tầng dbt (stg_company_info.sql),
# không tồn tại lúc Python ingest chạy (ingest chạy TRƯỚC dbt build). symbol
# một mình đủ để JOIN dim_stock lấy com_class ở nơi cần lọc theo loại hình DN.
STATEMENT_COLS = [
    "symbol", "statement_type", "period_type", "period_label", "row_seq",
    "item_id", "item_vi", "item_en", "value",
]
```

Thêm DDL vào cuối `init_warehouse` (sau khối DDL `raw_officer` của B1):

```python
    # --- B2: BCTC chi tiết (upsert theo khoá mịn tới từng kỳ) ---
    # PRIMARY KEY gồm cả period_label lẫn row_seq: cửa sổ 8-kỳ trượt theo
    # thời gian giống sự kiện DN, nhưng khoá mịn tới từng kỳ khiến
    # INSERT OR REPLACE không đụng các kỳ đã rơi khỏi cửa sổ fetch mới —
    # xem docstring upsert_financial_statements.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_financial_statement (
            symbol         VARCHAR,
            statement_type VARCHAR,
            period_type    VARCHAR,
            period_label   VARCHAR,
            row_seq        INTEGER,
            item_id        VARCHAR,
            item_vi        VARCHAR,
            item_en        VARCHAR,
            value          DOUBLE,
            ingested_at    TIMESTAMP,
            PRIMARY KEY (symbol, statement_type, period_type, period_label, row_seq)
        );
        """
    )
```

Thêm hàm ghi (đặt ngay sau `upsert_officers`):

```python
def upsert_financial_statements(con, df) -> int:
    """Ghi chi tiết BCTC. INSERT OR REPLACE theo khoá 5 cột (symbol,
    statement_type, period_type, period_label, row_seq) → chạy lại cùng kỳ
    an toàn.

    Cửa sổ 8-kỳ mà Company.income_statement()/balance_sheet()/cash_flow()
    trả về CŨNG trượt theo thời gian (giống sự kiện DN) — kỳ mới xuất
    hiện, kỳ cũ nhất rơi khỏi cửa sổ. Nhưng KHÁC insert_corporate_events
    (phải append-only vì đơn vị trùng lặp là toàn bộ sự kiện, không gì
    phân biệt "sự kiện cũ" ngoài chính nó): ở đây khoá mịn tới từng KỲ
    (period_label nằm trong khoá cùng row_seq), nên khi kỳ cũ nhất rơi
    khỏi batch mới, INSERT OR REPLACE đơn giản KHÔNG ĐỤNG tới khoá đó —
    nó vẫn còn nguyên từ lần ghi trước. Ghi đè chỉ xảy ra khi CÙNG kỳ
    được fetch lại (giá trị hiếm khi đổi, nhưng nếu đổi thì bản mới đúng
    hơn).
    """
    if df is None or df.empty:
        return 0
    cols = ", ".join(STATEMENT_COLS)
    con.register("df_st", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_financial_statement ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_st;
        """
    )
    con.unregister("df_st")
    return len(df)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_warehouse_statements.py -q`
Expected: PASS — 5 passed

- [ ] **Step 5: Viết test thất bại cho unpivot/fetch**

Tạo `tests/test_ingest_statements.py`:

```python
"""Test unpivot wide -> dài cho BCTC (income_statement/balance_sheet/cash_flow)."""
import pandas as pd
import pytest

from src import dq
from src.ingest_market import _unpivot_statement, fetch_financial_statements
from src.warehouse import STATEMENT_COLS


def _wide_df(**kw) -> pd.DataFrame:
    """Dựng DataFrame giống nguyên trạng nguồn trả về — 3 cột item + N cột
    kỳ. Mặc định mô phỏng đúng ca thật: 'cost' xuất hiện 2 lần (2 nhóm tài
    sản khác nhau, cùng item_id, khác item/item_en) để test row_seq phân
    biệt được, cộng 1 dòng bình thường."""
    df = pd.DataFrame({
        "item":    ["Doanh thu thuần", "Nguyên giá TSCĐ hữu hình", "Nguyên giá tài sản đầu tư"],
        "item_en": ["Net sales", "Cost of tangible fixed assets", "Cost of investment property"],
        "item_id": ["net_sales", "cost", "cost"],
        "2026-Q2": [100.0, 10.0, 5.0],
        "2026-Q1": [90.0, 9.0, 4.0],
    })
    return df


def test_unpivot_tra_dung_bo_cot():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    assert list(out.columns) == STATEMENT_COLS


def test_unpivot_moi_dong_x_moi_ky_thanh_mot_dong_dai():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    # 3 dòng gốc x 2 cột kỳ = 6 dòng dài
    assert len(out) == 6


def test_unpivot_giu_dung_row_seq_phan_biet_hai_dong_trung_item_id():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    cost_rows = out[out["item_id"] == "cost"]
    assert set(cost_rows["row_seq"]) == {1, 2}
    r1 = cost_rows[cost_rows["row_seq"] == 1].iloc[0]
    r2 = cost_rows[cost_rows["row_seq"] == 2].iloc[0]
    assert r1["item_vi"] == "Nguyên giá TSCĐ hữu hình"
    assert r2["item_vi"] == "Nguyên giá tài sản đầu tư"


def test_unpivot_symbol_ep_hoa_va_statement_type_period_type_dung():
    out = _unpivot_statement(_wide_df(), "hpg", "balance_sheet", "quarter")
    assert (out["symbol"] == "HPG").all()
    assert (out["statement_type"] == "balance_sheet").all()
    assert (out["period_type"] == "quarter").all()


def test_unpivot_gia_tri_giu_dung_so():
    out = _unpivot_statement(_wide_df(), "HPG", "balance_sheet", "quarter")
    row = out[(out["item_id"] == "net_sales") & (out["period_label"] == "2026-Q2")]
    assert row.iloc[0]["value"] == pytest.approx(100.0)


def test_unpivot_df_rong_tra_df_rong_dung_cot():
    out = _unpivot_statement(pd.DataFrame(), "HPG", "balance_sheet", "quarter")
    assert list(out.columns) == STATEMENT_COLS
    assert len(out) == 0


def test_unpivot_df_none_tra_df_rong():
    out = _unpivot_statement(None, "HPG", "balance_sheet", "quarter")
    assert len(out) == 0
```

- [ ] **Step 6: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_statements.py -q`
Expected: FAIL — `ImportError: cannot import name '_unpivot_statement' from 'src.ingest_market'`

- [ ] **Step 7: Thêm `_unpivot_statement` + `fetch_financial_statements` vào `src/ingest_market.py`**

Thêm vào cuối file:

```python
_printed_statement_cols = {}

_STATEMENT_TYPES = ["income_statement", "balance_sheet", "cash_flow"]
_STATEMENT_REQUIRED = ["item_id", "item"]


def _unpivot_statement(df, symbol: str, statement_type: str, period_type: str) -> pd.DataFrame:
    """Ép DataFrame wide (item x kỳ) từ Company.Finance.*_statement() thành
    dạng dài (một dòng = một ô).

    row_seq = vị trí dòng TRONG DataFrame gốc (0-based, reset_index trước
    khi gán) — item_id KHÔNG unique trong một báo cáo (đã đo balance_sheet
    HPG: 22/122 dòng trùng item_id, ví dụ 'cost' xuất hiện 4 lần vì 4 nhóm
    tài sản cố định khác nhau dùng chung item_id). row_seq + item_vi mới
    giữ đúng nhóm ngữ nghĩa — xem Task 1 (kiểm vị trí dòng ổn định giữa
    các lần gọi) và spec §1.3/§3.1.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=warehouse.STATEMENT_COLS)
    dq.assert_columns(df, _STATEMENT_REQUIRED, f"Finance.{statement_type}({symbol})")

    df = df.reset_index(drop=True)
    df = df.assign(row_seq=df.index)
    period_cols = [c for c in df.columns
                  if c not in ("item", "item_en", "item_id", "row_seq")]

    long = df.melt(
        id_vars=["item_id", "item", "item_en", "row_seq"],
        value_vars=period_cols,
        var_name="period_label",
        value_name="value",
    )
    long["symbol"] = symbol.upper().strip()
    long["statement_type"] = statement_type
    long["period_type"] = period_type
    long["item_vi"] = long["item"]
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    return long[warehouse.STATEMENT_COLS]


def fetch_financial_statements(symbols: list[str], source: str = "VCI",
                               period: str = "quarter") -> pd.DataFrame:
    """Chi tiết BCTC (income_statement + balance_sheet + cash_flow) qua
    Company.Finance(symbol, source, period).

    `period="quarter"` trả 8 quý gần nhất (~2 năm); `period="year"` trả 8
    năm gần nhất — KHÔNG có tham số nào mở rộng quá 8 kỳ (đã kiểm cả 2 chế
    độ, xem spec §1.4). Cửa sổ 8-kỳ trượt theo thời gian giống sự kiện DN,
    nhưng khoá ghi mịn tới từng kỳ nên tích luỹ đúng qua nhiều lần chạy —
    xem docstring warehouse.upsert_financial_statements.

    Một số mã KHÔNG CÓ BCTC nào qua nguồn này (DataFrame rỗng hoàn toàn,
    0 dòng 0 cột — đã xác nhận thật với TDN/ULG, spec §1.2) — đây là
    trường hợp BÌNH THƯỜNG (thiếu dữ liệu, không phải lỗi schema), xử lý
    giống fetch_financials/fetch_company_info: bỏ qua mã đó, KHÔNG tính
    vào rejected (chỉ dq.SchemaError mới tính).

    Bắt SchemaError theo TỪNG (mã, loại báo cáo) — một báo cáo dị thường
    không được xoá sổ cả mẻ ~1.600 mã đang chạy.
    """
    frames, rejected, total_calls = [], 0, 0
    for symbol in symbols:
        for statement_type in _STATEMENT_TYPES:
            ingest._throttle()
            total_calls += 1
            try:
                fin = Finance(symbol=symbol, source=source, period=period)
                df = getattr(fin, statement_type)()
            except Exception as e:
                print(f"[statements] {symbol}/{statement_type}: {e}")
                continue
            if df is None or len(df) == 0:
                continue
            df.columns = [str(c).lower() for c in df.columns]
            if not _printed_statement_cols.get(statement_type):
                print(f"[statements] cột thật ({symbol}/{statement_type}): {list(df.columns)}")
                _printed_statement_cols[statement_type] = True
            try:
                row = _unpivot_statement(df, symbol, statement_type, period)
            except dq.SchemaError as e:
                print(f"[statements] {symbol}/{statement_type}: {e}")
                rejected += 1
                continue
            if row is not None and not row.empty:
                frames.append(row)
    if rejected and dq.status_for(len(frames), rejected) == "degraded":
        raise dq.SchemaError(
            f"[Finance statements] {rejected}/{total_calls} (mã, báo cáo) sai "
            "schema — nguồn có thể đã đổi"
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=warehouse.STATEMENT_COLS)
```

Thêm import ở đầu `src/ingest_market.py`, cùng chỗ với `from vnstock.api.company import Company` đã có sẵn:

```python
from vnstock.api.financial import Finance
```

- [ ] **Step 8: Chạy cả hai file test**

Run: `.venv/bin/python -m pytest tests/test_ingest_statements.py tests/test_warehouse_statements.py -q`
Expected: PASS — 12 passed

- [ ] **Step 9: Nối vào `build_warehouse.py`**

Chèn khối này ngay **sau** khối `# 3b) Sự kiện doanh nghiệp (B1)` (weekly+monthly) và **trước** khối `# 4) Dim_industry ... monthly only`:

```python
    # 3c) BCTC chi tiết (B2) — quarter chạy CẢ weekly lẫn monthly, cùng lý
    # do sự kiện DN chạy cả hai (monthly là superset của weekly).
    if args.mode in ("weekly", "monthly"):
        print(f"Bắt đầu fetch BCTC chi tiết, period=quarter ({len(symbols)} mã)...")
        stmt_q = ingest_market.fetch_financial_statements(symbols, source, period="quarter")
        n_stmt_q = warehouse.upsert_financial_statements(con, stmt_q)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_statement",
                           n_stmt_q, "ok" if n_stmt_q else "empty", watermark=run_date,
                           notes="period=quarter")
        print(f"raw_financial_statement (quarter): {n_stmt_q} dòng")

    # 3d) BCTC chi tiết, period=year — CHỈ monthly (dữ liệu năm hiếm khi
    # đổi, không cần nhịp tuần; xếp cùng nhịp với company_info/shareholders
    # bên dưới thay vì chạy tuần vô ích).
    if args.mode == "monthly":
        print(f"Bắt đầu fetch BCTC chi tiết, period=year ({len(symbols)} mã)...")
        stmt_y = ingest_market.fetch_financial_statements(symbols, source, period="year")
        n_stmt_y = warehouse.upsert_financial_statements(con, stmt_y)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_statement",
                           n_stmt_y, "ok" if n_stmt_y else "empty", watermark=run_date,
                           notes="period=year")
        print(f"raw_financial_statement (year): {n_stmt_y} dòng")
```

- [ ] **Step 10: Khai báo source cho dbt**

Trong `transforms/models/staging/_sources.yml`, thêm vào cuối danh sách `tables`:

```yaml
      - name: raw_financial_statement
        loaded_at_field: ingested_at
        freshness:
          warn_after: {count: 10, period: day}
          error_after: {count: 20, period: day}
```

- [ ] **Step 11: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — không giảm so với baseline hiện tại (chạy `pytest tests/ -q` trước khi bắt đầu Task 2 để biết baseline chính xác — không dùng con số cứng, vì baseline phụ thuộc trạng thái merge B1 lúc triển khai; chỉ kiểm PASS + tăng đúng 12 test mới, không mất test nào).

- [ ] **Step 12: Commit**

```bash
git add src/warehouse.py src/ingest_market.py build_warehouse.py \
        transforms/models/staging/_sources.yml \
        tests/test_warehouse_statements.py tests/test_ingest_statements.py
git commit -m "feat(b2): bảng raw_financial_statement + fetch/unpivot BCTC chi tiết

item_id không unique trong một báo cáo (balance_sheet HPG: 22/122 dòng
trùng, 4 nhóm tài sản cố định dùng chung item_id 'cost'). Khoá ghi dùng
row_seq (vị trí dòng, đã kiểm ổn định ở Task 1) thay vì item_id.

INSERT OR REPLACE theo khoá mịn tới từng kỳ (period_label nằm trong khoá)
— tích luỹ đúng qua nhiều lần chạy dù cửa sổ API chỉ trả 8 kỳ gần nhất mỗi
lần, vì kỳ cũ rơi khỏi cửa sổ đơn giản không bị đụng tới.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `stg_financial_statement`

**Files:**
- Create: `transforms/models/staging/stg_financial_statement.sql`
- Modify: `transforms/models/staging/_staging.yml`

**Interfaces:**
- Consumes: `source('warehouse', 'raw_financial_statement')` (Task 2)
- Produces: model `stg_financial_statement` — view, cùng 9 cột như `raw_financial_statement` (không thêm/bớt cột, chỉ ép kiểu nhẹ nếu cần)

- [ ] **Step 1: Viết model**

```sql
{{ config(materialized='view') }}

-- Làm sạch nhẹ raw_financial_statement — không tính lại gì, không JOIN
-- com_class (cột đó không có ở tầng này, xem Global Constraints của plan).
-- Ai cần lọc theo loại hình DN thì JOIN dim_stock USING (symbol) ở tầng
-- gọi model này.
select
    symbol,
    statement_type,
    period_type,
    period_label,
    row_seq,
    item_id,
    item_vi,
    item_en,
    value
from {{ source('warehouse', 'raw_financial_statement') }}
```

- [ ] **Step 2: Khai báo test schema**

Thêm vào cuối `models` của `transforms/models/staging/_staging.yml`:

```yaml
  - name: stg_financial_statement
    description: >
      Chi tiết BCTC dạng dài (income_statement/balance_sheet/cash_flow).
      Khoá là (symbol, statement_type, period_type, period_label, row_seq)
      — row_seq (vị trí dòng gốc) thay cho item_id vì item_id KHÔNG unique
      trong một báo cáo (vd 'cost' xuất hiện 4 lần ở balance_sheet, mỗi
      lần một nhóm tài sản cố định khác nhau).
    columns:
      - name: symbol
        tests: [not_null]
      - name: statement_type
        tests:
          - not_null
          - accepted_values:
              values: ['income_statement', 'balance_sheet', 'cash_flow']
      - name: period_type
        tests:
          - not_null
          - accepted_values:
              values: ['quarter', 'year']
      - name: item_id
        tests: [not_null]
      - name: item_vi
        tests: [not_null]
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns:
            [symbol, statement_type, period_type, period_label, row_seq]
```

- [ ] **Step 3: Chạy dbt build**

```bash
cd transforms
set -a && source ../.env && set +a
export motherduck_token="$MOTHERDUCK_TOKEN"
export WAREHOUSE_DB="md:vn_market"
dbt build --profiles-dir . --no-partial-parse --select stg_financial_statement+ --vars '{}'
```

Expected: PASS toàn bộ (model + 1 singular test `unique_combination_of_columns` + 4 schema test).

> **Bẫy đã biết:** `--no-partial-parse` là bắt buộc (xem tiền lệ A2/B1 — `target/partial_parse.msgpack` từng tạo GREEN GIẢ ngay sau RED).

- [ ] **Step 4: Kiểm phân bố `statement_type`/`period_type` trên dữ liệu thật**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market')
print(con.execute('''
  select statement_type, period_type, count(distinct symbol) as n_ma, count(*) as n_dong
  from stg_financial_statement group by 1,2 order by 1,2
''').df().to_string(index=False))
"
```

Expected: 6 tổ hợp (3 `statement_type` × 2 `period_type`), mỗi tổ hợp có hàng trăm/nghìn mã. Ghi số liệu vào báo cáo — nếu `n_ma` cho `period_type='year'` gần bằng 0, có gì đó sai ở Task 2 Step 9 (nhánh `monthly`-only chưa chạy hoặc chưa commit đúng).

- [ ] **Step 5: Commit**

```bash
git add transforms/models/staging/stg_financial_statement.sql \
        transforms/models/staging/_staging.yml
git commit -m "feat(b2): stg_financial_statement — view làm sạch nhẹ

Không JOIN com_class (không có ở tầng này) — ai cần lọc loại hình DN tự
JOIN dim_stock USING (symbol).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Tool MCP `get_financial_statement`

**Files:**
- Modify: `mcp_server/tools.py` (thêm `get_financial_statement`)
- Modify: `mcp_server/server.py` (đăng ký tool)
- Modify: `tests/conftest_mart.py` (thêm bảng `stg_financial_statement` giả)
- Modify: `tests/test_mcp_tools.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `mcp_server.db.run_query`, `mcp_server.db.as_of`, `mcp_server.tools._clean`, model `stg_financial_statement` (Task 3)
- Produces: `tools.get_financial_statement(con, symbol: str, statement_type: str, period_type: str = "quarter") -> dict`

- [ ] **Step 1: Mở rộng fixture `tests/conftest_mart.py`**

Thêm vào cuối hàm `build_fake_mart`, ngay trước `con.close()`:

```python
    # --- B2: BCTC chi tiết ---
    # Mô phỏng đúng ca thật: item_id 'cost' trùng 2 lần (2 nhóm tài sản
    # khác nhau, cùng item_id, khác item_vi/row_seq) — đúng bài học A3
    # I2/B1 Task 4/5: fixture phải khớp schema/hành vi thật, không chỉ khớp
    # tên cột, nếu không lỗi phân biệt row_seq sẽ lọt qua mọi test.
    con.execute("""
        CREATE TABLE stg_financial_statement (
            symbol VARCHAR, statement_type VARCHAR, period_type VARCHAR,
            period_label VARCHAR, row_seq INTEGER, item_id VARCHAR,
            item_vi VARCHAR, item_en VARCHAR, value DOUBLE
        );
        INSERT INTO stg_financial_statement VALUES
          ('AAA','income_statement','quarter','2026-Q2',0,'net_sales','Doanh thu thuần','Net sales',100.0),
          ('AAA','income_statement','quarter','2026-Q1',0,'net_sales','Doanh thu thuần','Net sales',90.0),
          ('AAA','balance_sheet','quarter','2026-Q2',30,'cost','Nguyên giá TSCĐ hữu hình','Cost of tangible FA',10.0),
          ('AAA','balance_sheet','quarter','2026-Q1',30,'cost','Nguyên giá TSCĐ hữu hình','Cost of tangible FA',9.0),
          ('AAA','balance_sheet','quarter','2026-Q2',40,'cost','Nguyên giá tài sản đầu tư','Cost of investment property',5.0),
          ('AAA','balance_sheet','quarter','2026-Q1',40,'cost','Nguyên giá tài sản đầu tư','Cost of investment property',4.0);
    """)
```

- [ ] **Step 2: Viết test thất bại**

Thêm vào cuối `tests/test_mcp_tools.py`:

```python
def test_get_financial_statement_tra_dung_dang_moi_dong_kem_chuoi_ky(con):
    res = tools.get_financial_statement(con, "AAA", "income_statement")
    assert res["symbol"] == "AAA"
    assert res["statement_type"] == "income_statement"
    assert res["n_items"] == 1
    item = res["items"][0]
    assert item["item_id"] == "net_sales"
    assert item["item_vi"] == "Doanh thu thuần"
    assert item["values_by_period"]["2026-Q2"] == 100.0
    assert item["values_by_period"]["2026-Q1"] == 90.0


def test_get_financial_statement_phan_biet_hai_dong_trung_item_id_bang_row_seq(con):
    """Ca quan trọng nhất: 'cost' xuất hiện 2 lần trong balance_sheet AAA
    (2 nhóm tài sản khác nhau) — phải trả về 2 item riêng biệt, không gộp
    nhầm thành 1 (đúng lý do row_seq tồn tại, spec §1.3)."""
    res = tools.get_financial_statement(con, "AAA", "balance_sheet")
    assert res["n_items"] == 2
    cost_items = [i for i in res["items"] if i["item_id"] == "cost"]
    assert len(cost_items) == 2
    vi_labels = {i["item_vi"] for i in cost_items}
    assert vi_labels == {"Nguyên giá TSCĐ hữu hình", "Nguyên giá tài sản đầu tư"}
    row_seqs = {i["row_seq"] for i in cost_items}
    assert row_seqs == {30, 40}


def test_get_financial_statement_ma_khong_co_du_lieu_tra_has_data_false(con):
    res = tools.get_financial_statement(con, "ZZZ", "income_statement")
    assert res["data_quality"]["has_data"] is False
    assert "n_items" not in res or res.get("items") in (None, [])


def test_get_financial_statement_period_type_khong_ton_tai_tra_has_data_false(con):
    """AAA có dữ liệu quarter nhưng fixture không có year — has_data phải
    phản ánh đúng THEO period_type được hỏi, không phải theo mã nói
    chung."""
    res = tools.get_financial_statement(con, "AAA", "income_statement", period_type="year")
    assert res["data_quality"]["has_data"] is False
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: FAIL — `AttributeError: module 'mcp_server.tools' has no attribute 'get_financial_statement'`

- [ ] **Step 4: Thêm hàm vào `mcp_server/tools.py`**

Thêm vào cuối file:

```python
def get_financial_statement(con, symbol: str, statement_type: str,
                            period_type: str = "quarter") -> dict:
    """Chi tiết một báo cáo tài chính (income_statement/balance_sheet/
    cash_flow), mỗi dòng BCTC kèm chuỗi giá trị theo kỳ.

    row_seq trả kèm mỗi item để phân biệt các dòng TRÙNG item_id — item_id
    KHÔNG unique trong một báo cáo (vd 'cost' xuất hiện nhiều lần ở
    balance_sheet, mỗi lần một nhóm tài sản cố định khác nhau — chỉ
    item_vi/row_seq phân biệt được, xem spec B2 §1.3). Agent nên hiển thị
    item_vi cho người dùng, không phải row_seq.
    """
    sym = symbol.upper().strip()
    st = statement_type.strip()
    pt = period_type.strip()

    rows = db.run_query(
        con,
        """
        SELECT row_seq, item_id, item_vi, item_en, period_label, value
        FROM stg_financial_statement
        WHERE symbol = ? AND statement_type = ? AND period_type = ?
        ORDER BY row_seq, period_label DESC
        """,
        params=[sym, st, pt],
        limit=2000,
    )

    if not rows:
        return {
            "symbol": sym, "statement_type": st, "period_type": pt,
            "data_quality": {"has_data": False},
            **db.as_of(con),
        }

    # Gộp lại theo (row_seq, item_id, item_vi) -> {period_label: value},
    # giữ nguyên thứ tự row_seq đã sort ở SQL.
    items_by_seq: dict[int, dict] = {}
    order: list[int] = []
    for r in rows:
        seq = r["row_seq"]
        if seq not in items_by_seq:
            items_by_seq[seq] = {
                "item_id": r["item_id"],
                "item_vi": r["item_vi"],
                "row_seq": seq,
                "values_by_period": {},
            }
            order.append(seq)
        items_by_seq[seq]["values_by_period"][r["period_label"]] = _clean(r["value"])

    items = [items_by_seq[s] for s in order]

    return {
        "symbol": sym,
        "statement_type": st,
        "period_type": pt,
        "items": items,
        "n_items": len(items),
        "data_quality": {"has_data": True, "n_periods_available": len(
            {p for it in items for p in it["values_by_period"]}
        )},
        **db.as_of(con),
    }
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: PASS (kỳ vọng tăng đúng 4 test mới so với baseline trước Task 4 — chạy `pytest tests/test_mcp_tools.py -q` trước khi bắt đầu Task 4 để biết baseline chính xác, không dùng con số cứng vì phụ thuộc trạng thái B1 lúc triển khai).

- [ ] **Step 6: Đăng ký tool trong `mcp_server/server.py`**

Thêm vào cuối file, trước khối `if __name__ == "__main__":`:

```python
@mcp.tool()
@_safe_tool
def get_financial_statement(symbol: str, statement_type: str,
                            period_type: str = "quarter") -> dict:
    """Chi tiết một báo cáo tài chính, mỗi dòng kèm chuỗi giá trị theo kỳ.

    statement_type: 'income_statement' (kết quả kinh doanh) /
                     'balance_sheet' (cân đối kế toán) /
                     'cash_flow' (lưu chuyển tiền tệ).
    period_type: 'quarter' (8 quý gần nhất, mặc định) / 'year' (8 năm gần nhất).

    Một số item_id (ví dụ 'cost'/'accumulated_depreciation' ở
    balance_sheet) XUẤT HIỆN NHIỀU LẦN trong cùng báo cáo — mỗi lần một
    nhóm tài sản khác nhau, phân biệt bởi item_vi (tên tiếng Việt), không
    phải item_id. Luôn hiển thị item_vi cho người dùng.

    Kiểm data_quality.has_data trước khi kết luận — một số mã (đặc biệt
    vốn hoá nhỏ) không có BCTC nào qua nguồn này.
    """
    return tools.get_financial_statement(conn(), symbol, statement_type, period_type)
```

- [ ] **Step 7: Viết test qua `mcp.call_tool()` thật**

Thêm vào cuối `tests/test_mcp_server.py` (dùng lại fixture `b1_con`/tương đương đã có, hoặc mở rộng theo pattern của nó — đọc code hiện tại của file này trước khi viết, đảm bảo dùng đúng `build_fake_mart` đã cập nhật ở Task 4 Step 1, KHÔNG dùng `full_con` — fixture đó thiếu bảng B2, sẽ khiến test không thể đỏ đúng bài học A2 Task 11/A3 I1/I2):

```python
def test_get_financial_statement_via_mcp_call_tool(b1_con, monkeypatch):
    """Bài học A3 I1 lặp lại nhiều lần trong dự án: crash ở tầng serialize
    JSON của FastMCP xảy ra SAU khi hàm đã return, _safe_tool không bắt
    được, test gọi hàm Python trần không thấy. Phải gọi đúng qua
    mcp.call_tool()."""
    monkeypatch.setattr(server, "conn", lambda: b1_con)

    content = asyncio.run(
        server.mcp.call_tool("get_financial_statement",
                             {"symbol": "AAA", "statement_type": "balance_sheet"})
    )
    payload = json.loads(content[0].text)

    assert "error" not in payload
    assert payload["n_items"] == 2
    assert payload["data_quality"]["has_data"] is True
```

**LƯU Ý cho implementer:** nếu fixture `b1_con` (hoặc tên tương đương đã có trong file lúc triển khai) không tồn tại nữa hoặc đã đổi tên, đọc lại `tests/test_mcp_server.py` hiện tại và dùng đúng fixture/pattern mới nhất — KHÔNG tự tạo fixture riêng trùng lặp.

- [ ] **Step 8: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — tăng đúng 5 test mới so với baseline trước Task 4 (4 test hàm trần + 1 test qua `mcp.call_tool()`), không mất test nào.

- [ ] **Step 9: Commit**

```bash
git add mcp_server/tools.py mcp_server/server.py \
        tests/conftest_mart.py tests/test_mcp_tools.py tests/test_mcp_server.py
git commit -m "feat(b2): tool get_financial_statement

row_seq trả kèm mỗi item để phân biệt các dòng trùng item_id (vd 'cost' ở
balance_sheet, mỗi lần một nhóm tài sản khác nhau) — item_vi mới là tên
hiển thị đúng, không phải item_id/row_seq.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Nghiệm thu đầu-cuối trên dữ liệu thật

**Files:**
- Modify: `scripts/check_mcp_tools.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: toàn bộ Task 1–4.
- Produces: bằng chứng cho 7 tiêu chí hoàn thành trong spec §9.

- [ ] **Step 1: Mở rộng script nghiệm thu**

Trong `scripts/check_mcp_tools.py`, thêm vào hàm `main()` ngay sau lần gọi `get_ownership`, trước `run_sql`:

```python
    ok &= show("get_financial_statement(HPG, balance_sheet)",
               tools.get_financial_statement(con, "HPG", "balance_sheet"))
```

- [ ] **Step 2: Chạy ingest thật trên production, đo thời lượng tăng thêm**

```bash
cd /Users/huynhhuutai/thcoding/vn-stock-daily
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
export VNSTOCK_MIN_INTERVAL=1.05
date; time .venv/bin/python build_warehouse.py --mode monthly; date
```

Expected: chạy dài hơn đáng kể so với trước B2 (thêm ~3× thời lượng
`fetch_financials` cho `period="quarter"`, cộng thêm lần nữa cho
`period="year"` — ước tính vài giờ cho toàn bộ ~1.600 mã). **Nếu tiến
trình bị gián đoạn giữa chừng (đã từng xảy ra ở B1 do mạng/API bên thứ 3
không ổn định), KHÔNG cần lo dữ liệu bị hỏng** — cơ chế `INSERT OR
REPLACE` theo khoá mịn (Task 2) nghĩa là chạy lại từ đầu chỉ ghi đè đúng
những gì đã ghi, không tạo trùng lặp. Có thể xác minh quy mô nhỏ trước
(vài mã) bằng cách gọi trực tiếp `ingest_market.fetch_financial_statements`
+ `warehouse.upsert_financial_statements` như B1 đã làm khi cần verify
nhanh mà không chờ hết job đầy đủ.

Ghi lại số dòng `raw_financial_statement` theo `period_type` vào báo cáo,
cùng thời lượng chạy thật (lệnh `time` ở trên) so với thời lượng `--mode
monthly` trước B2 (B1 final review ghi nhận ~140 phút) — đây là bằng
chứng thật cho rủi ro "thời lượng job tăng ~+84 phút" ở spec §8. Nếu chạy
`--mode weekly` riêng để đo phần `period="quarter"` (không có `period="year"`
ở weekly) thì đối chiếu với thời lượng weekly trước B2 thay vì monthly.

- [ ] **Step 3: Chạy dbt build toàn bộ**

```bash
cd transforms
dbt build --profiles-dir . --no-partial-parse 2>&1 | tail -20
```

Expected: PASS, ERROR=0 (không tăng số ERROR/WARN so với trước B2 — nếu
B1 đã merge, kỳ vọng vẫn giữ đúng `WARN=1` từ `assert_cash_dividend_matches_ratio`
với `error_if='>150'`).

- [ ] **Step 4: Nghiệm thu 10 tool trên dữ liệu thật**

```bash
.venv/bin/python -m scripts.check_mcp_tools
```

Expected: `TẤT CẢ ĐẠT`, exit code 0, cả 10 tool trả dữ liệu (9 cũ + 1 mới).

- [ ] **Step 5: Kiểm tiêu chí #7 — điểm số KHÔNG đổi**

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market')
print(con.execute('''
  select symbol, value_score, quality_score, growth_score,
         dividend_score, safety_score
  from mart_stock_scorecard order by symbol limit 5
''').df().to_string(index=False))
print()
print('tổng số mã:', con.execute('select count(*) from mart_stock_scorecard').fetchone()[0])
"
```

Expected: khớp với giá trị trước B2. B2 chỉ **thêm** model mới, không sửa
model nào đang nuôi `mart_stock_scorecard` — nếu số liệu đổi thì có gì đó
đã lấn phạm vi, **báo controller ngay**.

- [ ] **Step 6: Đối chiếu tay 1 báo cáo thật**

```bash
.venv/bin/python -c "
import duckdb
con = duckdb.connect('md:vn_market')
print(con.execute('''
  select item_vi, period_label, value from stg_financial_statement
  where symbol='HPG' and statement_type='balance_sheet' and item_id='cost'
  order by row_seq, period_label desc
''').df().to_string(index=False))
"
```

Expected: đúng 2 nhóm `item_vi` khác nhau (ví dụ "Nguyên giá TSCĐ hữu
hình" và "Nguyên giá tài sản đầu tư"), mỗi nhóm có 8 dòng theo kỳ. Đối
chiếu vài giá trị với dữ liệu gọi trực tiếp API `Finance("HPG",
"VCI", "quarter").balance_sheet()` để xác nhận khớp — đây là tiêu chí #6.

- [ ] **Step 7: Cập nhật README**

Trong phần "Kiến trúc", đổi dòng mô tả `mcp_server/`:

```markdown
- `mcp_server/` — 10 tool read-only cho luồng hội thoại
```

- [ ] **Step 8: Chạy toàn bộ test lần cuối**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, không giảm so với baseline trước Task 5.

- [ ] **Step 9: Commit**

```bash
git add scripts/check_mcp_tools.py README.md
git commit -m "feat(b2): nghiệm thu 10 tool + cập nhật README

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành B2

| # | Tiêu chí | Cách kiểm | Task |
|---|---|---|---|
| 1 | Vị trí dòng ổn định giữa 2 lần gọi | `scripts/probe_statement_row_stability.py` exit 0 | 1 |
| 2 | Toàn bộ pytest pass, không hỏng test cũ | `pytest tests/ -q` | 5 |
| 3 | `raw_financial_statement` có dữ liệu thật, cả `period_type="quarter"` lẫn `"year"` | Task 3 Step 4, Task 5 Step 2 | 3, 5 |
| 4 | Không dòng nào vi phạm `unique` trên khoá 5 cột | dbt test | 3 |
| 5 | Tool trả đúng `data_quality.has_data=false` cho ≥1 mã đã biết thiếu dữ liệu (TDN hoặc ULG) trên production thật | Gọi tool thật | 5 |
| 6 | Đối chiếu tay ≥1 báo cáo thật khớp giá trị hiển thị trên nguồn | Task 5 Step 6 | 5 |
| 7 | `mart_stock_scorecard` và điểm số **không đổi** | Task 5 Step 5 | 5 |

---

## Ngoài phạm vi (nhắc lại để không hiểu nhầm ở review)

Không đụng `mart_stock_scorecard` · không tính lại `revenue_ttm`/`earnings_ttm` suy ra · không có cột `com_class` ở tầng raw/staging · không làm tầng `intermediate`/mart đối chiếu số suy ra vs số thật (để dành task riêng sau nếu cần) · không xử lý khối ngoại (vẫn chờ nguồn, B1 §1.1).
