# A3 — MCP Server (luồng hội thoại) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép hỏi đáp trực tiếp với warehouse trong Claude Code / Claude Desktop — "HPG đang rẻ hay đắt so với 5 năm qua?", "top 20 mã bluechip cổ tức" — thông qua 7 tool read-only đọc từ mart, kèm ràng buộc buộc agent nêu `as_of`, `peer_basis` và mức tin cậy dữ liệu.

**Architecture:** Một MCP server stdio bằng Python (`FastMCP`), chạy local, kết nối DuckDB/MotherDuck **read-only**. Mọi tool trả về dict có `as_of` và `data_quality`. Tool `search_stocks` gọi thẳng `src/scoring.py` (đã viết ở plan A2) nên kết quả hội thoại và kết quả báo cáo định kỳ luôn khớp nhau. Server là process độc lập — xoá khai báo trong `.mcp.json` là tắt hoàn toàn, không ảnh hưởng warehouse.

**Tech Stack:** Python 3.12 · `mcp` SDK (FastMCP) · DuckDB 1.5.3 · MotherDuck · pandas · pytest

## Global Constraints

- Spec nguồn: `docs/superpowers/specs/2026-08-09-fundamental-analysis-platform-design.md` §8.
- **Điều kiện tiên quyết:** plan A2 hoàn tất, `mart_stock_scorecard` và các mart khác đã có dữ liệu.
- **Mọi tool read-only.** `run_sql` chặn `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`, `ATTACH`, `COPY`, `INSTALL`, `LOAD`, `PRAGMA`, `SET`, `EXPORT`; giới hạn 1.000 dòng; timeout 30 giây.
- **Mọi tool trả kèm `as_of` và `data_quality`.**
- Không nhân bản logic chấm điểm — `search_stocks` phải gọi `src.scoring`.
- Chạy test: `.venv/bin/python -m pytest tests/ -q`.
- Branch làm việc: `feat/fundamental-analysis-platform`.

---

### Task 1: Khung server + kết nối read-only + `run_sql` có rào chắn

**Files:**
- Modify: `requirements.txt`
- Create: `mcp_server/__init__.py`, `mcp_server/db.py`, `mcp_server/server.py`
- Create: `tests/test_mcp_db.py`

**Interfaces:**
- Consumes: `src.warehouse` (đường dẫn DB qua `WAREHOUSE_DB`).
- Produces:
  - `mcp_server.db.get_readonly_conn()` — trả `(connection, is_readonly: bool)`
  - `mcp_server.db.SqlGuardError` — exception
  - `mcp_server.db.assert_safe_sql(query: str) -> None`
  - `mcp_server.db.run_query(con, sql: str, params=None, limit: int = 1000) -> list[dict]`
  - `mcp_server.db.as_of(con) -> dict` — `{"price_as_of": ..., "ratio_as_of": ..., "warehouse": ...}`

- [ ] **Step 1: Cài MCP SDK**

Thêm vào `requirements.txt`:

```
mcp>=1.2,<2.0
```

Run: `.venv/bin/pip install -r requirements.txt`
Expected: cài thành công; `.venv/bin/python -c "import mcp; print(mcp.__name__)"` in `mcp`.

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/test_mcp_db.py`:

```python
import duckdb
import pytest

from mcp_server import db


@pytest.fixture
def con(tmp_path):
    path = tmp_path / "m.duckdb"
    c = duckdb.connect(str(path))
    c.execute("CREATE TABLE t (a INTEGER, b VARCHAR)")
    c.execute("INSERT INTO t VALUES (1,'x'), (2,'y'), (3,'z')")
    yield c
    c.close()


@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (9,'q')",
    "update t set a = 5",
    "DELETE FROM t",
    "drop table t",
    "CREATE TABLE u (a INT)",
    "ALTER TABLE t ADD COLUMN c INT",
    "ATTACH 'other.db'",
    "COPY t TO 'out.csv'",
    "INSTALL httpfs",
    "LOAD httpfs",
    "PRAGMA database_list",
    "SET threads = 1",
    "select 1; drop table t",          # nhiều câu lệnh
])
def test_assert_safe_sql_blocks_writes(sql):
    with pytest.raises(db.SqlGuardError):
        db.assert_safe_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t",
    "  select a, b from t where b = 'x'  ",
    "WITH c AS (SELECT * FROM t) SELECT count(*) FROM c",
    "select 'update me' as note from t",    # từ khoá nằm trong chuỗi, không phải lệnh
])
def test_assert_safe_sql_allows_reads(sql):
    db.assert_safe_sql(sql)


def test_run_query_returns_dicts(con):
    rows = db.run_query(con, "SELECT a, b FROM t ORDER BY a")
    assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 3, "b": "z"}]


def test_run_query_applies_limit(con):
    rows = db.run_query(con, "SELECT a FROM t ORDER BY a", limit=2)
    assert len(rows) == 2


def test_run_query_rejects_write(con):
    with pytest.raises(db.SqlGuardError):
        db.run_query(con, "DELETE FROM t")
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 3
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_db.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_server'`

- [ ] **Step 4: Viết `mcp_server/__init__.py` và `mcp_server/db.py`**

`mcp_server/__init__.py`: file rỗng.

`mcp_server/db.py`:

