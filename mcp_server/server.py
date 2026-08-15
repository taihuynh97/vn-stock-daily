"""MCP server — hỏi đáp với warehouse phân tích cơ bản VN.

Chạy:
    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m mcp_server.server

Tắt luồng này: xoá khai báo trong .mcp.json. Warehouse và job báo cáo
không bị ảnh hưởng.
"""
import functools
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

from mcp_server import db
from mcp_server import tools

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


def _safe_tool(fn):
    """Bọc mọi tool: bắt toàn bộ exception, trả {"error": ..., "rows": []}.

    Agent hội thoại gõ sai tên bảng/cột là chuyện thường — lỗi đó phải trả
    về dạng lỗi sạch để agent tự sửa câu hỏi, không phải làm tool sập
    (SqlGuardError chỉ là một loại lỗi trong nhiều loại có thể xảy ra:
    tên bảng/cột sai, bảng chưa tồn tại khi as_of() truy vấn, v.v.).
    Task 2/3 thêm tool mới nên dùng lại decorator này thay vì tự viết
    try/except riêng.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"error": str(e), "rows": []}
    return wrapper


@mcp.tool()
@_safe_tool
def run_sql(query: str, limit: int = 200) -> dict:
    """Chạy một truy vấn SELECT read-only trên warehouse.

    Dùng khi 6 tool chuyên biệt không trả lời được câu hỏi. Chỉ chấp nhận
    một câu lệnh SELECT/WITH; mọi lệnh ghi đều bị từ chối.

    Bảng chính: dim_stock, dim_industry_hierarchy, fct_price_daily,
    fct_financial_quarterly, mart_valuation_band, mart_sector_snapshot,
    mart_stock_scorecard, mart_data_quality.
    """
    c = conn()
    rows = db.run_query(c, query, limit=min(limit, 1000))
    return {"rows": rows, "row_count": len(rows), **db.as_of(c)}


@mcp.tool()
@_safe_tool
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
@_safe_tool
def get_stock_profile(symbol: str) -> dict:
    """Hồ sơ đầy đủ một mã: ngành, loại hình, 5 điểm, định giá, chất lượng dữ liệu.

    Luôn kiểm tra data_quality.reliable trước khi kết luận về mã này.
    """
    return tools.get_stock_profile(conn(), symbol)


@mcp.tool()
@_safe_tool
def get_valuation_history(symbol: str, years: int = 5) -> dict:
    """P/E, P/B theo quý kèm percentile so với chính mã và nhãn vùng định giá.

    Dùng để trả lời "mã này đang rẻ hay đắt so với quá khứ của chính nó".
    """
    return tools.get_valuation_history(conn(), symbol, years)


@mcp.tool()
@_safe_tool
def get_financial_history(symbol: str, quarters: int = 12) -> dict:
    """Tỷ số theo quý + doanh thu/LNST suy ra + tăng trưởng YoY."""
    return tools.get_financial_history(conn(), symbol, quarters)


@mcp.tool()
@_safe_tool
def compare_stocks(symbols: list[str]) -> dict:
    """So sánh nhiều mã cạnh nhau. Cảnh báo khi các mã khác loại hình DN."""
    return tools.compare_stocks(conn(), symbols)


@mcp.tool()
@_safe_tool
def get_sector_snapshot(com_class: str = None) -> dict:
    """Trung vị P/E, P/B, ROE và suất sinh lời 3 tháng theo ngành ICB cấp 2.

    com_class: để trống = mọi loại hình; 'BANK' / 'NONFIN' / 'OTHERFIN'.
    """
    return tools.get_sector_snapshot(conn(), com_class)


if __name__ == "__main__":
    mcp.run()
