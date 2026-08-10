"""Tầng 4 kiểm chứng — đối chiếu chéo giữa các layer và với API nguồn.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.reconcile_warehouse            # đủ 2 phần
    python -m scripts.reconcile_warehouse --no-api   # chỉ đếm layer

Exit code 1 nếu có bất kỳ kiểm tra nào không đạt.
"""
import argparse
import random
import sys

import pandas as pd
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()

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

    return rows


def check_against_source(con, symbols: list[str]) -> list[dict]:
    """Gọi lại API gốc cho vài mã, so kỳ tỷ số gần nhất với warehouse."""
    out = []
    for sym in symbols:
        wh_row = con.execute(
            "SELECT year, quarter, pe, roe FROM raw_financial_ratio "
            "WHERE symbol = ? ORDER BY year DESC, quarter DESC LIMIT 1",
            [sym],
        ).fetchone()
        if wh_row is None:
            out.append({"symbol": sym, "check": "ratio_latest",
                        "detail": "không có trong warehouse", "ok": False})
            continue

        api = ingest_market.fetch_financials([sym])
        if api.empty:
            out.append({"symbol": sym, "check": "ratio_latest",
                        "detail": "API không trả dữ liệu", "ok": False})
            continue

        api = api.sort_values(["year", "quarter"]).iloc[-1]
        drift = []
        for i, col in enumerate(["pe", "roe"], start=2):
            a, b = wh_row[i], api[col]
            if a is None or pd.isna(b):
                continue
            denom = abs(b) if abs(b) > 1e-9 else 1.0
            drift.append(abs(a - b) / denom)
        worst = max(drift) if drift else 0.0
        out.append({
            "symbol": sym, "check": "ratio_latest",
            "detail": f"kỳ warehouse {wh_row[0]}Q{wh_row[1]}, lệch tối đa {worst:.4f}",
            "ok": worst <= MAX_DRIFT,
        })
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--sample", type=int, default=5)
    args = parser.parse_args()

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