```python
"""Kết nối read-only và rào chắn SQL cho MCP server.

Hai lớp bảo vệ độc lập:
  1. Kết nối read-only ở tầng DuckDB (nếu backend hỗ trợ).
  2. Rào chắn từ khoá ở tầng ứng dụng — luôn áp dụng, kể cả khi (1) thất bại.
"""
import os
import re
from pathlib import Path

import duckdb

FORBIDDEN = {
    "insert", "update", "delete", "drop", "create", "alter", "attach",
    "detach", "copy", "install", "load", "pragma", "set", "export",
    "import", "truncate", "replace", "call", "checkpoint", "vacuum",
}
_WORD = re.compile(r"[a-z_]+")
_STRING_LITERAL = re.compile(r"'[^']*'")


class SqlGuardError(RuntimeError):
    """Câu lệnh SQL bị từ chối vì không phải truy vấn đọc."""


def assert_safe_sql(query: str) -> None:
    """Chỉ cho phép một câu SELECT/WITH duy nhất."""
    if not query or not query.strip():
        raise SqlGuardError("Câu truy vấn rỗng.")

    # Bỏ chuỗi ký tự để từ khoá bên trong chuỗi không bị bắt nhầm.
    stripped = _STRING_LITERAL.sub("''", query)
    body = stripped.strip().rstrip(";")

    if ";" in body:
        raise SqlGuardError("Chỉ cho phép một câu lệnh duy nhất.")

    words = _WORD.findall(body.lower())
    if not words or words[0] not in {"select", "with"}:
        raise SqlGuardError("Chỉ chấp nhận câu lệnh bắt đầu bằng SELECT hoặc WITH.")

    hit = sorted(set(words) & FORBIDDEN)
    if hit:
        raise SqlGuardError(f"Câu lệnh chứa từ khoá bị cấm: {hit}")


def get_readonly_conn():
    """Trả (connection, is_readonly).

    MotherDuck có thể không nhận read_only — khi đó vẫn kết nối được nhưng
    is_readonly=False, và rào chắn SQL ở tầng ứng dụng là lớp bảo vệ duy nhất.
    """
    root = Path(__file__).resolve().parent.parent
    dbpath = os.getenv("WAREHOUSE_DB", str(root / "data" / "warehouse.duckdb"))
    try:
        return duckdb.connect(dbpath, read_only=True), True
    except Exception:
        return duckdb.connect(dbpath), False


def run_query(con, sql: str, params=None, limit: int = 1000) -> list[dict]:
    """Chạy truy vấn đọc, trả tối đa `limit` dòng dưới dạng list[dict]."""
    assert_safe_sql(sql)
    wrapped = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) LIMIT {int(limit)}"
    df = con.execute(wrapped, params or []).df()
    return df.to_dict(orient="records")


def as_of(con) -> dict:
    """Thời điểm dữ liệu — mọi tool phải trả kèm để agent không nói về số cũ."""
    price = con.execute(
        "SELECT max(trade_date) FROM fct_price_daily"
    ).fetchone()[0]
    ratio = con.execute(
        "SELECT max(period_end_date) FROM fct_financial_quarterly"
    ).fetchone()[0]
    return {
        "price_as_of": str(price) if price else None,
        "ratio_as_of": str(ratio) if ratio else None,
        "warehouse": os.getenv("WAREHOUSE_DB", "data/warehouse.duckdb"),
    }
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_db.py -q`
Expected: PASS — 20 passed (13 câu bị chặn + 4 câu được phép + 3 test `run_query`)

- [ ] **Step 6: Viết khung `mcp_server/server.py` với tool `run_sql`**

```python
"""MCP server — hỏi đáp với warehouse phân tích cơ bản VN.

Chạy:
    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m mcp_server.server

Tắt luồng này: xoá khai báo trong .mcp.json. Warehouse và job báo cáo
không bị ảnh hưởng.
"""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_server import db

ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS = (ROOT / "mcp_server" / "instructions.md").read_text(encoding="utf-8")

mcp = FastMCP("vn-stock-analysis", instructions=INSTRUCTIONS)

_CON = None
_READONLY = False


def conn():
    global _CON, _READONLY
    if _CON is None:
        _CON, _READONLY = db.get_readonly_conn()
    return _CON


@mcp.tool()
def run_sql(query: str, limit: int = 200) -> dict:
    """Chạy một truy vấn SELECT read-only trên warehouse.

    Dùng khi 6 tool chuyên biệt không trả lời được câu hỏi. Chỉ chấp nhận
    một câu lệnh SELECT/WITH; mọi lệnh ghi đều bị từ chối.

    Bảng chính: dim_stock, dim_industry_hierarchy, fct_price_daily,
    fct_financial_quarterly, mart_valuation_band, mart_sector_snapshot,
    mart_stock_scorecard, mart_data_quality.
    """
    c = conn()
    try:
        rows = db.run_query(c, query, limit=min(limit, 1000))
    except db.SqlGuardError as e:
        return {"error": str(e), "rows": []}
    return {"rows": rows, "row_count": len(rows), **db.as_of(c)}


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 7: Viết `mcp_server/instructions.md`**

```markdown
# Luật khi dùng warehouse phân tích cơ bản VN

Đây là dữ liệu tài chính doanh nghiệp niêm yết Việt Nam. Người dùng là nhà
đầu tư cá nhân tự quản lý danh mục, ưu tiên nắm giữ dài hạn.

## Bắt buộc

1. **Không bịa số.** Mọi con số phải đến từ kết quả tool hoặc trường `facts`.
   Không tự tính chỉ tiêu mới từ các số đã có.
2. **Luôn nêu `as_of`** khi phát biểu về một mã: giá tính đến phiên nào, tỷ số
   tính đến quý nào.
3. **Luôn nêu `peer_basis` và `peer_count`** khi nói "rẻ hơn ngành". So với 15
   mã khác hẳn so với 300 mã.
4. **Không đưa khuyến nghị mua/bán.** Nêu luận điểm đầu tư kèm **rủi ro đối
   trọng**. Kết thúc bằng lưu ý rằng đây là thông tin tham khảo.
5. Khi `data_quality_score < 60`, nói rõ dữ liệu không đủ để kết luận chắc chắn
   và nêu `quality_flags`.
6. Khi so sánh các mã khác `com_class`, nói rõ chỉ tiêu **không tương đương**.

## Bối cảnh dữ liệu cần biết

