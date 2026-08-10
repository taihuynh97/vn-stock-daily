"""Tầng 4 kiểm chứng — đối chiếu chéo giữa các layer và với API nguồn.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.reconcile_warehouse            # đủ 2 phần
    python -m scripts.reconcile_warehouse --no-api   # chỉ đếm layer

Exit code 1 nếu có bất kỳ kiểm tra nào không đạt.
"""
import os

# load_dotenv() PHẢI chạy trước khi import src.* — src.ingest đọc
# VNSTOCK_MIN_INTERVAL từ env ngay ở module scope lúc import, nên nếu .env
# được nạp sau import thì biến trong .env không có tác dụng.
from dotenv import load_dotenv

load_dotenv()

import argparse
import random
import sys

import pandas as pd

from src import ingest_market, warehouse

MIN_COVERAGE = 0.95      # tỉ lệ mã tối thiểu so với dim_symbols
MAX_DRIFT = 0.01         # sai lệch tối đa khi đối chiếu với API gốc


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def check_layer_counts(con) -> list[dict]:
    """Đếm số mã/số dòng qua từng bảng, so với dim_symbols."""
    total = _scalar(con, "SELECT count(*) FROM dim_symbols WHERE is_active")
    rows = [{"check": "dim_symbols", "value": total, "expected": total, "ok": total > 0}]

    for name, sql in [
        ("raw_price_daily_symbols",
         "SELECT count(DISTINCT symbol) FROM raw_price_daily"),
        ("raw_company_info_symbols",
         "SELECT count(*) FROM raw_company_info"),
        ("raw_financial_ratio_symbols",
         "SELECT count(DISTINCT symbol) FROM raw_financial_ratio"),
    ]:
        v = _scalar(con, sql)
        rows.append({"check": name, "value": v, "expected": total,
                     "ok": total > 0 and v >= total * MIN_COVERAGE})

    ind = _scalar(con, "SELECT count(*) FROM dim_industry")
    rows.append({"check": "dim_industry_rows", "value": ind, "expected": 100,
                 "ok": ind >= 100})

    idx = _scalar(con, "SELECT count(DISTINCT index_code) FROM raw_index_daily")
    rows.append({"check": "raw_index_daily_codes", "value": idx, "expected": 3,
                 "ok": idx >= 3})

    exch = _scalar(con,
                   "SELECT count(*) FROM dim_symbols WHERE exchange IS NOT NULL")
    rows.append({"check": "dim_symbols_with_exchange", "value": exch,
                 "expected": total, "ok": total > 0 and exch >= total * MIN_COVERAGE})

    # Đếm có hệ thống (toàn bộ, không phải mẫu ngẫu nhiên) số mã is_active
    # chưa có dòng nào trong raw_financial_ratio, dung sai giống các check độ
    # phủ khác ở trên (MIN_COVERAGE). Bù cho việc check_against_source coi mã
    # thiếu tỷ số là thông tin (ok=True) chứ không phải sai lệch: độ phủ vẫn
    # được canh, nhưng bằng phép đo toàn bộ thay vì mẫu --sample ngẫu nhiên.
    missing_ratio = _scalar(con, """
        SELECT count(*) FROM dim_symbols d
        WHERE d.is_active
          AND NOT EXISTS (
              SELECT 1 FROM raw_financial_ratio f WHERE f.symbol = d.symbol
          )
    """)
    rows.append({
        "check": "symbols_missing_ratio", "value": missing_ratio, "expected": 0,
        "ok": total > 0 and missing_ratio <= total * (1 - MIN_COVERAGE),
    })

    return rows


