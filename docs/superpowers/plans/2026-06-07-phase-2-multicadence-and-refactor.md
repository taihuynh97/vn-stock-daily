# Phase 2 — Multi-cadence Ingestion + Consumer Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add weekly financial ratios and monthly company info ingestion (2A), then refactor the news pipeline to read price history from warehouse instead of calling the API per symbol (2B).

**Architecture:** 2A adds two new raw tables and two new fetch functions in `ingest_market.py`, then extends `build_warehouse.py` with a `--mode` flag to orchestrate daily/weekly/monthly cadences. 2B adds `warehoPuse.read_price_history()` and modifies `ingest.fetch_history` to try warehouse first (fast) and fall back to API only when data is missing — no changes to signals/screener/digest/notify logic.

**Tech Stack:** Python 3.12, DuckDB/MotherDuck, vnstock 4.x (`Finance.ratio`, `Company.overview`), GitHub Actions cron, pytest + unittest.mock

**Constraint:** NEVER modify `main.py`, `signals.py`, `digest.py`, `notify.py`, `storage.py`. Only `ingest.py` and `screener.py` may be touched in 2B, and only to change data source, not logic.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `src/warehouse.py` | Modify | + `raw_financial_ratio` table, + `raw_company_info` table, + `upsert_financial_ratios()`, + `upsert_company_info()`, + `read_price_history()` |
| `src/ingest_market.py` | Modify | + `fetch_financials()`, + `fetch_company_info()`, + `_normalize_financials()`, + `_normalize_company()`, new module-level `_printed_fin_cols`, `_printed_info_cols` |
| `build_warehouse.py` | Modify | + `--mode {daily,weekly,monthly}` argument; weekly runs financials; monthly runs company_info too |
| `.github/workflows/warehouse-weekly.yml` | Create | Cron Saturday 08:30 UTC, runs `python build_warehouse.py --mode weekly` |
| `.github/workflows/warehouse-monthly.yml` | Create | Cron 1st of month 09:00 UTC, runs `python build_warehouse.py --mode monthly` |
| `src/ingest.py` | Modify (2B only) | `fetch_history` tries warehouse first; module-level lazy connection |
| `tests/test_warehouse_phase2a.py` | Create | Tests for new tables and upsert functions |
| `tests/test_ingest_financials.py` | Create | Tests for fetch_financials, fetch_company_info (mocked vnstock) |
| `tests/test_warehouse_read.py` | Create | Tests for read_price_history |
| `tests/test_ingest_warehouse_fallback.py` | Create | Tests for fetch_history warehouse-first logic |

---

## PART 2A — Multi-cadence Ingestion

---

### Task 1: DB tables and upsert functions

**Files:**
- Modify: `src/warehouse.py`
- Test: `tests/test_warehouse_phase2a.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_warehouse_phase2a.py`:

```python
import pandas as pd
import duckdb
import pytest
from src.warehouse import (
    init_warehouse,
    upsert_financial_ratios,
    upsert_company_info,
)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def test_init_creates_financial_ratio_table(con):
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "raw_financial_ratio" in tables


def test_init_creates_company_info_table(con):
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "raw_company_info" in tables


def test_upsert_financial_ratios_returns_row_count(con):
    df = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 10.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    n = upsert_financial_ratios(con, df)
    assert n == 1


def test_upsert_financial_ratios_idempotent(con):
    df = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 10.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    upsert_financial_ratios(con, df)
    upsert_financial_ratios(con, df)
    count = con.execute("SELECT COUNT(*) FROM raw_financial_ratio").fetchone()[0]
    assert count == 1


def test_upsert_financial_ratios_updates_pe(con):
    df1 = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 10.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    df2 = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 12.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    upsert_financial_ratios(con, df1)
    upsert_financial_ratios(con, df2)
    pe = con.execute(
        "SELECT pe FROM raw_financial_ratio WHERE symbol='AAA' AND period='2023'"
    ).fetchone()[0]
    assert pe == 12.0


def test_upsert_company_info_returns_row_count(con):
    df = pd.DataFrame([{
        "symbol": "AAA", "company_name": "An Phat Bioplastics",
        "exchange": "HOSE", "industry_icb": "Industrials",
        "sector": "Chemicals", "listed_date": "2010-01-15",
    }])
    n = upsert_company_info(con, df)
    assert n == 1


def test_upsert_company_info_overwrites_name(con):
    df1 = pd.DataFrame([{
        "symbol": "AAA", "company_name": "Old Name",
        "exchange": "HOSE", "industry_icb": "Industrials",
        "sector": "Chemicals", "listed_date": "2010-01-15",
    }])
    df2 = pd.DataFrame([{
        "symbol": "AAA", "company_name": "New Name",
        "exchange": "HOSE", "industry_icb": "Industrials",
        "sector": "Chemicals", "listed_date": "2010-01-15",
    }])
    upsert_company_info(con, df1)
    upsert_company_info(con, df2)
    name = con.execute(
        "SELECT company_name FROM raw_company_info WHERE symbol='AAA'"
    ).fetchone()[0]
    assert name == "New Name"


def test_upsert_empty_returns_zero(con):
    assert upsert_financial_ratios(con, pd.DataFrame()) == 0
    assert upsert_company_info(con, pd.DataFrame()) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_warehouse_phase2a.py -v
```

