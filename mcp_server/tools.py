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


def _data_quality(con, sym: str) -> dict:
    """Tín hiệu chất lượng dữ liệu cho một mã — cùng khuôn dict với
    `data_quality` của `get_stock_profile` ({data_quality_score,
    quality_flags, reliable}), tái dùng cho cả `get_valuation_history` và
    `get_financial_history` (fix round 1: reviewer phát hiện 2 hàm này
    thiếu tín hiệu `data_quality` mà Global Constraint của kế hoạch A3 yêu
    cầu MỌI tool phải trả kèm `as_of` và `data_quality`).

    Dùng một query riêng vào `mart_data_quality` — nguồn canonical cho chỉ
    tiêu này (liệt kê riêng trong docstring `run_sql`, tách khỏi
    `mart_stock_scorecard`) — thay vì JOIN thẳng vào query lịch sử của 2
    hàm gọi nó. Data quality là thuộc tính của MÃ tại thời điểm hiện tại,
    không phải của từng kỳ quá khứ; JOIN theo từng dòng `history` sẽ lặp
    lại đúng một giá trị trên mọi dòng và dễ khiến agent hội thoại hiểu
    nhầm nó thay đổi theo quý — để ở top-level của response tránh nhầm lẫn
    này, đúng gợi ý của reviewer.

    Không có dòng khớp (mã không có trong `mart_data_quality`) → trả về
    điểm 0/`reliable=False` thay vì lỗi, cùng cách `get_stock_profile` xử
    lý `data_quality_score` NULL (`r.get(...) or 0`)."""
    rows = db.run_query(
        con,
        "SELECT data_quality_score, quality_flags FROM mart_data_quality WHERE symbol = ?",
        params=[sym],
        limit=1,
    )
    dq_score = (rows[0].get("data_quality_score") or 0) if rows else 0
    flags = (rows[0].get("quality_flags") or "") if rows else ""
    return {
        "data_quality_score": dq_score,
        "quality_flags": flags,
        "reliable": dq_score >= RELIABLE_MIN,
    }


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


def get_valuation_history(con, symbol: str, years: int = 5) -> dict:
    """Chuỗi P/E, P/B theo quý kèm percentile so với chính mã và nhãn vùng."""
    sym = symbol.upper().strip()
    rows = db.run_query(
        con,
        """
        SELECT period_end_date, pe, pb, ps, pe_pct_own_5y, pb_pct_own_5y,
               pe_quarters_used, pb_quarters_used, valuation_band, com_class, industry_lv2
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
    # `period_end_date` là cột DATE đọc qua `.df()` nên ra `pandas.Timestamp`
    # — `_clean()` sẽ gọi `.isoformat()` trên nó và rò rỉ artifact
    # "T00:00:00" (xem docstring `_date_str`). Chuẩn hoá từng dòng trước khi
    # `_clean()` để tái dùng đúng helper thay vì lặp lại logic tương tự.
    for r in rows:
        r["period_end_date"] = _date_str(r.get("period_end_date"))
    return {
        "symbol": sym,
        "com_class": rows[0].get("com_class"),
        "industry": rows[0].get("industry_lv2"),
        "history": _clean(rows),
        "data_quality": _data_quality(con, sym),
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
    # Cùng lý do chuẩn hoá DATE như get_valuation_history ở trên.
    for r in rows:
        r["period_end_date"] = _date_str(r.get("period_end_date"))
    return {
        "symbol": sym,
        "history": _clean(rows),
        "data_quality": _data_quality(con, sym),
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
    # Cùng lý do chuẩn hoá DATE như get_valuation_history ở trên.
    for r in rows:
        r["period_end_date"] = _date_str(r.get("period_end_date"))
    return {"sectors": _clean(rows),
            "note": "Trung vị tính trong cùng com_class — không so ngân hàng "
                    "với doanh nghiệp sản xuất.",
            **db.as_of(con)}
