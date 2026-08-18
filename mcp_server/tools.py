"""Cài đặt các tool — tách khỏi server.py để test được mà không cần MCP runtime."""
import json
from datetime import date

import numpy as np
import pandas as pd

from mcp_server import db
from src import scoring

RELIABLE_MIN = 60

# search_stocks(min_composite=...) cần lọc trên TOÀN VŨ TRỤ mã hợp lệ của
# profile trước khi cắt về `limit` — screen_report() tự head(limit) bên
# trong, nên phải gọi nó với một limit đủ lớn để không cắt mất mã đạt
# ngưỡng trước khi lọc (xem search_stocks() bên dưới). ~1.600 mã niêm yết
# HOSE+HNX+UPCOM hiện tại trên VN, hằng số này chừa dư nhiều lần.
_SCREEN_LIMIT_FOR_FILTER = 10_000


def _clean(obj):
    """Đưa giá trị pandas/numpy về kiểu JSON được.

    Cột kiểu LIST/ARRAY của DuckDB đọc qua `.df()` ra `numpy.ndarray`, KHÔNG
    phải `list` Python — bản cũ chỉ kiểm `isinstance(obj, list)` nên một
    ndarray lọt xuống nhánh `pd.isna(obj)` gọi trên cả mảng, trả về một mảng
    bool (không phải một giá trị đơn), rồi `if <mảng nhiều phần tử>:` (ẩn
    trong biểu thức điều kiện) ném ValueError "truth value of an array...
    is ambiguous". Tái tạo bằng `select [1,2,3] as l` qua `run_sql` — lộ ra
    khi I1 cho `run_sql` đi qua `_clean()` (agent có thể SELECT một cột
    LIST bất kỳ lúc nào). Sửa bằng cách gộp `list`/`np.ndarray` vào MỘT
    nhánh đệ quy theo phần tử, đặt TRƯỚC mọi lời gọi `pd.isna()` — nhánh đó
    không bao giờ còn nhận một mảng làm tham số."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, np.ndarray)):
        return [_clean(v) for v in obj]
    if obj is None:
        return None
    if pd.isna(obj):
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
    """Chạy screener theo profile, trả danh sách xếp hạng.

    `min_composite` (nếu có) phải lọc trên TOÀN VŨ TRỤ mã hợp lệ của
    profile, không phải trên top `limit` mã đã bị `screen_report()` cắt sẵn
    — `screen_report()` tự `.head(limit)` bên trong TRƯỚC khi trả về
    (src/scoring.py). Gọi thẳng nó với `limit` gốc rồi mới lọc
    `min_composite` sẽ khiến một mã đạt ngưỡng nhưng xếp hạng ngoài top
    `limit` (theo composite thô, chưa lọc) bị cắt mất trước khi kịp lọc —
    agent hội thoại dễ đọc `len(results) < limit` thành "chỉ có từng đó mã
    đạt ngưỡng" trong khi thực ra chưa chắc đã quét hết vũ trụ. Khi có
    `min_composite`, gọi `screen_report` với `_SCREEN_LIMIT_FOR_FILTER`
    (đủ lớn để phủ toàn bộ vũ trụ mã thực tế) để lọc trên tập ĐẦY ĐỦ, rồi
    mới cắt về `limit` gốc SAU KHI lọc — giữ đúng `rank`/thứ tự composite
    giảm dần đã có sẵn từ `screen_report`."""
    screen_limit = _SCREEN_LIMIT_FOR_FILTER if min_composite is not None else limit
    report = scoring.screen_report(con, profile, limit=screen_limit)
    ranked = report["ranked"]
    if min_composite is not None:
        if not ranked.empty:
            ranked = ranked[ranked["composite_score"] >= min_composite]
        ranked = ranked.head(limit).reset_index(drop=True)

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
               avg_turnover_20d, peer_basis, peer_count, data_quality_score,
               quality_flags
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
               n_symbols, n_pe, n_pb, n_roe, median_pe, median_pb,
               median_roe, sector_return_3m
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
                    "với doanh nghiệp sản xuất. n_symbols là TỔNG số mã trong "
                    "nhóm; n_pe/n_pb/n_roe là số mã CÓ dữ liệu dùng được cho "
                    "từng chỉ tiêu (luôn <= n_symbols) — nêu con số này khi "
                    "nói về median, đừng ngầm hiểu median dựa trên n_symbols mã.",
            **db.as_of(con)}


def get_distribution_history(con, symbol: str, years: int = 5) -> dict:
    """Lịch sử phân phối cho cổ đông — HAI KHỐI trên HAI TRỤC THỜI GIAN.

    Cố ý KHÔNG ghép hai khối (hướng A của spec B1). `dividend_yield` gán
    theo NĂM TÀI CHÍNH; sự kiện gán theo NGÀY GDKHQ — cổ tức "cả năm 2021"
    của HPG chi trả ngày 17/06/2022. Ghép được cho cổ tức tiền mặt nhưng
    KHÔNG ghép được cho cổ tức bằng cổ phiếu (tiêu đề nguồn không ghi kỳ
    nào: "Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%") — tức đúng phần dữ liệu
    mới mà B1 sinh ra để lấy. Nên trả tách bạch, ghi rõ trục, để agent tự
    diễn giải.
    """
    sym = symbol.upper().strip()

    events = db.run_query(
        con,
        """
        SELECT event_id, exright_date, record_date, payout_date,
               distribution_type, cash_per_share, stock_ratio, event_title_vi
        FROM int_distribution_event
        WHERE symbol = ?
        ORDER BY exright_date DESC
        """,
        params=[sym],
        limit=4 * years + 20,
    )
    cash_year = db.run_query(
        con,
        """
        SELECT year, dividend_yield
        FROM stg_financial_ratio
        WHERE symbol = ? AND quarter = 5
        ORDER BY year DESC
        """,
        params=[sym],
        limit=years,
    )

    if not events and not cash_year:
        return {"error": f"Không có dữ liệu phân phối cho {sym}.", **db.as_of(con)}

    # I4 (fix round cuối): int_distribution_event lọc thêm
    # `exright_date is not null` (không có trục thời gian thì không đặt lên
    # timeline được) — hợp lý, nhưng đo trên production con số bị loại
    # không nhỏ: 323/9932 sự kiện phân phối (3,36%). Không đếm lại thì
    # data_quality.n_events chỉ đếm dòng còn sống, agent thấy
    # distribution_events rỗng (hoặc ngắn) mà không biết đó là "không có dữ
    # liệu" hay "dữ liệu bị lọc mất" — cùng lớp lỗi mà event_window_years
    # được đặt ra để chống.
    missing_exright = db.run_query(
        con,
        """
        SELECT count(*) as n
        FROM stg_corporate_event
        WHERE symbol = ? AND is_distribution AND exright_date IS NULL
        """,
        params=[sym],
        limit=1,
    )
    n_missing = missing_exright[0]["n"] if missing_exright else 0

    for r in events:
        for col in ("exright_date", "record_date", "payout_date"):
            r[col] = _date_str(r.get(col))

    window_start = min((r["exright_date"] for r in events if r["exright_date"]),
                       default=None)
    window_end = max((r["exright_date"] for r in events if r["exright_date"]),
                     default=None)
    window_years = None
    if window_start and window_end:
        window_years = round(
            (date.fromisoformat(window_end) - date.fromisoformat(window_start)).days / 365,
            1,
        )

    note = ("Hai khối nằm trên HAI TRỤC THỜI GIAN khác nhau: "
            "cash_dividend_by_fiscal_year theo NĂM TÀI CHÍNH, "
            "distribution_events theo NGÀY GDKHQ (cổ tức 'cả năm 2021' "
            "chi trả 17/06/2022). KHÔNG cộng gộp hai khối.")
    if n_missing:
        note += (f" Ngoài ra {n_missing} sự kiện phân phối của {sym} KHÔNG "
                 "có ngày GDKHQ nên không đặt lên được timeline này — xem "
                 "data_quality.n_events_missing_exright_date.")

    return {
        "symbol": sym,
        "cash_dividend_by_fiscal_year": _clean(cash_year),
        "distribution_events": _clean(events),
        "note": note,
        # event_window_years là bằng chứng đỡ cho mọi phát biểu về chuỗi cổ
        # tức. Nguồn chỉ trả 50 sự kiện gần nhất và cửa sổ đó trượt: đo trên
        # 15 mã (2026-08-16), 50 sự kiện phủ từ 1,0 năm (MWG) tới 9,9 năm
        # (AGX). Không phơi con số này thì agent nhìn VNM thấy 3 sự kiện cổ
        # tức rồi kết luận "VNM mới trả cổ tức 3 năm gần đây", trong khi sự
        # thật là cửa sổ chỉ nhìn được 1,5 năm.
        "data_quality": {
            "event_window_start": window_start,
            "event_window_end": window_end,
            "event_window_years": window_years,
            "n_events": len(events),
            # n_events_missing_exright_date (I4): số sự kiện phân phối THẬT
            # (cổ tức tiền mặt/cổ phiếu, cổ phiếu thưởng) của mã này bị
            # int_distribution_event lọc mất vì exright_date NULL — không có
            # trục thời gian thì không đặt lên timeline được, nhưng con số
            # đó phải có chỗ hiện diện thay vì lặng lẽ biến mất.
            "n_events_missing_exright_date": n_missing,
        },
        **db.as_of(con),
    }


def get_ownership(con, symbol: str) -> dict:
    """Cơ cấu sở hữu đã công bố: cổ đông lớn, ban lãnh đạo, mức độ cô đặc."""
    sym = symbol.upper().strip()

    conc_rows = db.run_query(
        con,
        """
        SELECT snapshot_date, officer_snapshot_date, n_disclosed,
               total_disclosed_pct, top1_pct, top5_pct, insider_pct
        FROM int_ownership_snapshot
        WHERE symbol = ?
        """,
        params=[sym],
        limit=1,
    )
    if not conc_rows:
        return {"error": f"Không có dữ liệu sở hữu cho {sym}.", **db.as_of(con)}

    conc = conc_rows[0]
    snapshot_date = _date_str(conc.get("snapshot_date"))
    # I1 (fix round cuối): officer_snapshot_date là ngày snapshot RIÊNG của
    # bảng officer — có thể lệch với snapshot_date (của cổ đông) nếu một mã
    # lỗi fetch ở lần chạy monthly cho một trong hai nguồn. Lọc stg_officer
    # bằng đúng ngày của chính nó, không dùng chung ngày cổ đông — nếu không
    # officers có thể trả về rỗng trong khi insider_pct vẫn có số (payload tự
    # mâu thuẫn).
    officer_snapshot_date = _date_str(conc.get("officer_snapshot_date"))

    holders = db.run_query(
        con,
        """
        SELECT share_holder, quantity, share_own_percent
        FROM stg_shareholder
        WHERE symbol = ? AND snapshot_date = ?
        ORDER BY share_own_percent DESC NULLS LAST
        """,
        params=[sym, snapshot_date],
        limit=200,
    )
    officers = db.run_query(
        con,
        """
        SELECT officer_name, officer_position,
               officer_own_percent, officer_own_quantity
        FROM stg_officer
        WHERE symbol = ? AND snapshot_date = ?
        ORDER BY officer_own_percent DESC NULLS LAST
        """,
        params=[sym, officer_snapshot_date],
        limit=100,
    )

    return {
        "symbol": sym,
        "major_shareholders": [
            {"name": h["share_holder"], "quantity": h["quantity"],
             "percent": h["share_own_percent"]}
            for h in _clean(holders)
        ],
        "officers": [
            {"name": o["officer_name"], "position": o["officer_position"],
             "own_percent": o["officer_own_percent"],
             "own_quantity": o["officer_own_quantity"]}
            for o in _clean(officers)
        ],
        "concentration": {
            "top1_pct": _clean(conc.get("top1_pct")),
            "top5_pct": _clean(conc.get("top5_pct")),
            "n_disclosed": _clean(conc.get("n_disclosed")),
            "total_disclosed_pct": _clean(conc.get("total_disclosed_pct")),
            "insider_pct": _clean(conc.get("insider_pct")),
        },
        "snapshot_date": snapshot_date,
        # Cảnh báo này bắt buộc: đo 2026-08-16, tổng % công bố là HPG 51,9%,
        # VNM 81,0%, VCB 91,0% — không phải 100%. Không nói rõ thì agent rất
        # dễ lấy 100% trừ đi rồi gọi phần dư là free float, trong khi
        # dim_stock.free_float_percentage là con số khác từ nguồn khác.
        "note": "Chỉ gồm cổ đông ĐÃ CÔNG BỐ — tổng total_disclosed_pct KHÔNG "
                "bằng 100%. Phần còn lại là cổ đông không công bố, KHÔNG đồng "
                "nghĩa free float (dùng get_stock_profile để lấy free float "
                "từ nguồn riêng).",
        **db.as_of(con),
    }


def get_financial_statement(con, symbol: str, statement_type: str,
                            period_type: str = "quarter") -> dict:
    """Chi tiết một báo cáo tài chính (income_statement/balance_sheet/
    cash_flow), mỗi dòng BCTC kèm chuỗi giá trị theo kỳ.

    row_seq trả kèm mỗi item để phân biệt các dòng TRÙNG item_id — item_id
    KHÔNG unique trong một báo cáo (vd 'cost' xuất hiện nhiều lần ở
    balance_sheet, mỗi lần một nhóm tài sản cố định khác nhau — chỉ
    item_vi/row_seq phân biệt được, xem spec B2 §1.3). Agent nên hiển thị
    item_vi cho người dùng, không phải row_seq.
    """
    sym = symbol.upper().strip()
    st = statement_type.strip()
    pt = period_type.strip()

    rows = db.run_query(
        con,
        """
        SELECT row_seq, item_id, item_vi, period_label, value
        FROM stg_financial_statement
        WHERE symbol = ? AND statement_type = ? AND period_type = ?
        ORDER BY row_seq, period_label DESC
        """,
        params=[sym, st, pt],
        limit=2000,
    )

    if not rows:
        return {
            "symbol": sym, "statement_type": st, "period_type": pt,
            "data_quality": {"has_data": False},
            **db.as_of(con),
        }

    # Fix round 1 (review): route TOÀN BỘ dòng qua _clean() TRƯỚC khi dùng —
    # cùng convention với get_ownership/get_distribution_history
    # (_clean(holders)/_clean(events) áp cho cả dict, không riêng một cột).
    # Bản trước chỉ _clean() cột `value`, để row_seq/item_id/item_vi lọt qua
    # trực tiếp từ pandas/DuckDB — rủi ro cụ thể: `row_seq` KHÔNG có test
    # not_null trong _staging.yml (chỉ nằm trong unique_combination_of_columns
    # cùng period_label), nên nếu có dữ liệu thật với row_seq NULL ở nhiều
    # dòng khác nhau, dict key `seq` sẽ là NaN/None không nhất quán và có thể
    # gộp nhầm các dòng khác nhóm vào chung items_by_seq[None] với
    # has_data=True, không có tín hiệu lỗi nào báo — đúng lỗi mà row_seq được
    # thêm vào để tránh.
    rows = _clean(rows)

    # Gộp lại theo (row_seq, item_id, item_vi) -> {period_label: value},
    # giữ nguyên thứ tự row_seq đã sort ở SQL.
    items_by_seq: dict[int, dict] = {}
    order: list[int] = []
    for r in rows:
        seq = r["row_seq"]
        if seq not in items_by_seq:
            items_by_seq[seq] = {
                "item_id": r["item_id"],
                "item_vi": r["item_vi"],
                "row_seq": seq,
                "values_by_period": {},
            }
            order.append(seq)
        items_by_seq[seq]["values_by_period"][r["period_label"]] = r["value"]

    items = [items_by_seq[s] for s in order]

    return {
        "symbol": sym,
        "statement_type": st,
        "period_type": pt,
        "items": items,
        "n_items": len(items),
        "data_quality": {"has_data": True, "n_periods_available": len(
            {p for it in items for p in it["values_by_period"]}
        )},
        **db.as_of(con),
    }