Expected: FAIL with `ImportError: cannot import name 'upsert_financial_ratios'`

- [ ] **Step 3: Implement tables and upsert functions in warehouse.py**

In `src/warehouse.py`, add to `init_warehouse()` after existing `CREATE TABLE IF NOT EXISTS etl_load_log`:

```python
        CREATE TABLE IF NOT EXISTS raw_financial_ratio (
            symbol      VARCHAR,
            period      VARCHAR,
            period_type VARCHAR,
            pe          DOUBLE,
            pb          DOUBLE,
            roe         DOUBLE,
            roa         DOUBLE,
            eps         DOUBLE,
            loaded_at   TIMESTAMP,
            PRIMARY KEY (symbol, period, period_type)
        );
        CREATE TABLE IF NOT EXISTS raw_company_info (
            symbol        VARCHAR PRIMARY KEY,
            company_name  VARCHAR,
            exchange      VARCHAR,
            industry_icb  VARCHAR,
            sector        VARCHAR,
            listed_date   DATE,
            loaded_at     TIMESTAMP
        );
```

Add these two functions anywhere after `upsert_prices`:

```python
def upsert_financial_ratios(con, df) -> int:
    if df is None or df.empty:
        return 0
    con.register("df_fin", df)
    con.execute(
        """
        INSERT OR REPLACE INTO raw_financial_ratio
        SELECT symbol, period, period_type, pe, pb, roe, roa, eps, now()
        FROM df_fin;
        """
    )
    con.unregister("df_fin")
    return len(df)


def upsert_company_info(con, df) -> int:
    if df is None or df.empty:
        return 0
    con.register("df_ci", df)
    con.execute(
        """
        INSERT OR REPLACE INTO raw_company_info
        SELECT symbol, company_name, exchange, industry_icb, sector,
               TRY_CAST(listed_date AS DATE), now()
        FROM df_ci;
        """
    )
    con.unregister("df_ci")
    return len(df)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_warehouse_phase2a.py -v
```

Expected: 8/8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/warehouse.py tests/test_warehouse_phase2a.py
git commit -m "feat: add raw_financial_ratio and raw_company_info tables with upsert functions"
```

---

### Task 2: fetch_financials() in ingest_market.py

**Files:**
- Modify: `src/ingest_market.py`
- Test: `tests/test_ingest_financials.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ingest_financials.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from src.ingest_market import fetch_financials
import src.ingest_market as im


@pytest.fixture(autouse=True)
def reset_module_state():
    im._printed_fin_cols = False
    yield
    im._printed_fin_cols = False


def _mock_finance_ratio():
    """DataFrame mimicking Finance.ratio() with yearreport and known cols."""
    return pd.DataFrame([
        {"yearreport": "2023", "pe": 10.0, "pb": 1.5,
         "roe": 0.15, "roa": 0.08, "eps": 2000.0},
        {"yearreport": "2022", "pe": 9.5,  "pb": 1.4,
         "roe": 0.14, "roa": 0.07, "eps": 1800.0},
    ])


