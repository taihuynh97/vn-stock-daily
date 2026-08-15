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
