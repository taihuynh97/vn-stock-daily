# A1 — Nền dữ liệu cơ bản (raw layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa raw layer của warehouse lên đủ chất lượng và độ rộng để phân tích cơ bản — sửa lỗi sentinel ngân hàng, mở rộng `raw_financial_ratio` 13→50 cột, vá bug ánh xạ hồ sơ doanh nghiệp, thêm `dim_industry` và `raw_index_daily`, và dựng tầng kiểm chứng dữ liệu đầu tiên.

**Architecture:** Giữ nguyên pattern ingestion hiện có (`src/ingest_market.py` gọi vnstock → `src/warehouse.py` upsert vào DuckDB/MotherDuck → `etl_load_log`). Thêm module `src/dq.py` làm cổng kiểm chứng: thiếu cột bắt buộc thì **raise** thay vì trả DataFrame rỗng âm thầm. Mọi thay đổi schema đi qua script migration có guard chống chạy lại.

**Tech Stack:** Python 3.12 · vnstock 4.0.4 (nguồn VCI) · DuckDB 1.5.3 · MotherDuck · pandas · pytest · GitHub Actions

## Global Constraints

- Spec nguồn: `docs/superpowers/specs/2026-08-09-fundamental-analysis-platform-design.md`. Mọi số liệu và tên cột lấy từ đó.
- **Ghim `vnstock==4.0.4`** trong `requirements.txt`. Không nâng lên 4.0.5 trong plan này — schema API có thể đổi.
- Raw layer là **immutable**: không bao giờ `UPDATE` đè lên dữ liệu raw. Sửa dữ liệu chỉ diễn ra ở tầng staging (plan A2).
- Mọi ghi DB phải **idempotent** (`INSERT OR REPLACE` theo khoá tự nhiên) và ghi `etl_load_log`.
- Mọi lời gọi vnstock đi qua `src.ingest._throttle()`.
- Đơn vị: giá cổ phiếu **VNĐ**; `raw_price_daily.value` **triệu VNĐ**; chỉ số **không** nhân ×1000.
- Không đụng `main.py`, `digest.py`, `signals.py`, `screener.py`, `storage.py`, `notify.py`, `.github/workflows/daily.yml`.
- Chạy test: `.venv/bin/python -m pytest tests/ -q`. Toàn bộ 43 test hiện có phải tiếp tục pass.
- Branch làm việc: `feat/fundamental-analysis-platform`.

---

### Task 1: Module kiểm chứng `src/dq.py` + `etl_load_log.rows_rejected`

**Files:**
- Create: `src/dq.py`
- Create: `tests/test_dq.py`
- Modify: `src/warehouse.py` (hàm `log_load`, thêm `_ensure_column`, gọi trong `init_warehouse`)
- Modify: `tests/test_warehouse_read.py` (không sửa nội dung, chỉ chạy lại để xác nhận không vỡ)

**Interfaces:**
- Consumes: không có (task đầu tiên).
- Produces:
  - `src.dq.SchemaError` — exception class
  - `src.dq.assert_columns(df: pd.DataFrame, required: list[str], source: str) -> None`
  - `src.dq.filter_range(df: pd.DataFrame, column: str, low: float, high: float) -> tuple[pd.DataFrame, int]`
  - `src.dq.status_for(rows_loaded: int, rows_rejected: int, threshold: float = 0.05) -> str`
  - `src.warehouse.log_load(con, job_name, table, rows, status, watermark="", notes="", rows_rejected=0)`
  - `src.warehouse._ensure_column(con, table: str, column: str, ddl_type: str) -> None`

- [ ] **Step 1: Viết test thất bại cho `src/dq.py`**

Tạo `tests/test_dq.py`:

```python
import pandas as pd
import pytest

from src import dq


def test_assert_columns_passes_when_all_present():
    df = pd.DataFrame({"a": [1], "b": [2]})
    dq.assert_columns(df, ["a", "b"], "nguon_test")  # không raise


def test_assert_columns_raises_and_names_missing_and_actual():
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(dq.SchemaError) as exc:
        dq.assert_columns(df, ["a", "b", "c"], "nguon_test")
    msg = str(exc.value)
    assert "nguon_test" in msg
    assert "'b'" in msg and "'c'" in msg
    assert "'a'" in msg  # có in ra cột thật để debug


def test_filter_range_drops_out_of_range_keeps_nulls():
    df = pd.DataFrame({"close": [50.0, 20000.0, None, 9_999_999.0]})
    kept, rejected = dq.filter_range(df, "close", 100, 5_000_000)
    assert rejected == 2                    # 50 và 9.999.999 bị loại
    assert len(kept) == 2                   # 20000 và None được giữ
    assert kept["close"].isna().sum() == 1


def test_filter_range_missing_column_is_noop():
    df = pd.DataFrame({"a": [1]})
    kept, rejected = dq.filter_range(df, "khong_ton_tai", 0, 1)
    assert rejected == 0
    assert len(kept) == 1


def test_filter_range_empty_df_is_noop():
    kept, rejected = dq.filter_range(pd.DataFrame(), "close", 0, 1)
    assert rejected == 0
    assert kept.empty


def test_status_for_ok_degraded_empty():
    assert dq.status_for(100, 0) == "ok"
    assert dq.status_for(100, 4) == "ok"        # 3,8% <= 5%
    assert dq.status_for(100, 10) == "degraded" # 9,1% > 5%
    assert dq.status_for(0, 0) == "empty"
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_dq.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.dq'`

- [ ] **Step 3: Viết `src/dq.py`**

```python
"""Tầng 1 kiểm chứng dữ liệu — chặn dữ liệu hỏng ngay tại ingestion.

Nguyên tắc: nguồn thiếu cột bắt buộc thì RAISE để job dừng và báo lỗi,
KHÔNG trả DataFrame rỗng âm thầm. Hành vi trả rỗng của code cũ đã che giấu
bug ánh xạ cột trong _normalize_company suốt nhiều tháng (industry_icb và
exchange NULL 100%) mà không ai biết.
"""
import pandas as pd


class SchemaError(RuntimeError):
    """Nguồn dữ liệu trả về thiếu cột bắt buộc."""


def assert_columns(df: pd.DataFrame, required: list[str], source: str) -> None:
    """Raise SchemaError nếu thiếu bất kỳ cột nào trong `required`."""
    actual = list(df.columns)
    missing = [c for c in required if c not in actual]
    if missing:
        raise SchemaError(
            f"[{source}] thiếu cột bắt buộc {missing}. Cột thật: {actual}"
        )


def filter_range(
    df: pd.DataFrame, column: str, low: float, high: float
) -> tuple[pd.DataFrame, int]:
    """Loại các dòng có `column` nằm ngoài [low, high].

    NULL/NaN được GIỮ LẠI — thiếu dữ liệu khác với dữ liệu sai.
    Trả về (df_còn_lại, số_dòng_bị_loại).
    """
    if df is None or df.empty or column not in df.columns:
        return df, 0
    values = pd.to_numeric(df[column], errors="coerce")
    keep = values.isna() | ((values >= low) & (values <= high))
    return df[keep].reset_index(drop=True), int((~keep).sum())


def status_for(rows_loaded: int, rows_rejected: int, threshold: float = 0.05) -> str:
    """Trạng thái cho etl_load_log: 'ok' | 'degraded' | 'empty'."""
    total = rows_loaded + rows_rejected
    if total == 0:
        return "empty"
    if rows_rejected / total > threshold:
        return "degraded"
    return "ok"
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_dq.py -q`
Expected: PASS — 6 passed

- [ ] **Step 5: Thêm `rows_rejected` vào `etl_load_log`**

Trong `src/warehouse.py`, thêm hàm mới ngay trước `init_warehouse`:

```python
def _ensure_column(con, table: str, column: str, ddl_type: str) -> None:
    """Thêm cột nếu chưa có (migration nhẹ, chạy lại an toàn)."""
    existing = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?",
            [table],
        ).fetchall()
    }
    if column not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
```

Ở **cuối** hàm `init_warehouse(con)`, sau khối `con.execute(""" ... """)`, thêm:

```python
    _ensure_column(con, "etl_load_log", "rows_rejected", "BIGINT")
```

Thay toàn bộ hàm `log_load` (dùng cột có tên, không dùng vị trí — thêm cột sẽ không làm vỡ):

```python
def log_load(con, job_name, table, rows, status, watermark="", notes="",
             rows_rejected=0):
    con.execute(
        """
        INSERT INTO etl_load_log
            (job_name, target_table, run_at, rows_loaded, status,
             watermark, notes, rows_rejected)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [job_name, table, datetime.now(timezone.utc), rows, status,
         watermark, notes, rows_rejected],
    )
```