- `com_class` chia doanh nghiệp thành `NONFIN` (phi tài chính), `BANK`
  (ngân hàng), `OTHERFIN` (bảo hiểm/chứng khoán). Mỗi nhóm dùng bộ chỉ tiêu
  riêng: ngân hàng không có ROIC hay hệ số thanh toán hiện hành, mà có NIM,
  NPL, CIR, CAR, CASA.
- Điểm thành phần là **percentile trong nhóm tương đương**, thang 0–100.
  Điểm 0 = kém nhất nhóm. Điểm **NULL = không đo được** — hai thứ này khác nhau,
  đừng đọc NULL thành 0.
- `valuation_band` dựa trên percentile P/E so với **chính mã trong 5 năm qua**,
  không phải so với thị trường.
- Doanh thu và lợi nhuận là **suy ra** từ `market_cap / ps` và `market_cap / pe`,
  không đọc trực tiếp từ báo cáo tài chính. Đối chiếu HPG 2024 cho kết quả khớp,
  nhưng vẫn nên nói rõ khi người dùng cần độ chính xác tuyệt đối.
- `dividend_yield` bằng 0 có thể là "không trả cổ tức" hoặc "nguồn không có
  dữ liệu" — không khẳng định chắc chắn doanh nghiệp không trả cổ tức.
```

- [ ] **Step 8: Chạy thử server**

```bash
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python -c "
from mcp_server import db
con, ro = db.get_readonly_conn()
print('read_only =', ro)
print(db.as_of(con))
print(db.run_query(con, 'select symbol, com_class, quality_score from mart_stock_scorecard order by quality_score desc nulls last', limit=5))
"
```

Expected: in ra `as_of` có ngày và 5 dòng dữ liệu.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt mcp_server/ tests/test_mcp_db.py
git commit -m "feat(mcp): khung server + kết nối read-only + rào chắn SQL

run_sql chỉ chấp nhận một câu SELECT/WITH; chặn 20 từ khoá ghi.
Bỏ chuỗi ký tự trước khi quét để không bắt nhầm từ khoá trong literal.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `search_stocks` và `get_stock_profile`

**Files:**
- Create: `mcp_server/tools.py`
- Modify: `mcp_server/server.py`
- Create: `tests/test_mcp_tools.py`, `tests/conftest_mart.py`

**Interfaces:**
- Consumes: `mcp_server.db`, `src.scoring`.
- Produces:
  - `mcp_server.tools.search_stocks(con, profile, limit, min_composite=None) -> dict`
  - `mcp_server.tools.get_stock_profile(con, symbol) -> dict`

- [ ] **Step 1: Tạo fixture mart giả — `tests/conftest_mart.py`**

```python
"""Dựng một warehouse tí hon có cấu trúc giống mart thật, để test tool
không phụ thuộc MotherDuck."""
import duckdb


