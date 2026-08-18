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
    """Bọc mọi tool: bắt toàn bộ exception, trả {"error": ...}.

    Agent hội thoại gõ sai tên bảng/cột là chuyện thường — lỗi đó phải trả
    về dạng lỗi sạch để agent tự sửa câu hỏi, không phải làm tool sập
    (SqlGuardError chỉ là một loại lỗi trong nhiều loại có thể xảy ra:
    tên bảng/cột sai, bảng chưa tồn tại khi as_of() truy vấn, v.v.).
    Task 2/3 thêm tool mới nên dùng lại decorator này thay vì tự viết
    try/except riêng.

    Payload lỗi CHỈ có khoá "error" (fix round cuối, M2): bản trước kèm
    thêm "rows": [] cho MỌI tool, nhưng 6/7 tool không dùng khoá "rows"
    trong response THÀNH CÔNG của chúng (dùng "results"/"history"/
    "stocks"/"sectors") — agent đọc {"rows": []} từ, vd, get_sector_snapshot
    dễ hiểu nhầm thành "ngành không có dữ liệu" thay vì "tool bị lỗi". Bỏ
    khoá dữ liệu khỏi payload lỗi chung; "error" đã đủ để agent nhận biết
    và tự sửa câu hỏi.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"error": str(e)}
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
    # I1 (fix round cuối): run_sql là tool DUY NHẤT từng trả thẳng dòng thô
    # từ db.run_query (df.to_dict()) — không qua tools._clean() như 6 tool
    # còn lại. Cột DATE NULL đọc qua .df() ra pandas.NaT; cột double NULL ra
    # float('nan'); FastMCP serialize response qua JSON ở TẦNG SAU khi hàm
    # đã return — NaT làm nó CRASH thật (ToolError: "'float' object cannot
    # be interpreted as an integer"), NaN lọt ra ngoài thành literal `NaN`
    # (JSON không hợp lệ theo RFC 8259). _safe_tool KHÔNG bắt được lớp lỗi
    # này vì nó xảy ra sau khi run_sql đã return xong. Cho rows đi qua
    # _clean() để đóng cả hai: NaT/NaN → None. Ca DATE literal không NULL sẽ
    # còn lộ artifact "T00:00:00" (Timestamp.isoformat()) — chấp nhận được,
    # vì run_sql chạy SQL tuỳ ý, không biết trước cột nào là DATE để tự cắt
    # bằng _date_str() như 6 tool chuyên biệt kia.
    rows = tools._clean(rows)
    return {"rows": rows, "row_count": len(rows), **db.as_of(c)}


@mcp.tool()
@_safe_tool
def search_stocks(profile: str = "bluechip_dividend", limit: int = 20,
                  min_composite: float = None) -> dict:
    """Quét toàn thị trường theo hồ sơ đầu tư, trả danh sách xếp hạng.

    profile: 'bluechip_dividend' (bluechip + cổ tức, dài hạn),
             'deep_value' (định giá sâu, mở rộng xuống mid-cap),
             'quality_growth' (chất lượng + tăng trưởng).
    min_composite: lọc composite_score >= ngưỡng này trên TOÀN VŨ TRỤ mã hợp
             lệ của profile (mọi mã đã qua sàng lọc universe, không chỉ
             top `limit`), RỒI mới cắt kết quả về `limit`. VD limit=20,
             min_composite=70 có thể trả ít hơn 20 mã nếu không đủ mã đạt
             ngưỡng, nhưng không bao giờ bỏ sót một mã đạt ngưỡng chỉ vì nó
             xếp ngoài top-20 theo composite thô.

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


@mcp.tool()
@_safe_tool
def get_distribution_history(symbol: str, years: int = 5) -> dict:
    """Lịch sử phân phối cho cổ đông: cổ tức tiền mặt, cổ tức bằng cổ phiếu,
    cổ phiếu thưởng, kèm ngày giao dịch không hưởng quyền (GDKHQ).

    Trả HAI KHỐI trên HAI TRỤC THỜI GIAN khác nhau — đọc kỹ trường 'note'
    trước khi phát biểu. Luôn nêu data_quality.event_window_years khi nói về
    chuỗi cổ tức: nguồn chỉ nhìn được 50 sự kiện gần nhất, với mã năng động
    cửa sổ đó có thể chỉ 1-2 năm dù doanh nghiệp trả cổ tức đều hàng chục năm.
    """
    return tools.get_distribution_history(conn(), symbol, years)


@mcp.tool()
@_safe_tool
def get_ownership(symbol: str) -> dict:
    """Cơ cấu sở hữu đã công bố: cổ đông lớn, ban lãnh đạo, mức độ cô đặc.

    Tổng tỉ lệ công bố KHÔNG bằng 100% — không suy ra phần còn lại là free
    float.
    """
    return tools.get_ownership(conn(), symbol)


@mcp.tool()
@_safe_tool
def get_financial_statement(symbol: str, statement_type: str,
                            period_type: str = "quarter") -> dict:
    """Chi tiết một báo cáo tài chính, mỗi dòng kèm chuỗi giá trị theo kỳ.

    statement_type: 'income_statement' (kết quả kinh doanh) /
                     'balance_sheet' (cân đối kế toán) /
                     'cash_flow' (lưu chuyển tiền tệ).
    period_type: 'quarter' (8 quý gần nhất, mặc định) / 'year' (8 năm gần nhất).

    Một số item_id (ví dụ 'cost'/'accumulated_depreciation' ở
    balance_sheet) XUẤT HIỆN NHIỀU LẦN trong cùng báo cáo — mỗi lần một
    nhóm tài sản khác nhau, phân biệt bởi item_vi (tên tiếng Việt), không
    phải item_id. Luôn hiển thị item_vi cho người dùng.

    Kiểm data_quality.has_data trước khi kết luận — một số mã (đặc biệt
    vốn hoá nhỏ) không có BCTC nào qua nguồn này.
    """
    return tools.get_financial_statement(conn(), symbol, statement_type, period_type)


if __name__ == "__main__":
    mcp.run()
