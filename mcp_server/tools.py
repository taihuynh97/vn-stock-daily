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


def _date_str(v):
    """Chuẩn hoá cột kiểu DATE của DuckDB về "YYYY-MM-DD".

    `db.run_query` đọc kết quả qua `.df()` (pandas) nên cột SQL kiểu DATE
    (không có giờ) trở thành `pandas.Timestamp` thay vì `datetime.date` —
    `Timestamp.isoformat()` luôn trả kèm phần giờ "...T00:00:00" dù cột
    gốc không có khái niệm giờ. Đã tự phát hiện lỗi này khi test
    `price_as_of` kỳ vọng "2026-08-07" nhưng nhận "2026-08-07T00:00:00".
    Cắt về `.date()` trước khi isoformat để không rò rỉ artifact của bước
    chuyển đổi pandas ra ngoài — chỉ dùng cho các cột đã biết chắc là
    DATE (price_as_of, ratio_as_of, listed_date), không sửa `_clean()`
    dùng chung vì đó là hàm tổng quát, không nên giả định mọi giá trị có
    `.isoformat()` đều là DATE (một TIMESTAMP thật đúng lúc nửa đêm sẽ bị
    cắt nhầm nếu áp logic này toàn cục).

    Fix round 1 (code review): guard NULL trước đây chỉ bắt
    `isinstance(v, float) and pd.isna(v)` — bỏ sót `pandas.NaT`
    (kiểu `NaTType`, KHÔNG phải `float`). Một mã thiếu lịch sử định giá
    (`ratio_as_of` NULL thật, vd mã mới niêm yết <12 quý — đúng kịch bản
    CCC trong fixture, chỉ là fixture cũ tình cờ không gán NULL) đọc qua
    `.df()` cho `v = pd.NaT`, lọt qua guard cũ, rồi `hasattr(v, "date")`
    và `hasattr(v, "isoformat")` đều True trên `NaT` (nó tự trả về chính
    nó ở `.date()`), kết quả cuối là chuỗi literal `"NaT"` thay vì `None`
    — sai gấp đôi: vừa không phải None, vừa là text vô nghĩa nếu agent
    hội thoại đọc thẳng. `pd.isna(v)` (không giới hạn kiểu) nhận diện
    đúng cả `None`, `float('nan')`, lẫn `NaT` nên dùng thẳng nó làm điều
    kiện duy nhất, bỏ nhánh `isinstance(v, float)` thừa."""
    if v is None or pd.isna(v):
        return None
    if hasattr(v, "date"):
        v = v.date()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


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
        # rejected_counts đếm theo TỪNG điều kiện, CHO PHÉP CHỒNG LẤP — một mã
        # trượt cả sàn lẫn vốn hoá được cộng vào cả hai khoá (đo thực tế:
        # 85,5-96,4% mã bị loại trượt ≥2 điều kiện, xem docstring
        # scoring.screen_report). Không phơi rejected_total kèm nó thì agent
        # hội thoại rất dễ tự cộng rejected_counts rồi báo sai tổng số mã bị
        # loại cho người dùng — đúng lỗi đã sửa ở A2 Task 11.
        "rejected_counts": report["rejected_counts"],
        "rejected_total": report["rejected_total"],
        "unscored": _clean(report["unscored"].to_dict(orient="records")),
        "results": results,
        "note": "rejected_counts đếm chồng lấp theo điều kiện, KHÔNG cộng lại "
                "thành tổng — dùng rejected_total cho tổng số mã bị loại thật.",
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

    raw = rows[0]
    r = _clean(raw)
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
        "listed_date": _date_str(raw.get("listed_date")),
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
        "ratio_as_of": _date_str(raw.get("ratio_as_of")),
        "price_as_of": _date_str(raw.get("price_as_of")),
    }
