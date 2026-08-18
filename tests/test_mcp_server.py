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
from tests.conftest_mart import build_fake_mart


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


@pytest.fixture
def b1_con(tmp_path):
    """Kết nối có đủ 4 bảng B1 + bảng mart tối thiểu cho as_of().

    CỐ Ý KHÔNG dùng fixture `full_con` sẵn có: nó chỉ dựng fct_price_daily,
    fct_financial_quarterly và bảng t — không có int_distribution_event hay
    int_ownership_snapshot. Tool gọi trên đó sẽ ném "table not found",
    _safe_tool nuốt thành {"error": ...}, và một assertion lỏng kiểu
    `assert content is not None` VẪN XANH — tức test không bao giờ đỏ được,
    đúng lỗi "test không thể đỏ" của A2 Task 11. Dùng build_fake_mart để
    fixture khớp schema thật (bài học A3 I2).
    """
    path = str(tmp_path / "b1.duckdb")
    build_fake_mart(path)
    c = duckdb.connect(path)
    yield c
    c.close()


def test_get_ownership_via_mcp_call_tool(b1_con, monkeypatch):
    """Bài học A3 I1: crash ở tầng serialize JSON của FastMCP xảy ra SAU khi
    hàm đã return, nên _safe_tool không bắt được và test gọi hàm Python trần
    không thấy. Phải gọi đúng qua mcp.call_tool().
    """
    monkeypatch.setattr(server, "conn", lambda: b1_con)

    content = asyncio.run(
        server.mcp.call_tool("get_ownership", {"symbol": "AAA"})
    )
    payload = json.loads(content[0].text)

    assert "error" not in payload
    assert payload["symbol"] == "AAA"
    assert len(payload["major_shareholders"]) == 3
    assert payload["concentration"]["total_disclosed_pct"] == 0.5189
    assert payload["snapshot_date"] == "2026-08-01"


def test_get_distribution_history_via_mcp_call_tool(b1_con, monkeypatch):
    """Cùng lý do như trên. Fixture cố tình có `payout_date` NULL thật (cổ
    tức bằng cổ phiếu không có ngày chi trả) và `cash_per_share` NULL —
    đúng loại giá trị làm serialize vỡ nếu không đi qua _clean/_date_str.
    """
    monkeypatch.setattr(server, "conn", lambda: b1_con)

    content = asyncio.run(
        server.mcp.call_tool("get_distribution_history",
                             {"symbol": "AAA", "years": 5})
    )
    payload = json.loads(content[0].text)

    assert "error" not in payload
    assert len(payload["distribution_events"]) == 3
    # NULL phải ra None, KHÔNG phải chuỗi "NaT" hay "NaN"
    stock_div = next(e for e in payload["distribution_events"]
                     if e["distribution_type"] == "STOCK_DIVIDEND")
    assert stock_div["cash_per_share"] is None
    assert stock_div["payout_date"] is None
    assert payload["data_quality"]["n_events"] == 3


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