def test_fetch_financials_returns_expected_schema():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.return_value = _mock_finance_ratio()
        result = fetch_financials(["AAA"])
    assert set(result.columns) >= {"symbol", "period", "period_type", "pe", "pb", "roe"}
    assert result.iloc[0]["symbol"] == "AAA"
    assert result.iloc[0]["period_type"] == "year"


def test_fetch_financials_multiple_periods():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.return_value = _mock_finance_ratio()
        result = fetch_financials(["AAA"])
    assert len(result) == 2
    assert set(result["period"].tolist()) == {"2023", "2022"}


def test_fetch_financials_empty_on_exception():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.side_effect = Exception("API error")
        result = fetch_financials(["AAA"])
    assert result.empty


def test_fetch_financials_empty_on_empty_response():
    with patch("src.ingest_market.Finance") as MockFin, \
         patch("src.ingest_market.ingest._throttle"):
        MockFin.return_value.ratio.return_value = pd.DataFrame()
        result = fetch_financials(["AAA"])
    assert result.empty


def test_fetch_financials_skips_failed_symbol_continues():
    """One bad symbol should not prevent good symbols from returning data."""
    def side_effect_factory(symbol, source, period):
        mock = MagicMock()
        if symbol == "BAD":
            mock.ratio.side_effect = Exception("fail")
        else:
            mock.ratio.return_value = _mock_finance_ratio()
        return mock

    with patch("src.ingest_market.Finance", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_financials(["BAD", "AAA"])
    assert len(result) > 0
    assert all(result["symbol"] == "AAA")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ingest_financials.py -v
```

Expected: FAIL with `ImportError: cannot import name 'fetch_financials'`

- [ ] **Step 3: Implement fetch_financials in ingest_market.py**

At the top of `src/ingest_market.py`, add these imports after the existing ones:

```python
from vnstock.api.financial import Finance
from vnstock.api.company import Company
```

Add these module-level flags (after `_printed_hist_cols = False`):

```python
_printed_fin_cols = False
_printed_info_cols = False
```

Add these functions at the end of `src/ingest_market.py`:

```python
def fetch_financials(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    """Financial ratios per symbol via Finance.ratio. Returns DataFrame for raw_financial_ratio."""
    global _printed_fin_cols
    frames = []
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Finance(symbol=symbol, source=source, period="year").ratio()
        except Exception as e:
            print(f"[financials] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [
            '.'.join(map(str, c)).lower() if isinstance(c, tuple) else str(c).lower()
            for c in df.columns
        ]
        if not _printed_fin_cols:
            print(f"[financials] cột thật ({symbol}): {list(df.columns)}")
            _printed_fin_cols = True
        row = _normalize_financials(df, symbol)
        if row is not None and not row.empty:
            frames.append(row)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_financials(df, symbol) -> pd.DataFrame:
    cols = list(df.columns)
    period_col = _find(cols, "yearreport", "year", "period", "quarter", "reportdate")
    pe_col = _find(cols, "pe", "p/e", "price_to_earn")
    pb_col = _find(cols, "pb", "p/b", "price_to_book")
    roe_col = _find(cols, "roe")
    roa_col = _find(cols, "roa")
    eps_col = _find(cols, "eps")

    if period_col is None:
        print(f"[financials] {symbol}: không tìm thấy cột period. Cột có: {cols}")
        return pd.DataFrame()

    out = pd.DataFrame({
        "symbol":      symbol.upper().strip(),
        "period":      df[period_col].astype(str),
        "period_type": "year",
        "pe":          pd.to_numeric(df[pe_col],  errors="coerce") if pe_col  else None,
        "pb":          pd.to_numeric(df[pb_col],  errors="coerce") if pb_col  else None,
        "roe":         pd.to_numeric(df[roe_col], errors="coerce") if roe_col else None,
        "roa":         pd.to_numeric(df[roa_col], errors="coerce") if roa_col else None,
        "eps":         pd.to_numeric(df[eps_col], errors="coerce") if eps_col else None,
    })
    return out.dropna(subset=["period"]).reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_ingest_financials.py -v
```

Expected: 5/5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingest_market.py tests/test_ingest_financials.py
git commit -m "feat: add fetch_financials with Finance.ratio soft-mapping"
```

---

### Task 3: fetch_company_info() in ingest_market.py

**Files:**
- Modify: `src/ingest_market.py`
- Append to: `tests/test_ingest_financials.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingest_financials.py`:

```python
from src.ingest_market import fetch_company_info


@pytest.fixture(autouse=True)
def reset_info_state():
    im._printed_info_cols = False
    yield
    im._printed_info_cols = False


def _mock_company_overview():
    return pd.DataFrame([{
        "organ_name": "An Phat Bioplastics",
        "exchange": "HOSE",
        "industry_icb_name2": "Industrials",
        "sector": "Chemicals",
        "listing_date": "2010-01-15",
    }])


def test_fetch_company_info_returns_expected_schema():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.return_value = _mock_company_overview()
        result = fetch_company_info(["AAA"])
    assert set(result.columns) >= {"symbol", "company_name", "exchange", "industry_icb"}
    assert result.iloc[0]["symbol"] == "AAA"


def test_fetch_company_info_empty_on_exception():
    with patch("src.ingest_market.Company") as MockCo, \
         patch("src.ingest_market.ingest._throttle"):
        MockCo.return_value.overview.side_effect = Exception("API down")
        result = fetch_company_info(["AAA"])
    assert result.empty


def test_fetch_company_info_skips_failed_continues():
    call_count = [0]
    def factory(symbol, source):
        mock = MagicMock()
        call_count[0] += 1
        if call_count[0] == 1:
            mock.overview.side_effect = Exception("fail")
        else:
            mock.overview.return_value = _mock_company_overview()
        return mock

    with patch("src.ingest_market.Company", side_effect=factory), \
         patch("src.ingest_market.ingest._throttle"):
        result = fetch_company_info(["BAD", "AAA"])
    assert len(result) == 1
    assert result.iloc[0]["symbol"] == "AAA"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ingest_financials.py::test_fetch_company_info_returns_expected_schema -v
```

Expected: FAIL with `ImportError: cannot import name 'fetch_company_info'`

- [ ] **Step 3: Implement fetch_company_info in ingest_market.py**

Append to `src/ingest_market.py`:

```python
def fetch_company_info(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    """Company overview per symbol via Company.overview. Returns DataFrame for raw_company_info."""
    global _printed_info_cols
    frames = []
    for symbol in symbols:
        ingest._throttle()
        try:
            df = Company(symbol=symbol, source=source).overview()
        except Exception as e:
            print(f"[company_info] {symbol}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        df.columns = [str(c).lower() for c in df.columns]
        if not _printed_info_cols:
            print(f"[company_info] cột thật ({symbol}): {list(df.columns)}")
            _printed_info_cols = True
        row = _normalize_company(df, symbol)
        if row is not None and not row.empty:
            frames.append(row)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_company(df, symbol) -> pd.DataFrame:
    cols = list(df.columns)
    name_col    = _find(cols, "organ_name", "company_name", "short_name", "company")
    exch_col    = _find(cols, "exchange", "comgroupcode", "board")
    industry_col = _find(cols, "industry_icb", "industry", "icb_name", "ngành")
    sector_col  = _find(cols, "sector", "sector_name")
    listed_col  = _find(cols, "listing_date", "listed_date", "ipo")

    if df.empty:
        return pd.DataFrame()
    row = df.iloc[0]

    listed_val = None
    if listed_col and pd.notna(row[listed_col]):
        try:
            listed_val = pd.to_datetime(row[listed_col]).date().isoformat()
        except Exception:
            listed_val = None

    return pd.DataFrame([{
        "symbol":       symbol.upper().strip(),
        "company_name": str(row[name_col]).strip()    if name_col     else None,
        "exchange":     str(row[exch_col]).upper()    if exch_col     else None,
        "industry_icb": str(row[industry_col]).strip() if industry_col else None,
        "sector":       str(row[sector_col]).strip()  if sector_col   else None,
        "listed_date":  listed_val,
    }])
```

- [ ] **Step 4: Run all ingest financials tests**

```bash
python -m pytest tests/test_ingest_financials.py -v
```

Expected: 8/8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/ingest_market.py tests/test_ingest_financials.py
git commit -m "feat: add fetch_company_info with Company.overview soft-mapping"
```

---

### Task 4: build_warehouse.py --mode argument

**Files:**
- Modify: `build_warehouse.py`

No unit tests (entry point). Integration verified by running with `--mode weekly` locally.

- [ ] **Step 1: Add --mode argument and branching logic**

Replace the current `main()` body in `build_warehouse.py` with:

```python
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

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")
    run_date = date.today().isoformat()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    # 1) Refresh danh sách mã
    uni = ingest_market.refresh_universe(cfg["exchanges"], source)
    n_sym = warehouse.upsert_symbols(con, uni, run_date)
    warehouse.log_load(con, f"warehouse_{args.mode}", "dim_symbols", n_sym,
                       "ok" if n_sym else "empty")
    print(f"dim_symbols: {n_sym} mã ({', '.join(cfg['exchanges'])})")

    # 2) Giá EOD toàn thị trường (bulk) — mọi mode đều có
    symbols = warehouse.get_active_symbols(con)
    if not symbols:
        print("Chưa có mã nào trong dim_symbols — dừng.")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", 0,
                           "skipped", notes="no symbols")
        con.close()
        return

    prices = ingest_market.fetch_eod_prices(symbols, source, cfg.get("price_board_batch", 50))
    n_px = warehouse.upsert_prices(con, prices)
    warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", n_px,
                       "ok" if n_px else "empty", watermark=run_date)
    print(f"raw_price_daily: {n_px}/{len(symbols)} mã có giá cho {run_date}")

    # 3) Financial ratios — weekly và monthly
    if args.mode in ("weekly", "monthly"):
        print(f"Bắt đầu fetch financials ({len(symbols)} mã)...")
        fin = ingest_market.fetch_financials(symbols, source)
        n_fin = warehouse.upsert_financial_ratios(con, fin)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_ratio", n_fin,
                           "ok" if n_fin else "empty", watermark=run_date)
        print(f"raw_financial_ratio: {n_fin} dòng")

    # 4) Company info — monthly only
    if args.mode == "monthly":
        print(f"Bắt đầu fetch company info ({len(symbols)} mã)...")
        info = ingest_market.fetch_company_info(symbols, source)
        n_info = warehouse.upsert_company_info(con, info)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_company_info", n_info,
                           "ok" if n_info else "empty", watermark=run_date)
        print(f"raw_company_info: {n_info} mã")

    con.close()
    print(f"Xong warehouse job ({args.mode}).")
