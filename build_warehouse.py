"""Job thu thập warehouse — Phase 1: dim_symbols + giá EOD toàn thị trường.

Chạy độc lập với main.py (job bản tin). Chạy sau giờ đóng cửa mỗi ngày.

    python build_warehouse.py

Biến môi trường:
  WAREHOUSE_DB     (tuỳ chọn) đường dẫn DuckDB. Mặc định data/warehouse.duckdb.
                   Đặt 'md:vn_market' để ghi lên MotherDuck cloud.
  motherduck_token (nếu dùng MotherDuck)
  VNSTOCK_API_KEY  (khuyến nghị) nâng rate limit lên 60 req/phút.
"""
import os
from datetime import date
from pathlib import Path
import yaml
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()
ROOT = Path(__file__).resolve().parent


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Warehouse ingestion job")
    parser.add_argument(
        "--mode",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="daily=giá EOD+universe; weekly=+financials; monthly=+company_info",
    )
    args = parser.parse_args()

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")
    run_date = date.today().isoformat()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    # 1) Refresh danh sách mã
    uni = ingest_market.refresh_universe(cfg["exchanges"], source)
    n_sym = warehouse.upsert_symbols(con, uni, run_date)
    warehouse.log_load(con, f"warehouse_{args.mode}", "dim_symbols", n_sym,
                       "ok" if n_sym else "empty")
    print(f"dim_symbols: {n_sym} mã ({', '.join(cfg['exchanges'])})")

    # 2) Giá EOD toàn thị trường (bulk) — mọi mode đều có
    symbols = warehouse.get_active_symbols(con)
    if not symbols:
        print("Chưa có mã nào trong dim_symbols — dừng.")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", 0,
                           "skipped", notes="no symbols")
        con.close()
        return

    if not ingest_market.is_trading_day(date.today()):
        print(f"{run_date} không phải ngày giao dịch (T7/CN) — bỏ qua giá EOD.")
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", 0,
                           "skipped", notes="non-trading day (weekend)")
    else:
        prices = ingest_market.fetch_eod_prices(symbols, source, cfg.get("price_board_batch", 50))
        n_px = warehouse.upsert_prices(con, prices)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_price_daily", n_px,
                           "ok" if n_px else "empty", watermark=run_date)
        print(f"raw_price_daily: {n_px}/{len(symbols)} mã có giá cho {run_date}")

    # 3) Financial ratios — weekly và monthly
    if args.mode in ("weekly", "monthly"):
        print(f"Bắt đầu fetch financials ({len(symbols)} mã)...")
        fin = ingest_market.fetch_financials(symbols, source)
        n_fin = warehouse.upsert_financial_ratios(con, fin)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_financial_ratio", n_fin,
                           "ok" if n_fin else "empty", watermark=run_date)
        print(f"raw_financial_ratio: {n_fin} dòng")

    # 4) Company info — monthly only
    if args.mode == "monthly":
        ind = ingest_market.fetch_industries_icb(source)
        n_ind = warehouse.upsert_industries(con, ind)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_industry", n_ind,
                           "ok" if n_ind else "empty", watermark=run_date)
        print(f"dim_industry: {n_ind} ngành ICB")

        print(f"Bắt đầu fetch company info ({len(symbols)} mã)...")
        info = ingest_market.fetch_company_info(symbols, source)
        n_info = warehouse.upsert_company_info(con, info)
        warehouse.log_load(con, f"warehouse_{args.mode}", "raw_company_info", n_info,
                           "ok" if n_info else "empty", watermark=run_date)
        print(f"raw_company_info: {n_info} mã")
        n_exch = warehouse.update_symbol_exchanges(con)
        warehouse.log_load(con, f"warehouse_{args.mode}", "dim_symbols", n_exch,
                           "ok" if n_exch else "empty", watermark=run_date,
                           notes="sync exchange tu raw_company_info")
        print(f"dim_symbols.exchange: cập nhật {n_exch} mã")

    con.close()
    print(f"Xong warehouse job ({args.mode}).")


if __name__ == "__main__":
    main()
