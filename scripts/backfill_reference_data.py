"""Nạp reference data (dim_industry + raw_company_info) — chạy MỘT LẦN,
KHÔNG gọi fetch_financials.

Vì sao cần: controller vừa nạp lại toàn bộ raw_financial_ratio bằng
scripts/migrate_financial_ratio_v2.py (~2 giờ). Chạy tiếp
build_warehouse.py --mode monthly sẽ gọi lại fetch_financials cho 1.598
mã — lặp lại đúng việc vừa làm, tốn thêm ~2 giờ vô ích. Script này chỉ
nạp phần reference data còn thiếu của mode monthly: dim_industry,
raw_company_info, và đồng bộ dim_symbols.exchange.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    export VNSTOCK_API_KEY=<key>          # nếu có, nâng rate limit lên 60 req/phút
    python -m scripts.backfill_reference_data
    python -m scripts.backfill_reference_data --limit 20   # chạy thử
"""
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

import argparse

import pandas as pd

from src import ingest_market, warehouse

JOB_NAME = "backfill_reference_data"


def main():
    parser = argparse.ArgumentParser(description="Nạp dim_industry + raw_company_info một lần")
    parser.add_argument("--limit", type=int, default=None,
                        help="Giới hạn số mã nạp hồ sơ doanh nghiệp (chạy thử)")
    args = parser.parse_args()

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    db_target = os.getenv("WAREHOUSE_DB", warehouse.DEFAULT_DB)
    print(f"Đang kết nối tới: {db_target}")

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)
    run_date = date.today().isoformat()

    # 1) Phân ngành ICB (bảng tĩnh, ~177 dòng)
    ind = ingest_market.fetch_industries_icb()
    n_ind = warehouse.upsert_industries(con, ind)
    warehouse.log_load(con, JOB_NAME, "dim_industry", n_ind,
                       "ok" if n_ind else "empty", watermark=run_date)
    print(f"dim_industry: {n_ind} ngành ICB")

    # 2) Hồ sơ doanh nghiệp
    symbols = warehouse.get_active_symbols(con)
    if args.limit:
        symbols = symbols[:args.limit]
    print(f"Bắt đầu fetch company info ({len(symbols)} mã)...")
    info = ingest_market.fetch_company_info(symbols)
    n_info = warehouse.upsert_company_info(con, info)
    warehouse.log_load(con, JOB_NAME, "raw_company_info", n_info,
                       "ok" if n_info else "empty", watermark=run_date,
                       notes=f"limit={args.limit}" if args.limit else "")
    print(f"raw_company_info: {n_info} mã")

    # 3) Đồng bộ dim_symbols.exchange từ raw_company_info
    n_exch = warehouse.update_symbol_exchanges(con)
    warehouse.log_load(con, JOB_NAME, "dim_symbols", n_exch,
                       "ok" if n_exch else "empty", watermark=run_date,
                       notes="sync exchange tu raw_company_info")
    print(f"dim_symbols.exchange: cập nhật {n_exch} mã")

    n_null_exchange = con.execute(
        "SELECT count(*) FROM dim_symbols WHERE is_active AND exchange IS NULL"
    ).fetchone()[0]
    con.close()

    print("\nTổng kết:")
    summary = pd.DataFrame([
        {"muc": "dim_industry (nganh ICB)", "gia_tri": n_ind},
        {"muc": "raw_company_info (ma co ho so)", "gia_tri": n_info},
        {"muc": "dim_symbols.exchange da cap nhat", "gia_tri": n_exch},
        {"muc": "dim_symbols.exchange con NULL", "gia_tri": n_null_exchange},
    ])
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