```

- [ ] **Step 2: Smoke test locally (daily mode = current behavior)**

```bash
python build_warehouse.py --help
```

Expected output includes:
```
usage: build_warehouse.py [-h] [--mode {daily,weekly,monthly}]
```

```bash
python build_warehouse.py --mode daily
```

Expected: runs normally, prints "Xong warehouse job (daily)."

- [ ] **Step 3: Commit**

```bash
git add build_warehouse.py
git commit -m "feat: add --mode flag to build_warehouse.py for weekly/monthly cadences"
```

---

### Task 5: GitHub Actions weekly + monthly workflows

**Files:**
- Create: `.github/workflows/warehouse-weekly.yml`
- Create: `.github/workflows/warehouse-monthly.yml`

- [ ] **Step 1: Create warehouse-weekly.yml**

```yaml
name: warehouse-weekly

on:
  schedule:
    # Thứ 7 hàng tuần lúc 08:30 UTC (15:30 ICT)
    - cron: "30 8 * * 6"
  workflow_dispatch: {}

jobs:
  warehouse-weekly:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Warehouse weekly (giá + financial ratios)
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
          VNSTOCK_API_KEY: ${{ secrets.VNSTOCK_API_KEY }}
        run: python build_warehouse.py --mode weekly
```

- [ ] **Step 2: Create warehouse-monthly.yml**

```yaml
name: warehouse-monthly

