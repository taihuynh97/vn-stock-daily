"""Test cho mcp_server/server.py — chủ yếu kiểm tool run_sql không sập khi
gặp lỗi (bảng/cột không tồn tại, SQL bị rào chắn chặn, ...).

`@mcp.tool()` (FastMCP) trả về đúng hàm gốc sau khi đăng ký (không bọc lại),
nên gọi trực tiếp `server.run_sql(...)` tương đương gọi qua MCP runtime.
"""
import duckdb
import pytest

from mcp_server import server


@pytest.fixture
def bare_con(tmp_path):
    """Kết nối KHÔNG có các bảng mart — mô phỏng warehouse local chưa build
    (tình huống làm run_sql sập trước khi sửa, vì as_of() truy vấn vô điều
    kiện fct_price_daily/fct_financial_quarterly)."""
    path = tmp_path / "bare.duckdb"
    c = duckdb.connect(str(path))
    c.execute("CREATE TABLE t (a INTEGER)")
    c.execute("INSERT INTO t VALUES (1), (2)")
    yield c
    c.close()


@pytest.fixture
def full_con(tmp_path):
    """Kết nối có đủ bảng mart tối thiểu để as_of() chạy được."""
    path = tmp_path / "full.duckdb"
    c = duckdb.connect(str(path))
    c.execute("CREATE TABLE fct_price_daily (trade_date DATE)")
    c.execute("INSERT INTO fct_price_daily VALUES ('2026-01-01')")
    c.execute("CREATE TABLE fct_financial_quarterly (period_end_date DATE)")
    c.execute("INSERT INTO fct_financial_quarterly VALUES ('2025-12-31')")
    c.execute("CREATE TABLE t (a INTEGER)")
    c.execute("INSERT INTO t VALUES (1), (2), (3)")
    yield c
    c.close()


def test_run_sql_missing_mart_table_returns_error_not_crash(bare_con, monkeypatch):
    """Trước khi sửa: SELECT 1 hợp lệ vẫn làm run_sql ném exception ra ngoài
    vì as_of() gọi vô điều kiện và bảng fct_price_daily chưa tồn tại."""
    monkeypatch.setattr(server, "conn", lambda: bare_con)
    result = server.run_sql("SELECT 1")
    assert "error" in result
    assert result["rows"] == []


def test_run_sql_unknown_table_returns_error_not_crash(full_con, monkeypatch):
    monkeypatch.setattr(server, "conn", lambda: full_con)
    result = server.run_sql("SELECT * FROM khong_ton_tai")
    assert "error" in result
    assert result["rows"] == []


def test_run_sql_success_includes_as_of(full_con, monkeypatch):
    monkeypatch.setattr(server, "conn", lambda: full_con)
    result = server.run_sql("SELECT a FROM t ORDER BY a")
    assert result["rows"] == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert result["row_count"] == 3
    assert result["price_as_of"] == "2026-01-01"
    assert result["ratio_as_of"] == "2025-12-31"
    assert "error" not in result


def test_run_sql_blocks_write_and_returns_error(full_con, monkeypatch):
    monkeypatch.setattr(server, "conn", lambda: full_con)
    result = server.run_sql("DELETE FROM t")
    assert "error" in result
    assert result["rows"] == []
    assert full_con.execute("SELECT count(*) FROM t").fetchone()[0] == 3