def build_fake_mart(path: str):
    con = duckdb.connect(path)
    con.execute("""
        CREATE TABLE mart_stock_scorecard (
            symbol VARCHAR, company_name VARCHAR, exchange VARCHAR,
            com_class VARCHAR, icb_code_lv2 VARCHAR, industry_lv2 VARCHAR,
            peer_basis VARCHAR, peer_count BIGINT,
            value_score DOUBLE, quality_score DOUBLE, growth_score DOUBLE,
            dividend_score DOUBLE, safety_score DOUBLE,
            value_metrics_used BIGINT, quality_metrics_used BIGINT,
            growth_metrics_used BIGINT, dividend_metrics_used BIGINT,
            safety_metrics_used BIGINT,
            market_cap DOUBLE, avg_turnover_20d DOUBLE, last_close DOUBLE,
            price_as_of DATE, pe DOUBLE, pb DOUBLE,
            pe_pct_own_5y DOUBLE, pb_pct_own_5y DOUBLE,
            valuation_band VARCHAR, ratio_as_of DATE,
            is_loss_making BOOLEAN, data_quality_score DOUBLE,
            quality_flags VARCHAR, dividend_years_consecutive DOUBLE,
            roe_avg_8q DOUBLE, roe_stability DOUBLE, facts VARCHAR
        );
        INSERT INTO mart_stock_scorecard VALUES
        ('AAA','Cty A','HOSE','NONFIN','1700','Tài nguyên cơ bản',
         'com_class+icb_lv2', 40, 80,70,60,90,50, 5,6,5,4,7,
         5e12, 5e9, 20000, DATE '2026-08-07', 9.5, 1.2, 0.18, 0.22,
         'rất rẻ', DATE '2026-06-30', FALSE, 90, '', 5, 0.18, 0.85,
         '[{"metric":"pe_pct_own_5y","value":0.18,"text":"P/E 9,5 - thấp hơn 82% số quý"}]'),
        ('VCB','Cty B','HOSE','BANK','8300','Ngân hàng',
         'com_class', 27, 60,85,55,70,80, 4,8,5,4,7,
         5e14, 2e11, 59000, DATE '2026-08-07', 15.2, 2.6, 0.45, 0.40,
         'hợp lý', DATE '2026-06-30', FALSE, 95, '', 4, 0.19, 0.90,
         '[{"metric":"roe_avg_8q","value":0.19,"text":"ROE trung bình 8 quý 19,0%"}]'),
        ('CCC','Cty C','UPCOM','NONFIN','1700','Tài nguyên cơ bản',
         'com_class', 300, 95,40,30,20,25, 5,6,5,4,7,
         6e11, 2e8, 8000, DATE '2026-08-07', 4.0, 0.5, 0.05, 0.08,
         'rất rẻ', DATE '2026-06-30', TRUE, 45, 'thiếu lịch sử tỷ số (<12 quý)',
         0, -0.05, 0.0, '[]');
    """)
    con.execute("""
        CREATE TABLE fct_price_daily (symbol VARCHAR, trade_date DATE, close DOUBLE);
        INSERT INTO fct_price_daily VALUES ('AAA', DATE '2026-08-07', 20000);
        CREATE TABLE fct_financial_quarterly (
            symbol VARCHAR, year INTEGER, quarter INTEGER, period_end_date DATE,
            com_class VARCHAR, pe DOUBLE, pb DOUBLE, roe DOUBLE,
            revenue_ttm DOUBLE, earnings_ttm DOUBLE, revenue_yoy DOUBLE,
            earnings_yoy DOUBLE
        );
        INSERT INTO fct_financial_quarterly VALUES
          ('AAA',2026,2,DATE '2026-06-30','NONFIN',9.5,1.2,0.18,1e13,1e12,0.12,0.20),
          ('AAA',2026,1,DATE '2026-03-31','NONFIN',10.1,1.3,0.17,9.5e12,9e11,0.10,0.15);
        CREATE TABLE mart_valuation_band (
            symbol VARCHAR, period_end_date DATE, com_class VARCHAR,
            icb_code_lv2 VARCHAR, industry_lv2 VARCHAR,
            pe DOUBLE, pb DOUBLE, ps DOUBLE,
            pe_pct_own_5y DOUBLE, pb_pct_own_5y DOUBLE,
            own_quarters_used BIGINT, valuation_band VARCHAR
        );
        INSERT INTO mart_valuation_band VALUES
          ('AAA',DATE '2026-06-30','NONFIN','1700','Tài nguyên cơ bản',
           9.5,1.2,0.9,0.18,0.22,20,'rất rẻ'),
          ('AAA',DATE '2026-03-31','NONFIN','1700','Tài nguyên cơ bản',
           10.1,1.3,1.0,0.30,0.35,19,'rẻ');
        CREATE TABLE mart_sector_snapshot (
            icb_code_lv2 VARCHAR, industry_lv2 VARCHAR, com_class VARCHAR,
            period_end_date DATE, n_symbols BIGINT, median_pe DOUBLE,
            median_pb DOUBLE, median_roe DOUBLE, sector_return_3m DOUBLE
        );
        INSERT INTO mart_sector_snapshot VALUES
          ('1700','Tài nguyên cơ bản','NONFIN',DATE '2026-06-30',40,12.5,1.4,0.13,0.08),
          ('8300','Ngân hàng','BANK',DATE '2026-06-30',27,8.6,1.3,0.18,0.11);
        CREATE TABLE mart_data_quality (
            symbol VARCHAR, quarters_available BIGINT, price_sessions_1y BIGINT,
            ratio_age_days BIGINT, max_price_gap_days BIGINT,
            has_required_metrics BOOLEAN, data_quality_ratio DOUBLE,
            data_quality_score DOUBLE, quality_flags VARCHAR
        );
        INSERT INTO mart_data_quality VALUES
          ('AAA',20,245,40,3,TRUE,0.90,90,''),
          ('VCB',20,248,40,2,TRUE,0.95,95,''),
          ('CCC',6,120,400,45,FALSE,0.45,45,'thiếu lịch sử tỷ số (<12 quý)');
        CREATE TABLE dim_stock (
            symbol VARCHAR, company_name VARCHAR, exchange VARCHAR,
            com_class VARCHAR, industry_lv2 VARCHAR, market_cap DOUBLE,
            avg_turnover_20d DOUBLE, last_close DOUBLE, price_as_of DATE,
            free_float_percentage DOUBLE, foreigner_percentage DOUBLE,
            listed_date DATE, listing_age_years BIGINT,
            return_1m DOUBLE, return_3m DOUBLE, return_12m DOUBLE,
            high_52w DOUBLE, low_52w DOUBLE
        );
        INSERT INTO dim_stock VALUES
          ('AAA','Cty A','HOSE','NONFIN','Tài nguyên cơ bản',5e12,5e9,20000,
           DATE '2026-08-07',0.55,0.22,DATE '2007-11-15',18,0.03,0.08,0.15,29000,19500),
          ('VCB','Cty B','HOSE','BANK','Ngân hàng',5e14,2e11,59000,
           DATE '2026-08-07',0.25,0.23,DATE '2009-06-30',17,0.01,0.05,0.10,63100,50000),
          ('CCC','Cty C','UPCOM','NONFIN','Tài nguyên cơ bản',6e11,2e8,8000,
           DATE '2026-08-07',0.30,0.02,DATE '2022-01-10',4,-0.05,-0.12,-0.30,15000,7500);
    """)
    con.close()
```

- [ ] **Step 2: Viết test thất bại — `tests/test_mcp_tools.py`**

```python
import duckdb
import pytest

from mcp_server import tools
from tests.conftest_mart import build_fake_mart


@pytest.fixture
def con(tmp_path):
    path = str(tmp_path / "mart.duckdb")
    build_fake_mart(path)
    c = duckdb.connect(path, read_only=True)
    yield c
    c.close()