- [ ] **Step 6: Viết test cho `log_load` với `rows_rejected`**

Thêm vào cuối `tests/test_dq.py`:

```python
import duckdb

from src import warehouse


def test_log_load_records_rows_rejected(tmp_path):
    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    warehouse.init_warehouse(con)
    warehouse.log_load(con, "job_x", "raw_price_daily", 90, "degraded",
                       watermark="2026-08-07", notes="thu", rows_rejected=10)
    row = con.execute(
        "SELECT job_name, rows_loaded, status, rows_rejected FROM etl_load_log"
    ).fetchone()
    con.close()
    assert row == ("job_x", 90, "degraded", 10)


def test_init_warehouse_is_rerunnable_and_adds_column(tmp_path):
    db = str(tmp_path / "t2.duckdb")
    con = duckdb.connect(db)
    warehouse.init_warehouse(con)
    warehouse.init_warehouse(con)   # chạy lần 2 không được lỗi
    cols = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'etl_load_log'"
        ).fetchall()
    }
    con.close()
    assert "rows_rejected" in cols
```

- [ ] **Step 7: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 51 passed (43 cũ + 8 mới)

- [ ] **Step 8: Commit**

```bash
git add src/dq.py src/warehouse.py tests/test_dq.py
git commit -m "feat(dq): module kiểm chứng ingestion + etl_load_log.rows_rejected

Thiếu cột bắt buộc giờ raise SchemaError thay vì trả DataFrame rỗng
âm thầm — hành vi cũ đã che giấu bug ánh xạ cột nhiều tháng.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Mở rộng `raw_financial_ratio` 13 → 50 cột

**Files:**
- Modify: `src/warehouse.py` (hằng số cột, DDL `raw_financial_ratio`, `upsert_financial_ratios`)
- Modify: `src/ingest_market.py` (`_normalize_financials`, `fetch_financials`)
- Modify: `tests/test_ingest_financials.py` (bổ sung test cho cột ngân hàng)

**Interfaces:**
- Consumes: `src.dq.assert_columns` (Task 1).
- Produces:
  - `src.warehouse.RATIO_COMMON`, `RATIO_NONFIN`, `RATIO_BANK` — `list[str]`
  - `src.warehouse.RATIO_NUM_COLS` = tổng 3 list trên, **44 cột số**
  - `src.warehouse.RATIO_ALL_COLS` = `["symbol","year","quarter","period_type","ratio_type"] + RATIO_NUM_COLS`, **49 cột** (cột thứ 50 là `loaded_at` do DB tự điền)
  - `src.ingest_market.fetch_financials(symbols, source="VCI") -> pd.DataFrame` với đúng `RATIO_ALL_COLS`

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_ingest_financials.py`:

```python
from src import warehouse as wh


def _mock_bank_ratio_summary():
    """VCB: cột ngân hàng có giá trị, cột phi tài chính là sentinel 0.0."""
    return pd.DataFrame([{
        "symbol": "VCB", "year": 2026, "quarter": 2, "ratio_type": "RATIO_TTM",
        "market_cap": 5.0e14, "number_of_shares_mkt_cap": 5.5e9,
        "dividend_yield": 0.008, "pe": 15.2, "pb": 2.6, "ps": 5.1,
        "roe": 0.19, "roa": 0.017, "debt_to_equity": 9.8,
        "gross_margin": 0.68, "pre_tax_profit_margin": 0.41,
        "after_tax_profit_margin": 0.33,
        # phi tài chính — sentinel 0.0 do VCI trả
        "roic": 0.0, "current_ratio": 0.0, "ebit_margin": 0.0,
        "quick_ratio": 0.0, "cash_ratio": 0.0, "asset_turnover": 0.0,
        "ev_to_ebitda": 0.0, "price_to_cash_flow": 2.2,
        "fixed_asset_turnover": 0.0, "cash_cycle": 0.0,
        "day_sale_outstanding": 0.0, "days_inventory_outstanding": 0.0,
        "days_payable_outstanding": 0.0, "ebit": 0.0, "ebitda": 0.0,
        "debt_per_equity": 0.0,
        # ngân hàng — giá trị thật
        "net_interest_margin": 0.025, "average_yield_on_earning_assets": 0.053,
        "average_cost_of_financing": -0.029, "non_and_interest_income": 0.33,
        "cir": -0.41, "loans_growth": 0.049, "deposit_growth": 0.046,
        "equity_to_liabilities": 0.064, "equity_to_loans": 0.097,
        "total_equity_total_asset": 0.060, "ldr_loan_deposit_ratio": 0.79,
        "npl": 0.0115, "loans_loss_reserve_to_loans": 0.016,
        "provision_to_outstanding_loans": -0.011, "car": 0.12,
        "casa_ratio": 0.35,
    }])


def test_ratio_column_constants_have_expected_sizes():
    assert len(wh.RATIO_COMMON) == 13
    assert len(wh.RATIO_NONFIN) == 15
    assert len(wh.RATIO_BANK) == 16
    assert len(wh.RATIO_NUM_COLS) == 44
    assert len(wh.RATIO_ALL_COLS) == 49
    # không được trùng cột giữa các nhóm
    assert len(set(wh.RATIO_NUM_COLS)) == 44
    # hai cột trùng lặp đã xác minh phải bị loại
    assert "financial_leverage" not in wh.RATIO_NUM_COLS
    assert "cost_to_income" not in wh.RATIO_NUM_COLS
    # cột đòn bẩy thứ hai (khác debt_to_equity) phải được giữ
    assert "debt_per_equity" in wh.RATIO_NONFIN


def test_fetch_financials_keeps_bank_metrics():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_bank_ratio_summary()
        result = fetch_financials(["VCB"])
    row = result.iloc[0]
    assert row["net_interest_margin"] == pytest.approx(0.025)
    assert row["npl"] == pytest.approx(0.0115)
    assert row["cir"] == pytest.approx(-0.41)     # giữ nguyên dấu ở raw
    assert row["casa_ratio"] == pytest.approx(0.35)
    assert row["number_of_shares_mkt_cap"] == pytest.approx(5.5e9)
    assert row["ratio_type"] == "RATIO_TTM"


def test_fetch_financials_returns_all_ratio_columns():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_bank_ratio_summary()
        result = fetch_financials(["VCB"])
    assert list(result.columns) == wh.RATIO_ALL_COLS


def test_fetch_financials_missing_year_column_raises():
    bad = pd.DataFrame([{"symbol": "AAA", "quarter": 1, "pe": 10.0}])
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = bad
        with pytest.raises(Exception) as exc:
            fetch_financials(["AAA"])
    assert "year" in str(exc.value)


def test_upsert_financial_ratios_roundtrip(tmp_path):
    import duckdb
    con = duckdb.connect(str(tmp_path / "fin.duckdb"))
    wh.init_warehouse(con)
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.ratio_summary.return_value = _mock_bank_ratio_summary()
        df = fetch_financials(["VCB"])
    n = wh.upsert_financial_ratios(con, df)
    stored = con.execute(
        "SELECT symbol, npl, car, loaded_at IS NOT NULL "
        "FROM raw_financial_ratio"
    ).fetchone()
    con.close()
    assert n == 1
    assert stored[0] == "VCB"
    assert stored[1] == pytest.approx(0.0115)
    assert stored[2] == pytest.approx(0.12)
    assert stored[3] is True
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_financials.py -q`
Expected: FAIL — `AttributeError: module 'src.warehouse' has no attribute 'RATIO_COMMON'`

- [ ] **Step 3: Thêm hằng số cột + DDL vào `src/warehouse.py`**

Thêm ngay sau `DEFAULT_DB = ...`:

```python
# --- Cột raw_financial_ratio (nguồn: Company.ratio_summary, 61 cột) ---
# Loại bỏ có chủ đích: financial_leverage (≡ debt_to_equity, xác minh HPG),
# cost_to_income (≡ cir, xác minh VCB), owners_equity (ngữ nghĩa không rõ),
# ratio_ttm_id / ratio_year_id / organ_code / year_report / equity /
# loans_loss_reserves_to_np_ls / nob66 / nob69 / nob70 / bsb113.
# Nhóm COMMON = có giá trị THẬT ở cả ngân hàng lẫn phi tài chính (xác minh
# VCB vs HPG). Nhóm NONFIN/BANK = bên còn lại trả sentinel 0.0 hoặc None.
RATIO_COMMON = [
    "market_cap", "number_of_shares_mkt_cap", "dividend_yield",
    "pe", "pb", "ps", "roe", "roa", "debt_to_equity",
    "gross_margin", "pre_tax_profit_margin", "after_tax_profit_margin",
    "price_to_cash_flow",   # VCB 2,20 — giá trị thật, KHÔNG phải sentinel
]
RATIO_NONFIN = [
    "roic", "ev_to_ebitda",
    "current_ratio", "quick_ratio", "cash_ratio", "ebit_margin",
    "asset_turnover", "fixed_asset_turnover", "cash_cycle",
    "day_sale_outstanding", "days_inventory_outstanding",
    "days_payable_outstanding", "ebit", "ebitda", "debt_per_equity",
]
RATIO_BANK = [
    "net_interest_margin", "average_yield_on_earning_assets",
    "average_cost_of_financing", "non_and_interest_income", "cir",
    "loans_growth", "deposit_growth", "equity_to_liabilities",
    "equity_to_loans", "total_equity_total_asset", "ldr_loan_deposit_ratio",
    "npl", "loans_loss_reserve_to_loans", "provision_to_outstanding_loans",
    "car", "casa_ratio",
]
RATIO_NUM_COLS = RATIO_COMMON + RATIO_NONFIN + RATIO_BANK          # 44
RATIO_ALL_COLS = [
    "symbol", "year", "quarter", "period_type", "ratio_type",
] + RATIO_NUM_COLS                                                  # 49
```

Trong `init_warehouse`, **thay** khối `CREATE TABLE IF NOT EXISTS raw_financial_ratio (...)` hiện tại bằng cách tách nó ra khỏi chuỗi SQL lớn và tạo riêng ngay sau khối `con.execute(""" ... """)`:

```python
    ratio_cols_ddl = ",\n            ".join(f"{c} DOUBLE" for c in RATIO_NUM_COLS)
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS raw_financial_ratio (
            symbol      VARCHAR,
            year        INTEGER,
            quarter     INTEGER,
            period_type VARCHAR,
            ratio_type  VARCHAR,
            {ratio_cols_ddl},
            loaded_at   TIMESTAMP,
            PRIMARY KEY (symbol, year, quarter)
        );
        """
    )
```

(Xoá khối `CREATE TABLE IF NOT EXISTS raw_financial_ratio (...)` cũ trong chuỗi SQL lớn — nếu để lại, `IF NOT EXISTS` sẽ tạo bảng 13 cột trước và khối mới không có tác dụng.)

Thay `upsert_financial_ratios`:

```python
def upsert_financial_ratios(con, df) -> int:
    if df is None or df.empty:
        return 0
    cols = ", ".join(RATIO_ALL_COLS)
    con.register("df_fin", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_financial_ratio ({cols}, loaded_at)
        SELECT {cols}, now() FROM df_fin;
        """
    )
    con.unregister("df_fin")
    return len(df)
```

- [ ] **Step 4: Cập nhật `_normalize_financials` trong `src/ingest_market.py`**

Thêm import ở đầu file, cạnh `from . import ingest`:

```python
from . import ingest, warehouse, dq
```

Xoá hằng số `_RATIO_NUM_COLS` cũ và **thay** hàm `_normalize_financials`:

```python
def _normalize_financials(df, symbol) -> pd.DataFrame:
    dq.assert_columns(df, ["year", "quarter"], f"ratio_summary({symbol})")

    out = pd.DataFrame({
        "symbol":  symbol.upper().strip(),
        "year":    pd.to_numeric(df["year"], errors="coerce"),
        "quarter": pd.to_numeric(df["quarter"], errors="coerce"),
    })
    out["period_type"] = out["quarter"].apply(lambda q: "year" if q == 5 else "quarter")
    if "ratio_type" in df.columns:
        out["ratio_type"] = df["ratio_type"].astype(str).values
    else:
        out["ratio_type"] = out["quarter"].apply(
            lambda q: "RATIO_YEAR" if q == 5 else "RATIO_TTM"
        )
    for col in warehouse.RATIO_NUM_COLS:
        out[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else None

    out = out.dropna(subset=["year", "quarter"]).reset_index(drop=True)
    return out[warehouse.RATIO_ALL_COLS]
```

Trong `fetch_financials`, bỏ `try/except` bao quanh `_normalize_financials` nếu có — `SchemaError` phải nổi lên. Thân vòng lặp giữ nguyên; chỉ `Company(...).ratio_summary()` được bọc `try/except` (lỗi mạng của một mã không được làm vỡ job).

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_ingest_financials.py -q`
Expected: PASS

- [ ] **Step 6: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 56 passed

- [ ] **Step 7: Kiểm chứng với nguồn thật (1 mã ngân hàng, 1 mã phi tài chính)**

```bash
set -a && source .env && set +a && .venv/bin/python -c "
from src.ingest_market import fetch_financials
df = fetch_financials(['VCB','HPG'])
print(df.shape)
print(df[df.symbol=='VCB'][['symbol','year','quarter','net_interest_margin','npl','cir','roic']].tail(3))
print(df[df.symbol=='HPG'][['symbol','year','quarter','roic','current_ratio','npl']].tail(3))
"
```

Expected: `df.shape` có 49 cột; VCB có `net_interest_margin`/`npl`/`cir` khác 0 và `roic = 0`; HPG có `roic`/`current_ratio` khác 0 và `npl = 0`. Sentinel `0.0` **vẫn còn ở raw** — đúng thiết kế, sẽ khử ở staging (plan A2).

- [ ] **Step 8: Commit**

```bash
git add src/warehouse.py src/ingest_market.py tests/test_ingest_financials.py
git commit -m "feat(warehouse): raw_financial_ratio 13 -> 50 cột

Giữ đủ khối chỉ tiêu ngân hàng (NIM, NPL, CIR, CAR, CASA, LDR...) và
các chỉ tiêu phi tài chính bị bỏ sót. Loại 2 cột trùng lặp đã xác minh:
financial_leverage (= debt_to_equity), cost_to_income (= cir).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Sửa bug ánh xạ `_normalize_company` + mở rộng `raw_company_info`

**Files:**
- Modify: `src/warehouse.py` (DDL `raw_company_info`, `upsert_company_info`, thêm `update_symbol_exchanges`)
- Modify: `src/ingest_market.py` (`_normalize_company`)
- Modify: `tests/test_ingest_financials.py` (test `fetch_company_info` hiện có dùng tên cột sai — phải viết lại)
- Modify: `build_warehouse.py` (gọi `update_symbol_exchanges` ở mode monthly)

**Interfaces:**
- Consumes: `src.dq.assert_columns` (Task 1).
- Produces:
  - `src.warehouse.COMPANY_COLS` — `list[str]`, 20 cột (chưa kể `loaded_at`)
  - `src.ingest_market.fetch_company_info(symbols, source="VCI") -> pd.DataFrame` với đúng `COMPANY_COLS`
  - `src.warehouse.update_symbol_exchanges(con) -> int` — đồng bộ `dim_symbols.exchange` từ `raw_company_info.exchange`

- [ ] **Step 1: Viết test thất bại**

Trong `tests/test_ingest_financials.py`, **thay** hàm `_mock_company_overview` và 3 test `fetch_company_info` hiện có (chúng dùng tên cột `exchange`/`industry_icb_name2` không tồn tại trong API thật) bằng:

```python
def _mock_company_overview():
    """Cột thật của Company.overview() — xác minh bằng HPG ngày 2026-08-09."""
    return pd.DataFrame([{
        "symbol": "HPG",
        "organ_name": "Công ty Cổ phần Tập đoàn Hòa Phát",
        "organ_short_name": "Hòa Phát",
        "com_group_code": "HOSE",
        "com_type_code": "CT",
        "is_bank": False,
        "icb_code_lv2": "1700",
        "icb_code_lv4": "1757",
        "sector": "Basic Resources",
        "market_cap": 1.4e14,
        "issue_share": 7.7e9,
        "free_float_percentage": 0.55,
        "foreigner_percentage": 0.22,
        "maximum_foreign_percentage": 0.49,
        "state_percentage": 0.0,
        "average_match_value1_month": 3.0e11,
        "average_match_volume1_month": 1.3e7,
        "highest_price1_year": 29000.0,
        "lowest_price1_year": 19500.0,
        "listing_date": "2007-11-15",
    }])


def test_fetch_company_info_maps_real_columns():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        result = fetch_company_info(["HPG"])
    row = result.iloc[0]
    assert row["symbol"] == "HPG"
    assert row["exchange"] == "HOSE"           # từ com_group_code, KHÔNG phải NULL
    assert row["icb_code_lv2"] == "1700"       # từ icb_code_lv2, KHÔNG phải NULL
    assert row["icb_code_lv4"] == "1757"
    assert row["com_type_code"] == "CT"
    assert bool(row["is_bank"]) is False
    assert row["free_float_percentage"] == pytest.approx(0.55)
    assert row["avg_match_value_1m"] == pytest.approx(3.0e11)
    assert str(row["listed_date"]) == "2007-11-15"


def test_fetch_company_info_bank_flag_true():
    df = _mock_company_overview()
    df.loc[0, "symbol"] = "VCB"
    df.loc[0, "is_bank"] = True
    df.loc[0, "sector"] = "Banks"
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = df
        result = fetch_company_info(["VCB"])
    assert bool(result.iloc[0]["is_bank"]) is True


def test_fetch_company_info_returns_all_company_cols():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        result = fetch_company_info(["HPG"])
    assert list(result.columns) == wh.COMPANY_COLS


def test_fetch_company_info_missing_symbol_column_raises():
    bad = pd.DataFrame([{"organ_name": "X"}])
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = bad
        with pytest.raises(Exception) as exc:
            fetch_company_info(["HPG"])
    assert "com_group_code" in str(exc.value) or "icb_code_lv2" in str(exc.value)


def test_fetch_company_info_empty_on_exception():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.side_effect = Exception("API down")
        result = fetch_company_info(["HPG"])
    assert result.empty


def test_update_symbol_exchanges_fills_dim_symbols(tmp_path):
    import duckdb
    con = duckdb.connect(str(tmp_path / "ci.duckdb"))
    wh.init_warehouse(con)
    con.execute(
        "INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, "
        "first_seen, last_seen) VALUES ('HPG', NULL, 'HP', TRUE, "
        "DATE '2026-01-01', DATE '2026-08-07')"
    )
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        info = fetch_company_info(["HPG"])
    wh.upsert_company_info(con, info)
    n = wh.update_symbol_exchanges(con)
    got = con.execute("SELECT exchange FROM dim_symbols WHERE symbol='HPG'").fetchone()[0]
    con.close()
    assert n == 1
    assert got == "HOSE"
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_financials.py -q -k company`
Expected: FAIL — `AttributeError: module 'src.warehouse' has no attribute 'COMPANY_COLS'`

- [ ] **Step 3: Cập nhật `src/warehouse.py`**

Thêm sau khối `RATIO_ALL_COLS`:

```python
# --- Cột raw_company_info (nguồn: Company.overview, 37 cột) ---
# Không lấy: analyst, target_price, upside_to_target_percent,
# projected_tsr_percentage, rating — là khuyến nghị của bên thứ ba, không
# phải dữ kiện; đưa vào sẽ khiến agent trích dẫn nhầm thành phân tích riêng.
COMPANY_COLS = [
    "symbol", "company_name", "short_name", "exchange", "com_type_code",
    "is_bank", "icb_code_lv2", "icb_code_lv4", "sector",
    "market_cap", "issue_share", "free_float_percentage",
    "foreigner_percentage", "maximum_foreign_percentage", "state_percentage",
    "avg_match_value_1m", "avg_match_volume_1m",
    "highest_price_1y", "lowest_price_1y", "listed_date",
]
```

Xoá khối `CREATE TABLE IF NOT EXISTS raw_company_info (...)` cũ trong chuỗi SQL lớn của `init_warehouse`, và thêm sau khối tạo `raw_financial_ratio`:

```python
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_company_info (
            symbol                     VARCHAR PRIMARY KEY,
            company_name               VARCHAR,
            short_name                 VARCHAR,
            exchange                   VARCHAR,
            com_type_code              VARCHAR,
            is_bank                    BOOLEAN,
            icb_code_lv2               VARCHAR,
            icb_code_lv4               VARCHAR,
            sector                     VARCHAR,
            market_cap                 DOUBLE,
            issue_share                DOUBLE,
            free_float_percentage      DOUBLE,
            foreigner_percentage       DOUBLE,
            maximum_foreign_percentage DOUBLE,
            state_percentage           DOUBLE,
            avg_match_value_1m         DOUBLE,
            avg_match_volume_1m        DOUBLE,
            highest_price_1y           DOUBLE,
            lowest_price_1y            DOUBLE,
            listed_date                DATE,
            loaded_at                  TIMESTAMP
        );
        """
    )
```

Thay `upsert_company_info` và thêm `update_symbol_exchanges`:

```python
def upsert_company_info(con, df) -> int:
    if df is None or df.empty:
        return 0
    cols = ", ".join(COMPANY_COLS)
    con.register("df_ci", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_company_info ({cols}, loaded_at)
        SELECT {cols}, now() FROM df_ci;
        """
    )
    con.unregister("df_ci")
    return len(df)


def update_symbol_exchanges(con) -> int:
    """Đồng bộ dim_symbols.exchange từ raw_company_info (đang NULL 100%)."""
    n = con.execute(
        """
        SELECT count(*) FROM dim_symbols d JOIN raw_company_info c USING (symbol)
        WHERE c.exchange IS NOT NULL
          AND (d.exchange IS DISTINCT FROM c.exchange)
        """
    ).fetchone()[0]
    con.execute(
        """
        UPDATE dim_symbols AS d
        SET exchange = c.exchange
        FROM raw_company_info AS c
        WHERE d.symbol = c.symbol AND c.exchange IS NOT NULL
        """
    )
    return n
```

- [ ] **Step 4: Viết lại `_normalize_company` trong `src/ingest_market.py`**

Thay toàn bộ hàm (dùng tên cột chính xác, không dò mềm — đã biết cột thật):

```python
_COMPANY_REQUIRED = ["symbol", "com_group_code", "icb_code_lv2"]


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y"}


def _to_date_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.to_datetime(v).date().isoformat()
    except Exception:
        return None


def _normalize_company(df, symbol) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    dq.assert_columns(df, _COMPANY_REQUIRED, f"Company.overview({symbol})")
    row = df.iloc[0]

    def num(col):
        return pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0] \
            if col in df.columns else None

    def text(col):
        v = row.get(col) if col in df.columns else None
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return str(v).strip()

    return pd.DataFrame([{
        "symbol":                     symbol.upper().strip(),
        "company_name":               text("organ_name"),
        "short_name":                 text("organ_short_name"),
        "exchange":                   (text("com_group_code") or "").upper() or None,
        "com_type_code":              text("com_type_code"),
        "is_bank":                    _to_bool(row.get("is_bank")),
        "icb_code_lv2":               text("icb_code_lv2"),
        "icb_code_lv4":               text("icb_code_lv4"),
        "sector":                     text("sector"),
        "market_cap":                 num("market_cap"),
        "issue_share":                num("issue_share"),
        "free_float_percentage":      num("free_float_percentage"),
        "foreigner_percentage":       num("foreigner_percentage"),
        "maximum_foreign_percentage": num("maximum_foreign_percentage"),
        "state_percentage":           num("state_percentage"),
        "avg_match_value_1m":         num("average_match_value1_month"),
        "avg_match_volume_1m":        num("average_match_volume1_month"),
        "highest_price_1y":           num("highest_price1_year"),
        "lowest_price_1y":            num("lowest_price1_year"),
        "listed_date":                _to_date_str(row.get("listing_date")),
    }])[warehouse.COMPANY_COLS]
```

Trong `fetch_company_info`, giữ `try/except` **chỉ** quanh `Company(...).overview()`; `_normalize_company` gọi ngoài `try` để `SchemaError` nổi lên.

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_ingest_financials.py -q`
Expected: PASS

- [ ] **Step 6: Gọi `update_symbol_exchanges` trong `build_warehouse.py`**

Trong khối `if args.mode == "monthly":`, ngay sau dòng `print(f"raw_company_info: {n_info} mã")`, thêm:

```python
        n_exch = warehouse.update_symbol_exchanges(con)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_symbols", n_exch,
                           "ok" if n_exch else "empty", watermark=run_date,
                           notes="sync exchange tu raw_company_info")
        print(f"dim_symbols.exchange: cập nhật {n_exch} mã")
```

- [ ] **Step 7: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 60 passed

- [ ] **Step 8: Kiểm chứng với nguồn thật**

```bash
set -a && source .env && set +a && .venv/bin/python -c "
from src.ingest_market import fetch_company_info
df = fetch_company_info(['HPG','VCB'])
print(df[['symbol','exchange','com_type_code','is_bank','icb_code_lv2','icb_code_lv4','sector','listed_date']].to_string())
"
```

Expected: cả hai mã có `exchange = 'HOSE'`, `icb_code_lv2` khác None, VCB có `is_bank = True`.

- [ ] **Step 9: Commit**

```bash
git add src/warehouse.py src/ingest_market.py tests/test_ingest_financials.py build_warehouse.py
git commit -m "fix(ingest): sửa bug ánh xạ cột hồ sơ DN + mở rộng raw_company_info