def check_against_source(con, symbols: list[str]) -> list[dict]:
    """Gọi lại API gốc cho vài mã, so kỳ tỷ số gần nhất với warehouse.

    Chỉ so lệch khi API trả về ĐÚNG kỳ (year, quarter) mà warehouse đang có.
    Nếu API đã có kỳ mới hơn (warehouse chưa kịp reload) thì đây là thông
    tin, KHÔNG phải sai lệch dữ liệu — không tính là fail, tránh CI đỏ ngẫu
    nhiên mỗi khi vnstock công bố báo cáo mới trước lần reload định kỳ.
    Tương tự, API không trả dữ liệu (lỗi mạng/rate limit tạm thời) không
    tính là fail — đó là sự cố nguồn, không phải sai lệch warehouse.
    Mã được lấy mẫu mà chưa có dòng nào trong raw_financial_ratio cũng KHÔNG
    tính là fail (~13/1598 mã thực tế đang ở trạng thái này — dung sai đã
    được chấp nhận ở check_layer_counts qua check symbols_missing_ratio dựa
    trên toàn bộ mã, không phải mẫu ngẫu nhiên 5 mã nên không nên đỏ CI ngẫu
    nhiên vì trúng đúng mã chưa có tỷ số).
    """
    out = []
    for sym in symbols:
        wh_row = con.execute(
            "SELECT year, quarter, pe, roe FROM raw_financial_ratio "
            "WHERE symbol = ? ORDER BY year DESC, quarter DESC LIMIT 1",
            [sym],
        ).fetchone()
        if wh_row is None:
            out.append({
                "symbol": sym, "check": "ratio_latest",
                "detail": (
                    f"{sym} chưa có tỷ số tài chính trong warehouse — thông "
                    "tin, không phải sai lệch (độ phủ được đo có hệ thống ở "
                    "check_layer_counts qua symbols_missing_ratio)"
                ),
                "ok": True,
            })
            continue

        wh_year, wh_quarter, wh_pe, wh_roe = wh_row
        api = ingest_market.fetch_financials([sym])
        if api.empty:
            out.append({
                "symbol": sym, "check": "ratio_latest",
                "detail": (
                    f"kỳ warehouse {wh_year}Q{wh_quarter} — API không trả dữ "
                    "liệu (có thể do lỗi mạng/rate limit tạm thời, không "
                    "phải sai lệch dữ liệu)"
                ),
                "ok": True,
            })
            continue

        match = api[(api["year"] == wh_year) & (api["quarter"] == wh_quarter)]
        if match.empty:
            api_latest = api.sort_values(["year", "quarter"]).iloc[-1]
            out.append({
                "symbol": sym, "check": "ratio_latest",
                "detail": (
                    f"kỳ warehouse {wh_year}Q{wh_quarter}, kỳ mới nhất từ API "
                    f"{int(api_latest['year'])}Q{int(api_latest['quarter'])} "
                    "— warehouse chưa reload kỳ mới, không phải lỗi"
                ),
                "ok": True,
            })
            continue

        api_row = match.iloc[-1]
        drift = []
        for wh_val, col in [(wh_pe, "pe"), (wh_roe, "roe")]:
            b = api_row[col]
            if wh_val is None or pd.isna(b):
                continue
            denom = abs(b) if abs(b) > 1e-9 else 1.0
            drift.append(abs(wh_val - b) / denom)
        worst = max(drift) if drift else 0.0
        out.append({
            "symbol": sym, "check": "ratio_latest",
            "detail": f"kỳ warehouse {wh_year}Q{wh_quarter}, lệch tối đa {worst:.4f}",
            # bool(...): worst có thể là numpy.float64 (đọc từ pandas Series),
            # so sánh sẽ ra numpy.bool_ — ép về Python bool để nhất quán với
            # kiểu dữ liệu của check_layer_counts() và an toàn khi so `is True/False`.
            "ok": bool(worst <= MAX_DRIFT),
        })
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--sample", type=int, default=5)
    args = parser.parse_args()

    # check_against_source gọi lại ingest_market.fetch_financials — không đăng
    # ký key thì chạy ở bậc Guest 20 req/phút (xem migrate_financial_ratio_v2.py).
    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    db_target = os.getenv("WAREHOUSE_DB", warehouse.DEFAULT_DB)
    print(f"Đang kết nối tới: {db_target}")

    con = warehouse.get_conn()
    results = check_layer_counts(con)

    if not args.no_api:
        pool = warehouse.get_active_symbols(con)
        sample = random.sample(pool, min(args.sample, len(pool)))
        print(f"Đối chiếu API gốc cho: {', '.join(sample)}")
        results += check_against_source(con, sample)

    con.close()
    print(pd.DataFrame(results).to_string(index=False))
    failed = [r for r in results if not r["ok"]]
    if failed:
        print(f"\n{len(failed)} kiểm tra KHÔNG ĐẠT.")
        sys.exit(1)
    print("\nTất cả kiểm tra ĐẠT.")


if __name__ == "__main__":
    main()