def test_search_stocks_returns_ranked_with_as_of(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    assert res["profile"] == "bluechip_dividend"
    assert "price_as_of" in res and "ratio_as_of" in res
    symbols = [r["symbol"] for r in res["results"]]
    assert "CCC" not in symbols            # UPCOM + thanh khoản thấp → loại
    assert res["universe_size"] >= 1
    assert "rejected_counts" in res


def test_search_stocks_includes_peer_basis_and_facts(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    first = res["results"][0]
    assert "peer_basis" in first and "peer_count" in first
    assert "composite_score" in first
    assert "facts" in first


def test_get_stock_profile_has_quality_and_as_of(con):
    res = tools.get_stock_profile(con, "AAA")
    assert res["symbol"] == "AAA"
    assert res["com_class"] == "NONFIN"
    assert res["scores"]["quality"] == 70
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["price_as_of"] == "2026-08-07"


def test_get_stock_profile_warns_on_low_quality(con):
    res = tools.get_stock_profile(con, "CCC")
    assert res["data_quality"]["data_quality_score"] == 45
    assert res["data_quality"]["reliable"] is False
    assert "thiếu lịch sử" in res["data_quality"]["quality_flags"]


def test_get_stock_profile_unknown_symbol(con):
    res = tools.get_stock_profile(con, "ZZZ")
    assert "error" in res
    assert "ZZZ" in res["error"]
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_server.tools'`

- [ ] **Step 4: Viết `mcp_server/tools.py`**

```python
"""Cài đặt các tool — tách khỏi server.py để test được mà không cần MCP runtime."""
import json

import pandas as pd

from mcp_server import db
from src import scoring

RELIABLE_MIN = 60


def _clean(obj):
    """Đưa giá trị pandas/numpy về kiểu JSON được."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if obj is None or (isinstance(obj, float) and pd.isna(obj)):
        return None
    if pd.isna(obj) if not isinstance(obj, (list, dict, str)) else False:
        return None
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def search_stocks(con, profile: str = None, limit: int = 20,
                  min_composite: float = None) -> dict:
    """Chạy screener theo profile, trả danh sách xếp hạng."""
    report = scoring.screen_report(con, profile, limit=limit)
    ranked = report["ranked"]
    if min_composite is not None and not ranked.empty:
        ranked = ranked[ranked["composite_score"] >= min_composite]

    cols = [
        "rank", "symbol", "company_name", "exchange", "com_class",
        "industry_lv2", "composite_score", "value_score", "quality_score",
        "growth_score", "dividend_score", "safety_score", "valuation_band",
        "pe", "pb", "pe_pct_own_5y", "roe_avg_8q", "dividend_years_consecutive",
        "market_cap", "avg_turnover_20d", "peer_basis", "peer_count",
        "data_quality_score", "quality_flags", "facts",
    ]
    present = [c for c in cols if c in ranked.columns]
    results = _clean(ranked[present].to_dict(orient="records"))
    for r in results:
        if isinstance(r.get("facts"), str):
            try:
                r["facts"] = json.loads(r["facts"])
            except (ValueError, TypeError):
                r["facts"] = []

    return {
        "profile": report["profile"],
        "profile_label": report["label"],
        "universe_size": report["universe_size"],
        "rejected_counts": report["rejected_counts"],
        "unscored": _clean(report["unscored"].to_dict(orient="records")),
        "results": results,
        **db.as_of(con),
    }


def get_stock_profile(con, symbol: str) -> dict:
    """Hồ sơ đầy đủ một mã: nhận dạng, điểm, định giá, chất lượng dữ liệu."""
    sym = symbol.upper().strip()
    rows = db.run_query(
        con,
        """
        SELECT s.*, d.free_float_percentage, d.foreigner_percentage,
               d.listed_date, d.return_1m, d.return_3m, d.return_12m,
               d.high_52w, d.low_52w
        FROM mart_stock_scorecard s
        LEFT JOIN dim_stock d USING (symbol)
        WHERE s.symbol = ?
        """,
        params=[sym],
        limit=1,
    )
    if not rows:
        return {"error": f"Không tìm thấy mã {sym} trong warehouse.",
                **db.as_of(con)}

    r = _clean(rows[0])
    facts = r.get("facts")
    if isinstance(facts, str):
        try:
            facts = json.loads(facts)
        except (ValueError, TypeError):
            facts = []

    dq_score = r.get("data_quality_score") or 0
    return {
        "symbol": r["symbol"],
        "company_name": r.get("company_name"),
        "exchange": r.get("exchange"),
        "com_class": r.get("com_class"),
        "industry": r.get("industry_lv2"),
        "market_cap": r.get("market_cap"),
        "last_close": r.get("last_close"),
        "avg_turnover_20d": r.get("avg_turnover_20d"),
        "free_float_percentage": r.get("free_float_percentage"),
        "foreigner_percentage": r.get("foreigner_percentage"),
        "listed_date": r.get("listed_date"),
        "returns": {"1m": r.get("return_1m"), "3m": r.get("return_3m"),
                    "12m": r.get("return_12m")},
        "range_52w": {"high": r.get("high_52w"), "low": r.get("low_52w")},
        "scores": {
            "value": r.get("value_score"),
            "quality": r.get("quality_score"),
            "growth": r.get("growth_score"),
            "dividend": r.get("dividend_score"),
            "safety": r.get("safety_score"),
        },
        "peer_basis": r.get("peer_basis"),
        "peer_count": r.get("peer_count"),
        "valuation": {
            "pe": r.get("pe"), "pb": r.get("pb"),
            "pe_pct_own_5y": r.get("pe_pct_own_5y"),
            "pb_pct_own_5y": r.get("pb_pct_own_5y"),
            "band": r.get("valuation_band"),
        },
        "fundamentals": {
            "roe_avg_8q": r.get("roe_avg_8q"),
            "roe_stability": r.get("roe_stability"),
            "dividend_years_consecutive": r.get("dividend_years_consecutive"),
            "is_loss_making": r.get("is_loss_making"),
        },
        "facts": facts,
        "data_quality": {
            "data_quality_score": dq_score,
            "quality_flags": r.get("quality_flags") or "",
            "reliable": dq_score >= RELIABLE_MIN,
        },
        "ratio_as_of": str(r.get("ratio_as_of")) if r.get("ratio_as_of") else None,
        "price_as_of": str(r.get("price_as_of")) if r.get("price_as_of") else None,
    }
```

- [ ] **Step 5: Đăng ký 2 tool trong `mcp_server/server.py`**

Thêm import `from mcp_server import tools` và:

```python
@mcp.tool()
def search_stocks(profile: str = "bluechip_dividend", limit: int = 20,
                  min_composite: float = None) -> dict:
    """Quét toàn thị trường theo hồ sơ đầu tư, trả danh sách xếp hạng.

    profile: 'bluechip_dividend' (bluechip + cổ tức, dài hạn),
             'deep_value' (định giá sâu, mở rộng xuống mid-cap),
             'quality_growth' (chất lượng + tăng trưởng).

    Kết quả gồm 5 điểm thành phần (0-100, percentile trong nhóm tương đương),
    'facts' là các phát biểu số liệu đã tính sẵn — chỉ diễn giải, không tự tính
    số mới. 'rejected_counts' cho biết vì sao các mã khác bị loại.
    """
    return tools.search_stocks(conn(), profile, limit, min_composite)


@mcp.tool()
def get_stock_profile(symbol: str) -> dict:
    """Hồ sơ đầy đủ một mã: ngành, loại hình, 5 điểm, định giá, chất lượng dữ liệu.

    Luôn kiểm tra data_quality.reliable trước khi kết luận về mã này.
    """
    return tools.get_stock_profile(conn(), symbol)
```

- [ ] **Step 6: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: PASS — 5 passed

- [ ] **Step 7: Commit**

```bash
git add mcp_server/ tests/test_mcp_tools.py tests/conftest_mart.py
git commit -m "feat(mcp): tool search_stocks và get_stock_profile

search_stocks gọi thẳng src.scoring nên kết quả hội thoại luôn khớp
với báo cáo định kỳ sau này.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `get_valuation_history`, `get_financial_history`, `compare_stocks`, `get_sector_snapshot`

**Files:**
- Modify: `mcp_server/tools.py`, `mcp_server/server.py`
- Modify: `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `mcp_server.db`.
- Produces:
  - `mcp_server.tools.get_valuation_history(con, symbol, years=5) -> dict`
  - `mcp_server.tools.get_financial_history(con, symbol, quarters=12) -> dict`
  - `mcp_server.tools.compare_stocks(con, symbols) -> dict`
  - `mcp_server.tools.get_sector_snapshot(con, com_class=None) -> dict`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_mcp_tools.py`:

```python
def test_get_valuation_history_returns_series(con):
    res = tools.get_valuation_history(con, "AAA", years=5)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    latest = res["history"][0]
    assert latest["valuation_band"] == "rất rẻ"
    assert latest["pe_pct_own_5y"] == 0.18
    assert "ratio_as_of" in res


def test_get_financial_history_returns_quarters(con):
    res = tools.get_financial_history(con, "AAA", quarters=12)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    assert res["history"][0]["revenue_ttm"] == 1e13
    assert res["note"].startswith("Doanh thu và lợi nhuận là chỉ tiêu SUY RA")


def test_compare_stocks_warns_on_mixed_com_class(con):
    res = tools.compare_stocks(con, ["AAA", "VCB"])
    assert len(res["stocks"]) == 2
    assert res["comparable"] is False
    assert "không tương đương" in res["warning"]


def test_compare_stocks_same_class_is_comparable(con):
    res = tools.compare_stocks(con, ["AAA", "CCC"])
    assert res["comparable"] is True
    assert res["warning"] == ""


def test_compare_stocks_reports_missing_symbol(con):
    res = tools.compare_stocks(con, ["AAA", "ZZZ"])
    assert res["not_found"] == ["ZZZ"]


def test_get_sector_snapshot_filters_com_class(con):
    res = tools.get_sector_snapshot(con, com_class="BANK")
    assert len(res["sectors"]) == 1
    assert res["sectors"][0]["industry_lv2"] == "Ngân hàng"
    assert res["sectors"][0]["median_pe"] == 8.6
```

- [ ] **Step 2: Chạy để xác nhận fail**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: FAIL — `AttributeError: module 'mcp_server.tools' has no attribute 'get_valuation_history'`

- [ ] **Step 3: Thêm 4 hàm vào `mcp_server/tools.py`**

```python
def get_valuation_history(con, symbol: str, years: int = 5) -> dict:
    """Chuỗi P/E, P/B theo quý kèm percentile so với chính mã và nhãn vùng."""
    sym = symbol.upper().strip()
    rows = db.run_query(
        con,
        """
        SELECT period_end_date, pe, pb, ps, pe_pct_own_5y, pb_pct_own_5y,
               own_quarters_used, valuation_band, com_class, industry_lv2
        FROM mart_valuation_band
        WHERE symbol = ?
          AND period_end_date >= current_date - (? * 365) * INTERVAL 1 DAY
        ORDER BY period_end_date DESC
        """,
        params=[sym, years],
        limit=4 * years + 4,
    )
    if not rows:
        return {"error": f"Không có dữ liệu định giá cho {sym}.", **db.as_of(con)}
    return {
        "symbol": sym,
        "com_class": rows[0].get("com_class"),
        "industry": rows[0].get("industry_lv2"),
        "history": _clean(rows),
        "note": "pe_pct_own_5y là percentile P/E so với CHÍNH MÃ trong 5 năm "
                "qua (0 = rẻ nhất lịch sử của nó), không phải so với thị trường.",
        **db.as_of(con),
    }


def get_financial_history(con, symbol: str, quarters: int = 12) -> dict:
    """Tỷ số theo quý + doanh thu/LNST suy ra + tăng trưởng."""
    sym = symbol.upper().strip()
    rows = db.run_query(
        con,
        """
        SELECT year, quarter, period_end_date, com_class,
               pe, pb, roe, revenue_ttm, earnings_ttm,
               revenue_yoy, earnings_yoy
        FROM fct_financial_quarterly
        WHERE symbol = ? AND quarter BETWEEN 1 AND 4
        ORDER BY period_end_date DESC
        """,
        params=[sym],
        limit=quarters,
    )
    if not rows:
        return {"error": f"Không có dữ liệu tài chính cho {sym}.", **db.as_of(con)}
    return {
        "symbol": sym,
        "history": _clean(rows),
        "note": "Doanh thu và lợi nhuận là chỉ tiêu SUY RA từ market_cap/ps và "
                "market_cap/pe, không đọc trực tiếp từ báo cáo tài chính. "
                "Đối chiếu HPG 2024 cho kết quả khớp, nhưng nên nói rõ khi "
                "người dùng cần độ chính xác tuyệt đối.",
        **db.as_of(con),
    }


def compare_stocks(con, symbols: list[str]) -> dict:
    """So sánh nhiều mã cạnh nhau, cảnh báo nếu khác loại hình doanh nghiệp."""
    syms = [s.upper().strip() for s in symbols]
    placeholders = ", ".join("?" for _ in syms)
    rows = db.run_query(
        con,
        f"""
        SELECT symbol, company_name, exchange, com_class, industry_lv2,
               value_score, quality_score, growth_score, dividend_score,
               safety_score, pe, pb, pe_pct_own_5y, valuation_band,
               roe_avg_8q, dividend_years_consecutive, market_cap,
               avg_turnover_20d, peer_basis, peer_count, data_quality_score
        FROM mart_stock_scorecard
        WHERE symbol IN ({placeholders})
        """,
        params=syms,
        limit=len(syms),
    )
    found = {r["symbol"] for r in rows}
    classes = {r["com_class"] for r in rows}
    comparable = len(classes) <= 1
    return {
        "stocks": _clean(rows),
        "not_found": [s for s in syms if s not in found],
        "com_classes": sorted(classes),
        "comparable": comparable,
        "warning": "" if comparable else (
            "Các mã thuộc loại hình doanh nghiệp khác nhau "
            f"({', '.join(sorted(classes))}) — chỉ tiêu KHÔNG tương đương. "
            "Ngân hàng vốn dĩ đòn bẩy cao và không có ROIC hay hệ số thanh "
            "toán hiện hành; đừng so trực tiếp các con số này."
        ),
        **db.as_of(con),
    }


def get_sector_snapshot(con, com_class: str = None) -> dict:
    """Bức tranh định giá theo ngành ICB cấp 2 ở kỳ mới nhất."""
    sql = """
        SELECT icb_code_lv2, industry_lv2, com_class, period_end_date,
               n_symbols, median_pe, median_pb, median_roe, sector_return_3m
        FROM mart_sector_snapshot
        WHERE period_end_date = (SELECT max(period_end_date) FROM mart_sector_snapshot)
    """
    params = []
    if com_class:
        sql += " AND com_class = ?"
        params.append(com_class.upper().strip())
    sql += " ORDER BY n_symbols DESC"
    rows = db.run_query(con, sql, params=params, limit=200)
    return {"sectors": _clean(rows),
            "note": "Trung vị tính trong cùng com_class — không so ngân hàng "
                    "với doanh nghiệp sản xuất.",
            **db.as_of(con)}
```

- [ ] **Step 4: Đăng ký 4 tool trong `mcp_server/server.py`**

```python
@mcp.tool()
def get_valuation_history(symbol: str, years: int = 5) -> dict:
    """P/E, P/B theo quý kèm percentile so với chính mã và nhãn vùng định giá.

    Dùng để trả lời "mã này đang rẻ hay đắt so với quá khứ của chính nó".
    """
    return tools.get_valuation_history(conn(), symbol, years)


@mcp.tool()
def get_financial_history(symbol: str, quarters: int = 12) -> dict:
    """Tỷ số theo quý + doanh thu/LNST suy ra + tăng trưởng YoY."""
    return tools.get_financial_history(conn(), symbol, quarters)


@mcp.tool()
def compare_stocks(symbols: list[str]) -> dict:
    """So sánh nhiều mã cạnh nhau. Cảnh báo khi các mã khác loại hình DN."""
    return tools.compare_stocks(conn(), symbols)


@mcp.tool()
def get_sector_snapshot(com_class: str = None) -> dict:
    """Trung vị P/E, P/B, ROE và suất sinh lời 3 tháng theo ngành ICB cấp 2.

    com_class: để trống = mọi loại hình; 'BANK' / 'NONFIN' / 'OTHERFIN'.
    """
    return tools.get_sector_snapshot(conn(), com_class)
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py -q`
Expected: PASS — 11 passed

- [ ] **Step 6: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 110 passed

- [ ] **Step 7: Commit**

```bash
git add mcp_server/ tests/test_mcp_tools.py
git commit -m "feat(mcp): 4 tool định giá, tài chính, so sánh và ngành

compare_stocks cảnh báo rõ khi so mã khác com_class — chỉ tiêu ngân hàng
và doanh nghiệp sản xuất không tương đương.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Đăng ký server và nghiệm thu đầu-cuối

**Files:**
- Create: `.mcp.json`
- Modify: `README.md`
- Create: `scripts/check_mcp_tools.py`

**Interfaces:**
- Consumes: toàn bộ `mcp_server/`.
- Produces: `scripts.check_mcp_tools.main()` — chạy cả 7 tool trên dữ liệu thật và in kết quả.

- [ ] **Step 1: Tạo `.mcp.json`**

```json
{
  "mcpServers": {
    "vn-stock-analysis": {
      "command": ".venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "WAREHOUSE_DB": "md:vn_market"
      }
    }
  }
}
```

> `motherduck_token` được nạp từ `.env` qua `python-dotenv`. Thêm `load_dotenv()` vào đầu `mcp_server/server.py`:
>
> ```python
> from dotenv import load_dotenv
> load_dotenv()
> ```
>
> Đặt dòng này **trước** `from mcp_server import db`.

- [ ] **Step 2: Viết script nghiệm thu `scripts/check_mcp_tools.py`**

```python
"""Chạy cả 7 tool MCP trên dữ liệu thật để nghiệm thu.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.check_mcp_tools
"""
import json
import sys

from dotenv import load_dotenv

from mcp_server import db, tools

load_dotenv()


def show(name, result):
    print("=" * 70)
    print(name)
    if isinstance(result, dict) and "error" in result:
        print("  LỖI:", result["error"])
        return False
    preview = json.dumps(result, ensure_ascii=False, default=str)[:600]
    print(" ", preview, "...")
    return True


def main():
    con, readonly = db.get_readonly_conn()
    print(f"read_only = {readonly}")
    ok = True

    ok &= show("search_stocks(bluechip_dividend)",
               tools.search_stocks(con, "bluechip_dividend", limit=10))
    ok &= show("get_stock_profile(HPG)", tools.get_stock_profile(con, "HPG"))
    ok &= show("get_valuation_history(HPG)",
               tools.get_valuation_history(con, "HPG", years=5))
    ok &= show("get_financial_history(HPG)",
               tools.get_financial_history(con, "HPG", quarters=8))
    ok &= show("compare_stocks(HPG, VCB)",
               tools.compare_stocks(con, ["HPG", "VCB"]))
    ok &= show("get_sector_snapshot(BANK)",
               tools.get_sector_snapshot(con, "BANK"))
    ok &= show("run_sql", {"rows": db.run_query(
        con, "select symbol, quality_score from mart_stock_scorecard "
             "order by quality_score desc nulls last", limit=5)})

    print("=" * 70)
    try:
        db.assert_safe_sql("DROP TABLE mart_stock_scorecard")
        print("LỖI NGHIÊM TRỌNG: rào chắn SQL không chặn DROP")
        ok = False
    except db.SqlGuardError:
        print("Rào chắn SQL chặn DROP đúng như mong đợi.")

    con.close()
    print("\n" + ("TẤT CẢ ĐẠT" if ok else "CÓ TOOL KHÔNG ĐẠT"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Chạy nghiệm thu trên dữ liệu thật**

```bash
set -a && source .env && set +a
export WAREHOUSE_DB=md:vn_market
export motherduck_token="$MOTHERDUCK_TOKEN"
.venv/bin/python -m scripts.check_mcp_tools
```

Expected: cả 7 tool trả dữ liệu, rào chắn chặn `DROP`, exit code 0.

- [ ] **Step 4: Kiểm tra server khởi động được ở chế độ stdio**

```bash
.venv/bin/python -c "
import mcp_server.server as s
names = sorted(t.name for t in s.mcp._tool_manager.list_tools())
print(names)
assert len(names) == 7, f'Cần 7 tool, có {len(names)}'
print('OK — 7 tool đã đăng ký')
"
```

Expected: in ra 7 tên tool.

- [ ] **Step 5: Bật MCP trong Claude Code và thử hỏi thật**

Khởi động lại Claude Code trong thư mục repo (`.mcp.json` được đọc tự động), rồi hỏi:

1. *"Top 10 mã theo profile bluechip_dividend, có ngân hàng nào không?"*
2. *"HPG đang rẻ hay đắt so với 5 năm qua?"*
3. *"So sánh HPG với VCB"* — phải nhận được cảnh báo khác loại hình.

Expected: agent trả lời có số liệu, nêu `as_of` và `peer_basis`, **không** đưa khuyến nghị mua/bán.

- [ ] **Step 6: Cập nhật `README.md`**

Thay phần "Kiến trúc" bằng:

```markdown
## Kiến trúc

Hai nhánh độc lập, dùng chung một warehouse trên MotherDuck:

```
INGESTION (Python)                WAREHOUSE            CONSUMERS
build_warehouse.py --mode         raw_* (immutable)    ├─ MCP server (hội thoại)
  daily   → giá EOD + chỉ số        ↓ dbt              ├─ main.py (bản tin Telegram)
  weekly  → tỷ số tài chính       stg_* → int_*        └─ SQL ad-hoc
  monthly → hồ sơ DN + ICB          ↓
                                  mart_* ← nơi mọi phân tích query vào
```

- `transforms/` — dbt project (staging → intermediate → marts)
- `src/scoring.py` + `config/scoring_profiles.yml` — bộ chấm điểm, đổi "gu" đầu tư ở đây
- `mcp_server/` — 7 tool read-only cho luồng hội thoại

### Bật/tắt luồng hội thoại

Xoá khai báo trong `.mcp.json` là tắt hoàn toàn MCP server. Warehouse, dbt và
bản tin Telegram không bị ảnh hưởng.

### Chạy screener bằng dòng lệnh

```bash
export WAREHOUSE_DB=md:vn_market
python -c "
from src import warehouse, scoring
con = warehouse.get_conn()
print(scoring.screen(con, 'bluechip_dividend', limit=20).to_string())
"
```
```

- [ ] **Step 7: Chạy toàn bộ test và commit**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — 110 passed

```bash
git add .mcp.json README.md scripts/check_mcp_tools.py mcp_server/
git commit -m "feat(mcp): đăng ký server + script nghiệm thu 7 tool

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Tiêu chí hoàn thành plan A3

| # | Tiêu chí | Cách kiểm tra |
|---|---|---|
| 1 | 110 test pytest pass | `.venv/bin/python -m pytest tests/ -q` |
| 2 | 7 tool đăng ký đầy đủ | Task 4 Step 4 |
| 3 | Cả 7 tool trả dữ liệu thật | `python -m scripts.check_mcp_tools` |
| 4 | `run_sql` từ chối DDL/DML | Task 4 Step 3 |
| 5 | Mọi tool trả kèm `as_of` và `data_quality` | Task 4 Step 3 |
| 6 | `compare_stocks` cảnh báo khi khác `com_class` | test + Task 4 Step 5 |
| 7 | Agent trả lời trong Claude Code, nêu `as_of`, không khuyến nghị mua/bán | Task 4 Step 5 |
| 8 | Xoá `.mcp.json` không ảnh hưởng warehouse hay bản tin | thử `python build_warehouse.py --mode daily` |

Sau khi đạt hết, mảng A hoàn tất. Các mảng tiếp theo (spec riêng):
**B** — BCTC chi tiết, sự kiện & cổ tức, khối ngoại ·
**C** — báo cáo luận điểm định kỳ + cảnh báo theo sự kiện ·
**D** — vĩ mô + kho tin & cơ chế scan.
