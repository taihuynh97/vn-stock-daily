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