_normalize_company dò tên cột 'industry_icb'/'exchange' vốn không tồn tại
trong Company.overview() -> NULL 100% cho 1.587 mã. Cột thật là
icb_code_lv2/lv4 và com_group_code. Bổ sung is_bank, com_type_code,
free float, sở hữu nước ngoài/nhà nước, thanh khoản 1 tháng.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Bảng phân ngành `dim_industry`

**Files:**
- Modify: `src/warehouse.py` (DDL `dim_industry`, `upsert_industries`)
- Modify: `src/ingest_market.py` (`fetch_industries_icb`)
- Create: `tests/test_ingest_industry.py`
- Modify: `build_warehouse.py` (mode monthly)

**Interfaces:**
- Consumes: `src.dq.assert_columns` (Task 1).
- Produces:
  - `src.ingest_market.fetch_industries_icb(source="VCI") -> pd.DataFrame` với cột `[icb_code, icb_name, en_icb_name, level]`
  - `src.warehouse.upsert_industries(con, df) -> int`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_ingest_industry.py`:

```python
import duckdb
import pandas as pd
import pytest
from unittest.mock import patch

from src import warehouse as wh
from src.ingest_market import fetch_industries_icb


def _mock_icb():
    """Cột thật của Listing.industries_icb() — xác minh ngày 2026-08-09."""
    return pd.DataFrame([
        {"icb_name": "Dầu khí", "en_icb_name": "Oil & Gas",
         "icb_code": "0001", "level": 1},
        {"icb_name": "Sản xuất Dầu khí", "en_icb_name": "Oil & Gas Producers",
         "icb_code": "0530", "level": 3},
        {"icb_name": "Tổ hợp Dầu khí", "en_icb_name": "Integrated Oil & Gas",
         "icb_code": "0537", "level": 4},
    ])


def test_fetch_industries_icb_schema():
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = _mock_icb()
        df = fetch_industries_icb()
    assert list(df.columns) == ["icb_code", "icb_name", "en_icb_name", "level"]
    assert len(df) == 3
    assert df.iloc[0]["icb_name"] == "Dầu khí"     # giữ tiếng Việt
    assert df.iloc[0]["level"] == 1


def test_fetch_industries_icb_raises_on_missing_column():
    bad = pd.DataFrame([{"icb_name": "X", "level": 1}])
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = bad
        with pytest.raises(Exception) as exc:
            fetch_industries_icb()
    assert "icb_code" in str(exc.value)


def test_fetch_industries_icb_empty_on_api_error():
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.side_effect = Exception("down")
        df = fetch_industries_icb()
    assert df.empty


def test_upsert_industries_is_idempotent(tmp_path):
    con = duckdb.connect(str(tmp_path / "ind.duckdb"))
    wh.init_warehouse(con)
    with patch("src.ingest_market.Listing") as MockL, \
         patch("src.ingest_market.ingest._throttle"):
        MockL.return_value.industries_icb.return_value = _mock_icb()
        df = fetch_industries_icb()
    assert wh.upsert_industries(con, df) == 3
    assert wh.upsert_industries(con, df) == 3          # chạy lại
    total = con.execute("SELECT count(*) FROM dim_industry").fetchone()[0]
    name = con.execute(
        "SELECT icb_name FROM dim_industry WHERE icb_code='0537'"
    ).fetchone()[0]
    con.close()
    assert total == 3                                   # không nhân đôi
    assert name == "Tổ hợp Dầu khí"
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_industry.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_industries_icb'`

- [ ] **Step 3: Thêm bảng `dim_industry` vào `src/warehouse.py`**

Trong `init_warehouse`, thêm vào chuỗi SQL lớn:

```sql
        CREATE TABLE IF NOT EXISTS dim_industry (
            icb_code    VARCHAR PRIMARY KEY,
            icb_name    VARCHAR,
            en_icb_name VARCHAR,
            level       INTEGER,
            loaded_at   TIMESTAMP
        );
```

Thêm hàm:

```python
def upsert_industries(con, df) -> int:
    if df is None or df.empty:
        return 0
    con.register("df_ind", df)
    con.execute(
        """
        INSERT OR REPLACE INTO dim_industry
            (icb_code, icb_name, en_icb_name, level, loaded_at)
        SELECT icb_code, icb_name, en_icb_name, level, now() FROM df_ind;
        """
    )
    con.unregister("df_ind")
    return len(df)
```

- [ ] **Step 4: Thêm `fetch_industries_icb` vào `src/ingest_market.py`**

```python
def fetch_industries_icb(source: str = "VCI") -> pd.DataFrame:
    """Bảng phân ngành ICB 4 cấp (bảng tĩnh, ~177 dòng, tên ngành tiếng Việt)."""
    ingest._throttle()
    try:
        df = Listing(source=source).industries_icb()
    except Exception as e:
        print(f"[industries_icb] {e}")
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()

    df.columns = [str(c).lower() for c in df.columns]
    dq.assert_columns(df, ["icb_code", "icb_name", "level"], "Listing.industries_icb")

    out = pd.DataFrame({
        "icb_code":    df["icb_code"].astype(str).str.strip(),
        "icb_name":    df["icb_name"].astype(str).str.strip(),
        "en_icb_name": (df["en_icb_name"].astype(str).str.strip()
                        if "en_icb_name" in df.columns else None),
        "level":       pd.to_numeric(df["level"], errors="coerce").astype("Int64"),
    })
    return out.drop_duplicates("icb_code").reset_index(drop=True)
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_ingest_industry.py -q`
Expected: PASS — 4 passed

- [ ] **Step 6: Gọi trong `build_warehouse.py` (mode monthly)**

Trong khối `if args.mode == "monthly":`, **trước** phần company info, thêm:

```python
        ind = ingest_market.fetch_industries_icb(source)
        n_ind = warehouse.upsert_industries(con, ind)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_industry", n_ind,
                           "ok" if n_ind else "empty", watermark=run_date)
        print(f"dim_industry: {n_ind} ngành ICB")
```

- [ ] **Step 7: Chạy toàn bộ test + kiểm chứng nguồn thật**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 64 passed

```bash
set -a && source .env && set +a && .venv/bin/python -c "
from src.ingest_market import fetch_industries_icb
df = fetch_industries_icb()
print(df.shape)
print(df.groupby('level').size())
"
```

Expected: `(177, 4)` và có đủ 4 cấp.

- [ ] **Step 8: Commit**

```bash
git add src/warehouse.py src/ingest_market.py tests/test_ingest_industry.py build_warehouse.py
git commit -m "feat(warehouse): thêm dim_industry (phân ngành ICB 4 cấp)

Nguồn Listing.industries_icb() — 177 dòng, tên ngành tiếng Việt.
Nền cho so sánh định giá trong cùng ngành ở tầng mart.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Bảng chỉ số `raw_index_daily`

**Files:**
- Modify: `src/warehouse.py` (DDL `raw_index_daily`, `upsert_index_prices`)
- Modify: `src/ingest_market.py` (`fetch_index_history`)
- Create: `tests/test_ingest_index.py`
- Modify: `config/warehouse.yml` (danh sách chỉ số)
- Modify: `build_warehouse.py` (mọi mode)
- Create: `scripts/backfill_index_history.py`

**Interfaces:**
- Consumes: `src.dq.assert_columns`, `src.dq.filter_range` (Task 1).
- Produces:
  - `src.ingest_market.fetch_index_history(index_code: str, start: str, end: str, source="VCI") -> pd.DataFrame` với cột `[index_code, trade_date, open, high, low, close, volume]`
  - `src.warehouse.upsert_index_prices(con, df) -> int`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_ingest_index.py`:

```python
import duckdb
import pandas as pd
import pytest
from unittest.mock import patch

from src import warehouse as wh
from src.ingest_market import fetch_index_history


def _mock_index_history():
    """Quote.history('VNINDEX') — giá trị KHÔNG nhân 1000."""
    return pd.DataFrame([
        {"time": "2026-08-06", "open": 1784.65, "high": 1784.65,
         "low": 1762.34, "close": 1764.78, "volume": 579915937},
        {"time": "2026-08-07", "open": 1761.23, "high": 1774.61,
         "low": 1756.07, "close": 1768.06, "volume": 660590646},
    ])


def test_fetch_index_history_does_not_scale_by_1000():
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = _mock_index_history()
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert df.iloc[-1]["close"] == pytest.approx(1768.06)   # KHÔNG phải 1_768_060
    assert df.iloc[-1]["open"] == pytest.approx(1761.23)


def test_fetch_index_history_schema():
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = _mock_index_history()
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert list(df.columns) == [
        "index_code", "trade_date", "open", "high", "low", "close", "volume"
    ]
    assert set(df["index_code"]) == {"VNINDEX"}
    assert df.iloc[0]["trade_date"] == "2026-08-06"


def test_fetch_index_history_raises_on_missing_close():
    bad = pd.DataFrame([{"time": "2026-08-07", "open": 1.0}])
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = bad
        with pytest.raises(Exception) as exc:
            fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert "close" in str(exc.value)


def test_fetch_index_history_empty_on_api_error():
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.side_effect = Exception("down")
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert df.empty


def test_upsert_index_prices_idempotent(tmp_path):
    con = duckdb.connect(str(tmp_path / "idx.duckdb"))
    wh.init_warehouse(con)
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = _mock_index_history()
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert wh.upsert_index_prices(con, df) == 2
    assert wh.upsert_index_prices(con, df) == 2
    total = con.execute("SELECT count(*) FROM raw_index_daily").fetchone()[0]
    close = con.execute(
        "SELECT close FROM raw_index_daily "
        "WHERE index_code='VNINDEX' AND trade_date=DATE '2026-08-07'"
    ).fetchone()[0]
    con.close()
    assert total == 2
    assert close == pytest.approx(1768.06)
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_index.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_index_history'`

- [ ] **Step 3: Thêm bảng vào `src/warehouse.py`**

Trong chuỗi SQL của `init_warehouse`:

```sql
        CREATE TABLE IF NOT EXISTS raw_index_daily (
            index_code VARCHAR,
            trade_date DATE,
            open       DOUBLE,
            high       DOUBLE,
            low        DOUBLE,
            close      DOUBLE,
            volume     BIGINT,
            loaded_at  TIMESTAMP,
            PRIMARY KEY (index_code, trade_date)
        );
```

Thêm hàm:

```python
def upsert_index_prices(con, df) -> int:
    if df is None or df.empty:
        return 0
    con.register("df_idx", df)
    con.execute(
        """
        INSERT OR REPLACE INTO raw_index_daily
            (index_code, trade_date, open, high, low, close, volume, loaded_at)
        SELECT index_code, trade_date, open, high, low, close, volume, now()
        FROM df_idx;
        """
    )
    con.unregister("df_idx")
    return len(df)
```

- [ ] **Step 4: Thêm `fetch_index_history` vào `src/ingest_market.py`**

```python
def fetch_index_history(index_code: str, start: str, end: str,
                        source: str = "VCI") -> pd.DataFrame:
    """Lịch sử chỉ số (VNINDEX/VN30/HNXINDEX).

    KHÁC fetch_history_one: chỉ số KHÔNG nhân ×1000. Xác minh 2026-08-07:
    Quote.history('VNINDEX').close = 1768.06 — đã đúng đơn vị.
    """
    ingest._throttle()
    try:
        df = Quote(symbol=index_code, source=source).history(
            start=start, end=end, interval="1D"
        )
    except Exception as e:
        print(f"[index] {index_code}: {e}")
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()

    df.columns = [str(c).lower() for c in df.columns]
    dq.assert_columns(df, ["close"], f"Quote.history({index_code})")
    date_col = _find(list(df.columns), "trading_date", "time", "date")
    if date_col is None:
        raise dq.SchemaError(
            f"[Quote.history({index_code})] không tìm thấy cột ngày. "
            f"Cột thật: {list(df.columns)}"
        )

    out = pd.DataFrame({
        "index_code": index_code.upper().strip(),
        "trade_date": pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d"),
        "open":   _col(df, _find(list(df.columns), "open")),
        "high":   _col(df, _find(list(df.columns), "high")),
        "low":    _col(df, _find(list(df.columns), "low")),
        "close":  pd.to_numeric(df["close"], errors="coerce"),
        "volume": _col(df, _find(list(df.columns), "volume")),
    })
    out = out.dropna(subset=["close"])
    out, rejected = dq.filter_range(out, "close", 1, 100_000)
    if rejected:
        print(f"[index] {index_code}: loại {rejected} dòng close ngoài [1, 100.000]")
    return out.drop_duplicates(["index_code", "trade_date"]).reset_index(drop=True)
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_ingest_index.py -q`
Expected: PASS — 5 passed

- [ ] **Step 6: Thêm cấu hình + gọi trong `build_warehouse.py`**

Thêm vào cuối `config/warehouse.yml`:

```yaml
# Chỉ số thị trường thu hằng ngày. Lưu ý: giá trị chỉ số KHÔNG nhân 1000.
indices:
  - VNINDEX
  - VN30
  - HNXINDEX
```

Trong `build_warehouse.py`, ngay sau khối giá EOD (mục 2), thêm:

```python
    # 2b) Chỉ số thị trường — mọi mode
    if ingest_market.is_trading_day(date.today()):
        n_idx = 0
        for code in cfg.get("indices", []):
            idx_df = ingest_market.fetch_index_history(code, run_date, run_date, source)
            n_idx += warehouse.upsert_index_prices(con, idx_df)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_index_daily", n_idx,
                           "ok" if n_idx else "empty", watermark=run_date)
        print(f"raw_index_daily: {n_idx} dòng")
```

- [ ] **Step 7: Viết script backfill chỉ số 10 năm**

Tạo `scripts/backfill_index_history.py`:

```python
"""Backfill lịch sử chỉ số (một lần). Chỉ 3 call API nên chạy rất nhanh.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.backfill_index_history --years 10
"""
import argparse
from datetime import date, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
JOB_NAME = "backfill_index_history"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=10)
    args = parser.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=args.years * 366)).isoformat()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    total = 0
    for code in cfg.get("indices", []):
        df = ingest_market.fetch_index_history(code, start, end, source)
        n = warehouse.upsert_index_prices(con, df)
        total += n
        print(f"{code}: {n} phiên ({start} → {end})")

    warehouse.log_load(con, JOB_NAME, "raw_index_daily", total,
                       "ok" if total else "empty", watermark=end)
    print(con.execute(
        "SELECT index_code, count(*) phien, min(trade_date), max(trade_date) "
        "FROM raw_index_daily GROUP BY 1 ORDER BY 1"
    ).df().to_string())
    con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 69 passed

- [ ] **Step 9: Commit**

```bash
git add src/warehouse.py src/ingest_market.py tests/test_ingest_index.py \
        config/warehouse.yml build_warehouse.py scripts/backfill_index_history.py
git commit -m "feat(warehouse): thêm raw_index_daily (VNINDEX, VN30, HNXINDEX)

fetch_index_history tách riêng khỏi fetch_history_one vì chỉ số KHÔNG
nhân x1000 (xác minh VNINDEX close = 1768.06 phiên 2026-08-07).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Migration + nạp lại dữ liệu thật + script đối chiếu chéo

**Files:**
- Create: `scripts/migrate_financial_ratio_v2.py`
- Create: `scripts/reconcile_warehouse.py`
- Create: `tests/test_reconcile.py`
- Modify: `requirements.txt` (ghim `vnstock==4.0.4`)
- Modify: `src/ingest.py` (throttle cấu hình được qua env)

**Interfaces:**
- Consumes: mọi hàm từ Task 1–5.
- Produces:
  - `scripts.reconcile_warehouse.check_layer_counts(con) -> list[dict]`
  - `scripts.reconcile_warehouse.check_against_source(con, symbols: list[str]) -> list[dict]`

- [ ] **Step 1: Cho phép cấu hình throttle qua biến môi trường**

Trong `src/ingest.py`, thay:

```python
_MIN_CALL_INTERVAL = 3.1  # giây
```

bằng:

```python
import os as _os

# Guest tier: 20 req/phút → cần ≥3s. Community (API key): 60 req/phút → ~1,05s.
# Đặt VNSTOCK_MIN_INTERVAL=1.05 khi có key Community để nạp lại nhanh hơn 3 lần.
_MIN_CALL_INTERVAL = float(_os.getenv("VNSTOCK_MIN_INTERVAL", "3.1"))
```

Ghim phiên bản trong `requirements.txt`: đổi dòng `vnstock>=4.0,<5.0` thành `vnstock==4.0.4`.

- [ ] **Step 2: Viết script migration**

Tạo `scripts/migrate_financial_ratio_v2.py`:

```python
"""Migration: raw_financial_ratio 13 cột → 50 cột (bao gồm chỉ tiêu ngân hàng).

Raw layer tái tạo được từ API nên không chuyển đổi dữ liệu: đổi tên bảng cũ
thành backup, tạo bảng mới, nạp lại toàn bộ, đối chiếu, rồi mới xoá backup.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    export VNSTOCK_MIN_INTERVAL=1.05      # nếu có key Community
    python -m scripts.migrate_financial_ratio_v2 --step rename
    python -m scripts.migrate_financial_ratio_v2 --step reload
    python -m scripts.migrate_financial_ratio_v2 --step verify
    python -m scripts.migrate_financial_ratio_v2 --step cleanup
"""
import argparse

from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()

JOB_NAME = "migration_financial_ratio_v3_50cols"
BACKUP = "raw_financial_ratio_v1_backup"


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
        [name],
    ).fetchone()[0])


def step_rename(con):
    if _table_exists(con, BACKUP):
        print(f"{BACKUP} đã tồn tại — bỏ qua bước rename.")
        return
    n = con.execute("SELECT count(*) FROM raw_financial_ratio").fetchone()[0]
    con.execute(f"ALTER TABLE raw_financial_ratio RENAME TO {BACKUP}")
    warehouse.init_warehouse(con)
    print(f"Đã đổi tên bảng cũ ({n} dòng) → {BACKUP}, tạo bảng mới 50 cột.")


def step_reload(con):
    symbols = warehouse.get_active_symbols(con)
    print(f"Nạp lại tỷ số cho {len(symbols)} mã...")
    total = 0
    batch = 50
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        df = ingest_market.fetch_financials(chunk)
        total += warehouse.upsert_financial_ratios(con, df)
        print(f"  {i + len(chunk)}/{len(symbols)} mã — tổng {total} dòng")
    warehouse.log_load(con, JOB_NAME, "raw_financial_ratio", total,
                       "ok" if total else "empty",
                       notes="reload 50 cot tu ratio_summary")
    print(f"Xong: {total} dòng.")


def step_verify(con) -> bool:
    old_rows, old_syms = con.execute(
        f"SELECT count(*), count(DISTINCT symbol) FROM {BACKUP}"
    ).fetchone()
    new_rows, new_syms = con.execute(
        "SELECT count(*), count(DISTINCT symbol) FROM raw_financial_ratio"
    ).fetchone()
    banks_ok = con.execute(
        """
        SELECT count(*) FROM raw_financial_ratio f
        JOIN raw_company_info c USING (symbol)
        WHERE c.is_bank AND f.net_interest_margin IS NOT NULL
          AND f.net_interest_margin <> 0
        """
    ).fetchone()[0]

    print(f"cũ : {old_rows} dòng / {old_syms} mã")
    print(f"mới: {new_rows} dòng / {new_syms} mã")
    print(f"dòng ngân hàng có net_interest_margin thật: {banks_ok}")

    ok = new_syms >= old_syms * 0.95 and new_rows >= old_rows and banks_ok > 0
    print("ĐẠT" if ok else "KHÔNG ĐẠT — không được xoá backup")
    return ok


def step_cleanup(con):
    if not step_verify(con):
        print("Bỏ qua cleanup vì verify không đạt.")
        return
    con.execute(f"DROP TABLE {BACKUP}")
    print(f"Đã xoá {BACKUP}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step",
                        choices=["rename", "reload", "verify", "cleanup"],
                        required=True)
    args = parser.parse_args()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)
    {"rename": step_rename, "reload": step_reload,
     "verify": step_verify, "cleanup": step_cleanup}[args.step](con)
    con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Viết test thất bại cho script đối chiếu**

Tạo `tests/test_reconcile.py`:

```python
import duckdb
import pytest

from src import warehouse as wh
from scripts import reconcile_warehouse as rw


def _seed(tmp_path):
    con = duckdb.connect(str(tmp_path / "rec.duckdb"))
    wh.init_warehouse(con)
    con.execute(
        "INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, "
        "first_seen, last_seen) VALUES "
        "('AAA','HOSE','A',TRUE,DATE '2026-01-01',DATE '2026-08-07'),"
        "('BBB','HNX','B',TRUE,DATE '2026-01-01',DATE '2026-08-07')"
    )
    con.execute(
        "INSERT INTO raw_price_daily (symbol, trade_date, open, high, low, "
        "close, volume, value, loaded_at) VALUES "
        "('AAA',DATE '2026-08-07',1,1,1,20000,1000,20.0,now())"
    )
    return con


def test_check_layer_counts_flags_missing_prices(tmp_path):
    con = _seed(tmp_path)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["dim_symbols"]["value"] == 2
    assert by_name["raw_price_daily_symbols"]["value"] == 1
    assert by_name["raw_price_daily_symbols"]["ok"] is False   # 1/2 = 50% < 95%


def test_check_layer_counts_passes_when_complete(tmp_path):
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO raw_price_daily (symbol, trade_date, open, high, low, "
        "close, volume, value, loaded_at) VALUES "
        "('BBB',DATE '2026-08-07',1,1,1,15000,900,15.0,now())"
    )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["raw_price_daily_symbols"]["ok"] is True


def test_check_layer_counts_returns_expected_checks(tmp_path):
    con = _seed(tmp_path)
    names = {r["check"] for r in rw.check_layer_counts(con)}
    con.close()
    assert {"dim_symbols", "raw_price_daily_symbols",
            "raw_company_info_symbols", "raw_financial_ratio_symbols",
            "dim_industry_rows", "raw_index_daily_codes"} <= names
```

- [ ] **Step 4: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.reconcile_warehouse'`

- [ ] **Step 5: Viết `scripts/reconcile_warehouse.py`**

```python
"""Tầng 4 kiểm chứng — đối chiếu chéo giữa các layer và với API nguồn.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.reconcile_warehouse            # đủ 2 phần
    python -m scripts.reconcile_warehouse --no-api   # chỉ đếm layer

Exit code 1 nếu có bất kỳ kiểm tra nào không đạt.
"""
import argparse
import random
import sys

import pandas as pd
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()

MIN_COVERAGE = 0.95      # tỉ lệ mã tối thiểu so với dim_symbols
MAX_DRIFT = 0.01         # sai lệch tối đa khi đối chiếu với API gốc


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def check_layer_counts(con) -> list[dict]:
    """Đếm số mã/số dòng qua từng bảng, so với dim_symbols."""
    total = _scalar(con, "SELECT count(*) FROM dim_symbols WHERE is_active")
    rows = [{"check": "dim_symbols", "value": total, "expected": total, "ok": total > 0}]

    for name, sql in [
        ("raw_price_daily_symbols",
         "SELECT count(DISTINCT symbol) FROM raw_price_daily"),
        ("raw_company_info_symbols",
         "SELECT count(*) FROM raw_company_info"),
        ("raw_financial_ratio_symbols",
         "SELECT count(DISTINCT symbol) FROM raw_financial_ratio"),
    ]:
        v = _scalar(con, sql)
        rows.append({"check": name, "value": v, "expected": total,
                     "ok": total > 0 and v >= total * MIN_COVERAGE})

    ind = _scalar(con, "SELECT count(*) FROM dim_industry")
    rows.append({"check": "dim_industry_rows", "value": ind, "expected": 100,
                 "ok": ind >= 100})

    idx = _scalar(con, "SELECT count(DISTINCT index_code) FROM raw_index_daily")
    rows.append({"check": "raw_index_daily_codes", "value": idx, "expected": 3,
                 "ok": idx >= 3})

    exch = _scalar(con,
                   "SELECT count(*) FROM dim_symbols WHERE exchange IS NOT NULL")
    rows.append({"check": "dim_symbols_with_exchange", "value": exch,
                 "expected": total, "ok": total > 0 and exch >= total * MIN_COVERAGE})

    return rows


def check_against_source(con, symbols: list[str]) -> list[dict]:
    """Gọi lại API gốc cho vài mã, so kỳ tỷ số gần nhất với warehouse."""
    out = []
    for sym in symbols:
        wh_row = con.execute(
            "SELECT year, quarter, pe, roe FROM raw_financial_ratio "
            "WHERE symbol = ? ORDER BY year DESC, quarter DESC LIMIT 1",
            [sym],
        ).fetchone()
        if wh_row is None:
            out.append({"symbol": sym, "check": "ratio_latest",
                        "detail": "không có trong warehouse", "ok": False})
            continue

        api = ingest_market.fetch_financials([sym])
        if api.empty:
            out.append({"symbol": sym, "check": "ratio_latest",
                        "detail": "API không trả dữ liệu", "ok": False})
            continue

        api = api.sort_values(["year", "quarter"]).iloc[-1]
        drift = []
        for i, col in enumerate(["pe", "roe"], start=2):
            a, b = wh_row[i], api[col]
            if a is None or pd.isna(b):
                continue
            denom = abs(b) if abs(b) > 1e-9 else 1.0
            drift.append(abs(a - b) / denom)
        worst = max(drift) if drift else 0.0
        out.append({
            "symbol": sym, "check": "ratio_latest",
            "detail": f"kỳ warehouse {wh_row[0]}Q{wh_row[1]}, lệch tối đa {worst:.4f}",
            "ok": worst <= MAX_DRIFT,
        })
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--sample", type=int, default=5)
    args = parser.parse_args()

    con = warehouse.get_conn()
    results = check_layer_counts(con)

    if not args.no_api:
        pool = warehouse.get_active_symbols(con)
        sample = random.sample(pool, min(args.sample, len(pool)))
        print(f"Đối chiếu API gốc cho: {', '.join(sample)}")
        results += check_against_source(con, sample)

    con.close()
    print(pd.DataFrame(results).to_string(index=False))
    failed = [r for r in results if not r["ok"]]
    if failed:
        print(f"\n{len(failed)} kiểm tra KHÔNG ĐẠT.")
        sys.exit(1)
    print("\nTất cả kiểm tra ĐẠT.")


if __name__ == "__main__":
    main()
```

