"""Kết nối read-only và rào chắn SQL cho MCP server.

Ba lớp bảo vệ độc lập:
  1. Kết nối read-only ở tầng DuckDB (nếu backend hỗ trợ).
  2. `enable_external_access=false` — chặn mọi hàm bảng đọc file/mạng của
     DuckDB (read_text, read_csv, glob, httpfs, ...). Từ khoá SQL không bắt
     được các hàm này vì chúng không phải lệnh ghi; đây là lớp chặn đúng chỗ.
  3. Rào chắn từ khoá ở tầng ứng dụng — luôn áp dụng, kể cả khi (1)/(2) thất bại.
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
# Đã tra `duckdb_functions()` trên md:vn_market thật cho toàn bộ 20 từ trong
# FORBIDDEN (không chỉ vá đúng checkpoint). Chỉ 2 cái trùng tên với một hàm/
# table-function DuckDB thật:
#   - checkpoint (table function, has_side_effects, flush WAL ra đĩa) —
#     nguy hiểm thật, KHÔNG thêm vào allowlist, vẫn bị chặn khi gọi
#     checkpoint(...).
#   - replace (scalar function thuần, "Replaces any occurrences of source
#     with target in string") — vô hại, đã xác minh trên dữ liệu thật
#     (replace(symbol,'A','B') trên mart_stock_scorecard).
# 18 từ còn lại (insert/update/delete/drop/create/alter/attach/detach/copy/
# install/load/pragma/set/export/import/truncate/call/vacuum) không phải
# tên hàm/table-function nào trong duckdb_functions() — chúng chỉ có nghĩa
# như từ khoá đầu câu lệnh SQL, không có cú pháp gọi word(...) nào để lo.
SAFE_FUNCTIONS = {"replace"}
_WORD = re.compile(r"[a-z_]+")
# Một lượt duy nhất cho cả string literal / line comment / block comment —
# tránh nhập nhằng thứ tự (regex chạy tuần tự trước đó khiến `--` bên trong
# chuỗi '--' bị hiểu nhầm thành comment thật, ăn lố qua cả dấu ';' và lệnh
# ghi phía sau). Alternation quét trái sang phải, mỗi vị trí chỉ khớp đúng
# MỘT khả năng dựa vào ký tự thật tại đó — giống lexer thật, không có
# trường hợp pattern sau "nhìn xuyên" qua pattern trước.
_NOISE = re.compile(r"(?P<string>'[^']*')|(?P<line>--[^\n]*)|(?P<block>/\*.*?\*/)", re.DOTALL)
# Từ khoá cấm chỉ tính khi:
#   (a) đứng đầu câu (words[0], kiểm riêng bên dưới), hoặc
#   (b) đứng ngay sau một dấu "(" mở đầu — vị trí CTE/sub-statement bắt đầu
#       (kiểu "AS (DELETE ...)"), hoặc
#   (c) đứng ngay TRƯỚC dấu "(" của chính nó — đang được gọi như hàm/
#       table-function (kiểu "checkpoint()"), trừ khi nằm trong
#       SAFE_FUNCTIONS.
# Đứng ở vị trí khác (tên cột trong SELECT list, ...) là vô hại và KHÔNG bị
# chặn.
_PAREN_WORD = re.compile(r"\(\s*([a-z_]+)")
_CALL_WORD = re.compile(r"([a-z_]+)\s*\(")


def _strip_noise(query: str) -> str:
    """Xoá string literal + comment (--, /* */) trong một lượt quét."""
    def repl(m: re.Match) -> str:
        if m.group("string") is not None:
            return "''"
        return " "
    return _NOISE.sub(repl, query)


class SqlGuardError(RuntimeError):
    """Câu lệnh SQL bị từ chối vì không phải truy vấn đọc."""


def assert_safe_sql(query: str) -> None:
    """Chỉ cho phép một câu SELECT/WITH duy nhất."""
    if not query or not query.strip():
        raise SqlGuardError("Câu truy vấn rỗng.")

    stripped = _strip_noise(query)
    body = stripped.strip().rstrip(";")

    if ";" in body:
        raise SqlGuardError("Chỉ cho phép một câu lệnh duy nhất.")

    lowered = body.lower()
    words = _WORD.findall(lowered)
    if not words or words[0] not in {"select", "with"}:
        raise SqlGuardError("Chỉ chấp nhận câu lệnh bắt đầu bằng SELECT hoặc WITH.")

    paren_hit = {m.group(1) for m in _PAREN_WORD.finditer(lowered)} & FORBIDDEN
    call_hit = ({m.group(1) for m in _CALL_WORD.finditer(lowered)} & FORBIDDEN) - SAFE_FUNCTIONS
    hit = paren_hit | call_hit
    if hit:
        raise SqlGuardError(f"Câu lệnh chứa từ khoá bị cấm: {sorted(hit)}")


def get_readonly_conn():
    """Trả (connection, is_readonly).

    MotherDuck có thể không nhận read_only — khi đó vẫn kết nối được nhưng
    is_readonly=False, và rào chắn SQL ở tầng ứng dụng là lớp bảo vệ duy nhất.

    Cả hai nhánh đều tắt enable_external_access ngay sau khi connect (không
    được truyền qua config= lúc connect — làm MotherDuck lỗi khi nạp
    extension). Đây là chặn đọc file/mạng (read_text, read_csv, glob,
    httpfs, ...) — độc lập với rào chắn từ khoá ghi ở assert_safe_sql.
    """
    root = Path(__file__).resolve().parent.parent
    dbpath = os.getenv("WAREHOUSE_DB", str(root / "data" / "warehouse.duckdb"))
    try:
        con = duckdb.connect(dbpath, read_only=True)
        is_readonly = True
    except Exception:
        con = duckdb.connect(dbpath)
        is_readonly = False
    con.execute("SET enable_external_access=false")
    return con, is_readonly


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