on:
  schedule:
    # Ngày 1 hàng tháng lúc 09:00 UTC
    - cron: "0 9 1 * *"
  workflow_dispatch: {}

jobs:
  warehouse-monthly:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Warehouse monthly (giá + financials + company info)
        env:
          WAREHOUSE_DB: "md:vn_market"
          motherduck_token: ${{ secrets.MOTHERDUCK_TOKEN }}
          VNSTOCK_API_KEY: ${{ secrets.VNSTOCK_API_KEY }}
        run: python build_warehouse.py --mode monthly
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/warehouse-weekly.yml .github/workflows/warehouse-monthly.yml
git commit -m "feat: add warehouse-weekly and warehouse-monthly GitHub Actions workflows"
```

---

## PART 2B — Consumer Refactor (news pipeline reads warehouse)

---

### Task 6: warehouse.read_price_history()

**Files:**
- Modify: `src/warehouse.py`
- Test: `tests/test_warehouse_read.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_warehouse_read.py`:

```python
import pandas as pd
import duckdb
import pytest
from datetime import date, timedelta
from src.warehouse import init_warehouse, upsert_prices, read_price_history


@pytest.fixture
def con_with_data():
    con = duckdb.connect(":memory:")
    init_warehouse(con)
    today = date.today()
    rows = []
    for i in range(60):
        d = (today - timedelta(days=60 - i)).isoformat()
        rows.append({
            "symbol": "AAA", "trade_date": d,
            "open": 10.0, "high": 11.0, "low": 9.5,
            "close": 10.5, "volume": 100000, "value": 1050000000.0,
        })
    df = pd.DataFrame(rows)
    upsert_prices(con, df)
    yield con
    con.close()


