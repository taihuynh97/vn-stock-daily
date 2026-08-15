"""Test cho mcp_server/server.py — chủ yếu kiểm tool run_sql không sập khi
gặp lỗi (bảng/cột không tồn tại, SQL bị rào chắn chặn, ...).

`@mcp.tool()` (FastMCP) trả về đúng hàm gốc sau khi đăng ký (không bọc lại),
nên gọi trực tiếp `server.run_sql(...)` tương đương gọi qua MCP runtime CHO
PHẦN THÂN HÀM — nhưng KHÔNG tương đương cho tầng serialize JSON của giao
thức MCP thật, thứ chỉ chạy khi gọi qua `mcp.call_tool()` (xem I1 bên dưới:
toàn bộ 4 task trước gọi `server.run_sql(...)` trần nên không phát hiện được
lớp lỗi serialize DATE NULL/NaN — `_safe_tool` cũng không bắt được vì lỗi đó
xảy ra ở FastMCP, SAU KHI hàm đã return).
"""
import asyncio
import json

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
    # M2 (fix round cuối): payload lỗi chung của _safe_tool không còn khoá
    # "rows" — 6/7 tool không dùng khoá này trong response thành công, giữ
    # nó trong payload lỗi dễ khiến agent hiểu nhầm "không có dữ liệu" thay
    # vì "tool bị lỗi".
    assert "rows" not in result


def test_run_sql_unknown_table_returns_error_not_crash(full_con, monkeypatch):
    monkeypatch.setattr(server, "conn", lambda: full_con)
    result = server.run_sql("SELECT * FROM khong_ton_tai")
    assert "error" in result
    assert "rows" not in result


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
    assert "rows" not in result
    assert full_con.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_run_sql_via_mcp_call_tool_handles_null_date_column(full_con, monkeypatch):
    """I1 — test bắt buộc của vòng sửa cuối: gọi ĐÚNG qua `mcp.call_tool()`
    (giao thức MCP thật), KHÔNG phải `server.run_sql(...)` trần như mọi
    test khác trong file này. Đây chính xác là lớp lỗi mà 4 task trước
    không phát hiện được: gọi hàm Python trần đi vòng qua tầng serialize
    JSON của FastMCP, nơi lỗi thật xảy ra.

    Trước khi sửa (run_sql trả thẳng dòng thô từ db.run_query, không qua
    tools._clean()): cột DATE NULL đọc qua `.df()` ra `pandas.NaT`, và
    FastMCP CRASH thật khi serialize response (`ToolError: Error executing
    tool run_sql: Error serializing to JSON: TypeError: 'float' object
    cannot be interpreted as an integer`) — đã tự tái tạo bằng chính đoạn
    test này trước khi vá. `_safe_tool` KHÔNG bắt được vì lỗi xảy ra ở
    FastMCP SAU KHI run_sql đã return xong, không phải trong thân hàm.

    Sau khi sửa (run_sql đi qua tools._clean()): không crash, NULL → None
    (không phải chuỗi "NaT"), giá trị DATE không NULL vẫn đọc được (có thể
    kèm artifact "T00:00:00" — chấp nhận được, xem comment trong
    server.run_sql)."""
    full_con.execute("CREATE TABLE u (a INTEGER, d DATE)")
    full_con.execute("INSERT INTO u VALUES (1, NULL), (2, DATE '2026-01-01')")
    monkeypatch.setattr(server, "conn", lambda: full_con)

    # server.mcp.call_tool() là API thật của FastMCP — đúng đường mà một
    # client MCP (Claude Code) gọi tool, bao gồm cả bước serialize kết quả
    # về content block mà `server.run_sql(...)` gọi trần không đi qua.
    content = asyncio.run(
        server.mcp.call_tool("run_sql", {"query": "SELECT a, d FROM u ORDER BY a"})
    )

    # FastMCP trả list[TextContent] cho tool không khai output_schema (đã
    # tự xác nhận thực nghiệm hình dạng này trước khi viết assertion) — đọc
    # payload JSON từ .text của khối đầu tiên.
    payload = json.loads(content[0].text)

    assert "error" not in payload
    rows = payload["rows"]
    assert rows[0]["a"] == 1
    assert rows[0]["d"] is None          # NULL phải ra None, KHÔNG phải "NaT"
    assert rows[1]["a"] == 2
    assert rows[1]["d"].startswith("2026-01-01")   # T00:00:00 chấp nhận được