Tạo file rỗng `scripts/__init__.py` nếu chưa có (để `python -m scripts.*` và import trong test hoạt động):

```bash
touch scripts/__init__.py
```

- [ ] **Step 6: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -q`
Expected: PASS — 3 passed

- [ ] **Step 7: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 72 passed

- [ ] **Step 8: Commit code trước khi chạy migration thật**

```bash
git add scripts/ tests/test_reconcile.py requirements.txt src/ingest.py
git commit -m "feat(scripts): migration raw_financial_ratio v2 + đối chiếu chéo

Ghim vnstock==4.0.4. Throttle cấu hình qua VNSTOCK_MIN_INTERVAL.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Chạy migration thật trên MotherDuck (LOCAL, không qua GitHub Actions)**

> Chạy local vì bước reload mất ~28–82 phút tuỳ throttle. GitHub Actions giới hạn 6 giờ/job nên vẫn đủ, nhưng chạy local dễ theo dõi và dừng lại hơn.

```bash
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
export VNSTOCK_MIN_INTERVAL=1.05        # bỏ dòng này nếu không có key Community

.venv/bin/python -m scripts.migrate_financial_ratio_v2 --step rename
.venv/bin/python -m scripts.migrate_financial_ratio_v2 --step reload
.venv/bin/python -m scripts.migrate_financial_ratio_v2 --step verify
```

Expected ở bước `verify`: `mới` ≥ 1.500 mã, số dòng ≥ 48.103, và `dòng ngân hàng có net_interest_margin thật` > 0 → in `ĐẠT`.

**Nếu KHÔNG ĐẠT: dừng lại, không chạy `cleanup`.** Bảng `raw_financial_ratio_v1_backup` vẫn còn nguyên để khôi phục.

- [ ] **Step 10: Nạp hồ sơ DN + ngành + chỉ số thật**

```bash
.venv/bin/python build_warehouse.py --mode monthly
.venv/bin/python -m scripts.backfill_index_history --years 10
```

Expected: `dim_industry: 177 ngành ICB`; `raw_company_info: ~1.587 mã`; `dim_symbols.exchange: cập nhật ~1.587 mã`; mỗi chỉ số ≥ 2.000 phiên.

- [ ] **Step 11: Chạy đối chiếu chéo**

```bash
.venv/bin/python -m scripts.reconcile_warehouse --sample 5
```

Expected: mọi dòng `ok = True`, exit code 0.

- [ ] **Step 12: Kiểm tra tiêu chí nghiệm thu của plan này**

```bash
.venv/bin/python -c "
import os, duckdb
os.environ['motherduck_token'] = os.environ['MOTHERDUCK_TOKEN']
con = duckdb.connect('md:vn_market')
print('cột raw_financial_ratio:', con.execute(\"select count(*) from information_schema.columns where table_name='raw_financial_ratio'\").fetchone()[0])
print('mã có tỷ số:', con.execute('select count(distinct symbol) from raw_financial_ratio').fetchone()[0])
print('ngân hàng có NIM/NPL/CIR:', con.execute('''
  select count(distinct f.symbol) from raw_financial_ratio f join raw_company_info c using(symbol)
  where c.is_bank and f.net_interest_margin is not null and f.npl is not null and f.cir is not null
''').fetchone()[0])
print('company_info có exchange & icb:', con.execute('select count(*) filter (where exchange is not null), count(*) filter (where icb_code_lv2 is not null), count(*) from raw_company_info').fetchone())
print('dim_symbols có exchange:', con.execute('select count(*) filter (where exchange is not null), count(*) from dim_symbols').fetchone())
print('dim_industry:', con.execute('select count(*), count(distinct level) from dim_industry').fetchone())
print('chỉ số:', con.execute('select index_code, count(*), min(trade_date), max(trade_date), max(close) from raw_index_daily group by 1 order by 1').df().to_string())
"
```

Expected:
- `cột raw_financial_ratio` = 50
- `mã có tỷ số` ≥ 1.500
- `ngân hàng có NIM/NPL/CIR` ≥ 25
- `company_info có exchange & icb` ≥ 95% của 1.587
- `dim_symbols có exchange` ≥ 95% của 1.598
- `dim_industry` = (177, 4)
- mỗi chỉ số ≥ 2.000 phiên, `max(close)` của VNINDEX < 5.000 (**nếu ≥ 5.000 nghĩa là bị nhân nhầm ×1000**)

- [ ] **Step 13: Dọn bảng backup và commit trạng thái**

Chỉ chạy khi Step 12 đạt hết:

```bash
.venv/bin/python -m scripts.migrate_financial_ratio_v2 --step cleanup
git commit --allow-empty -m "chore: hoàn tất nạp lại warehouse raw layer (A1)

raw_financial_ratio 50 cột / >=1500 mã; raw_company_info có exchange +
icb_code; dim_industry 177 dòng; raw_index_daily 3 chỉ số x >=2000 phiên.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Cập nhật GitHub Actions

**Files:**
- Modify: `.github/workflows/warehouse.yml`
- Modify: `.github/workflows/warehouse-weekly.yml`
- Modify: `.github/workflows/warehouse-monthly.yml`

**Interfaces:**
- Consumes: `scripts/reconcile_warehouse.py` (Task 6), `build_warehouse.py` (Task 3–5).
- Produces: không có interface code; chỉ thay đổi vận hành.

- [ ] **Step 1: Thêm `VNSTOCK_MIN_INTERVAL` vào cả 3 workflow**

Trong khối `env:` của mỗi workflow, thêm dòng:

```yaml
          VNSTOCK_MIN_INTERVAL: "1.05"
```

- [ ] **Step 2: Thêm bước đối chiếu chéo vào workflow monthly**

Trong `.github/workflows/warehouse-monthly.yml`, sau bước `Warehouse monthly`, thêm:

```yaml
      - name: Đối chiếu chéo warehouse
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
          VNSTOCK_API_KEY: ${{ secrets.VNSTOCK_API_KEY }}
          VNSTOCK_MIN_INTERVAL: "1.05"
        run: python -m scripts.reconcile_warehouse --sample 5
```

- [ ] **Step 3: Chạy thử workflow bằng tay**

Vào tab Actions trên GitHub, chạy `warehouse-daily` qua **Run workflow**.
Expected: job xanh; log có dòng `raw_index_daily: 3 dòng`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/
git commit -m "ci: thêm throttle Community + bước đối chiếu chéo hằng tháng

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành plan A1

| # | Tiêu chí | Cách kiểm tra |
|---|---|---|
| 1 | 72 test pytest pass | `.venv/bin/python -m pytest tests/ -q` |
| 2 | `raw_financial_ratio` có đúng 50 cột, ≥ 1.500 mã | Task 6 Step 12 |
| 3 | ≥ 25 ngân hàng có `net_interest_margin`, `npl`, `cir` khác NULL | Task 6 Step 12 |
| 4 | `raw_company_info.exchange` và `.icb_code_lv2` khác NULL cho ≥ 95% mã | Task 6 Step 12 |
| 5 | `dim_symbols.exchange` khác NULL cho ≥ 95% mã | Task 6 Step 12 |
| 6 | `dim_industry` có 177 dòng, đủ 4 cấp | Task 6 Step 12 |
| 7 | `raw_index_daily` có 3 chỉ số × ≥ 2.000 phiên, VNINDEX `close` < 5.000 | Task 6 Step 12 |
| 8 | `reconcile_warehouse.py` exit code 0 | Task 6 Step 11 |
| 9 | Pipeline bản tin cũ vẫn chạy | `.venv/bin/python main.py` |

Sau khi đạt hết: chuyển sang plan **A2 — dbt marts & bộ chấm điểm**.