def test_read_price_history_returns_dataframe(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    assert isinstance(result, pd.DataFrame)
    assert not result.empty


def test_read_price_history_has_required_columns(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    assert "close" in result.columns
    assert "volume" in result.columns


def test_read_price_history_respects_days_limit(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    assert len(result) <= 30


def test_read_price_history_returns_empty_for_unknown_symbol(con_with_data):
    result = read_price_history(con_with_data, "UNKNOWN", days=30)
    assert result.empty


def test_read_price_history_sorted_ascending(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    dates = result["trade_date"].tolist()
    assert dates == sorted(dates)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_warehouse_read.py -v
```

Expected: FAIL with `ImportError: cannot import name 'read_price_history'`

- [ ] **Step 3: Implement read_price_history in warehouse.py**

Add this function to `src/warehouse.py` (after `get_active_symbols`):

```python
def read_price_history(con, symbol: str, days: int) -> pd.DataFrame:
    """Đọc lịch sử OHLCV từ warehouse. Trả DataFrame với close, volume (tương thích signals.analyze)."""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=days * 2)).isoformat()
    df = con.execute(
        """
        SELECT trade_date, open, high, low, close, volume, value
        FROM raw_price_daily
        WHERE symbol = ? AND trade_date >= ?
        ORDER BY trade_date
        """,
        [symbol.upper().strip(), start],
    ).df()
    return df.tail(days).reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_warehouse_read.py -v
```

Expected: 5/5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/warehouse.py tests/test_warehouse_read.py
git commit -m "feat: add warehouse.read_price_history for consumer use"
```

---

### Task 7: ingest.fetch_history warehouse-first

**Files:**
- Modify: `src/ingest.py`
- Test: `tests/test_ingest_warehouse_fallback.py`

> **Context:** `signals.analyze(df)` needs `close` and optionally `volume`. `read_price_history` returns those columns. The warehouse has 3 years of history from Phase 1.5 backfill. After this task, `main.py` and `screener.py` automatically benefit — no changes needed to them.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ingest_warehouse_fallback.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock


def _make_wh_df(n_rows=60):
    """Simulate warehouse DataFrame with close + volume."""
    return pd.DataFrame({
        "trade_date": [f"2024-01-{i+1:02d}" for i in range(n_rows)],
        "open": [10.0] * n_rows,
        "high": [11.0] * n_rows,
        "low":  [9.5]  * n_rows,
        "close": [10.5] * n_rows,
        "volume": [100000] * n_rows,
        "value": [1e9] * n_rows,
    })


def test_fetch_history_uses_warehouse_when_enough_data():
    """If warehouse has >= days//2 rows, return warehouse data without API call."""
    wh_df = _make_wh_df(n_rows=60)

    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest._throttle"):
        mock_con = MagicMock()
        mock_wh.get_conn.return_value = mock_con
        mock_wh.read_price_history.return_value = wh_df

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert not result.empty
    assert "close" in result.columns
    # API was NOT called (no _throttle call for API, only warehouse path)
    mock_wh.read_price_history.assert_called_once()


def test_fetch_history_falls_back_to_api_when_warehouse_empty():
    """If warehouse returns empty, fall back to API."""
    api_df = _make_wh_df(n_rows=30)
    api_df.columns = ["time", "open", "high", "low", "close", "volume", "value"]

    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest.Quote") as MockQuote, \
         patch("src.ingest._throttle"):
        mock_con = MagicMock()
        mock_wh.get_conn.return_value = mock_con
        mock_wh.read_price_history.return_value = pd.DataFrame()
        MockQuote.return_value.history.return_value = api_df

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert not result.empty
    MockQuote.return_value.history.assert_called_once()


def test_fetch_history_falls_back_to_api_when_warehouse_unavailable():
    """If warehouse import/connect fails, silently fall back to API."""
    api_df = _make_wh_df(n_rows=30)
    api_df.columns = ["time", "open", "high", "low", "close", "volume", "value"]

    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest.Quote") as MockQuote, \
         patch("src.ingest._throttle"):
        mock_wh.get_conn.side_effect = Exception("DB not found")
        MockQuote.return_value.history.return_value = api_df

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert not result.empty
    MockQuote.return_value.history.assert_called_once()


def test_fetch_history_returns_empty_when_both_fail():
    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest.Quote") as MockQuote, \
         patch("src.ingest._throttle"):
        mock_wh.get_conn.side_effect = Exception("DB fail")
        MockQuote.return_value.history.return_value = None

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert result.empty
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ingest_warehouse_fallback.py -v
```

Expected: FAIL (warehouse is not yet imported in ingest.py)

- [ ] **Step 3: Modify ingest.fetch_history to try warehouse first**

In `src/ingest.py`, add this import at module level (after existing imports):

```python
from . import warehouse
```

Replace the existing `fetch_history` function:

```python
def fetch_history(symbol: str, source: str = "VCI", days: int = 120) -> pd.DataFrame:
    """OHLCV ngày trong `days` phiên gần nhất. Đọc warehouse trước, gọi API nếu thiếu."""
    # 1) Thử warehouse
    try:
        con = warehouse.get_conn()
        df = warehouse.read_price_history(con, symbol, days)
        con.close()
        if len(df) >= max(days // 2, 10):
            return df
    except Exception:
        pass

    # 2) Fallback: gọi API
    start = (date.today() - timedelta(days=days * 2)).isoformat()
    end = date.today().isoformat()
    _throttle()
    try:
        df = Quote(symbol=symbol, source=source).history(
            start=start, end=end, interval="1D"
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df.columns = [str(c).lower() for c in df.columns]
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        print(f"[history] {symbol}: {e}")
        return pd.DataFrame()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_ingest_warehouse_fallback.py -v
```

Expected: 4/4 PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass. If any test imports fail from circular imports (warehouse → ingest → warehouse), see note below.

> **Note on circular imports:** `warehouse.py` imports nothing from `ingest.py`. `ingest.py` now imports `warehouse`. `ingest_market.py` imports `ingest`. This chain is one-directional — no circular dependency.

- [ ] **Step 6: Smoke test main.py locally**

```bash
python main.py
```

Expected: runs without errors, bản tin sent to Telegram (or prints if no config). Should be noticeably faster since `fetch_history` reads DuckDB instead of calling API.

- [ ] **Step 7: Commit**

```bash
git add src/ingest.py tests/test_ingest_warehouse_fallback.py
git commit -m "feat: fetch_history reads warehouse first, falls back to API when data missing"
```

---

## Acceptance Criteria

After all tasks complete:

**2A:**
```sql
-- Should return rows with pe, pb, roe for most symbols after running --mode weekly
SELECT COUNT(DISTINCT symbol) FROM raw_financial_ratio;

-- Should return ~1500 rows after running --mode monthly
SELECT COUNT(*) FROM raw_company_info;
```

**2B:**
- `python main.py` runs significantly faster (no 3s-per-symbol throttle for history)
- Telegram bản tin still sent correctly
- `python -m pytest tests/ -v` all pass

**Báo cáo sau Phase 2:**
1. Số dòng `raw_financial_ratio` / số mã
2. Số dòng `raw_company_info`
3. Thời gian chạy `main.py` trước / sau 2B
4. Workflow files đã push: warehouse-weekly.yml, warehouse-monthly.yml
