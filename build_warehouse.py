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
    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")
    run_date = date.today().isoformat()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    # 1) Refresh danh sách mã (Phase 1: chạy mỗi lần; sau có thể tách job monthly)
    uni = ingest_market.refresh_universe(cfg["exchanges"], source)
    n_sym = warehouse.upsert_symbols(con, uni, run_date)
    warehouse.log_load(con, "warehouse_daily", "dim_symbols", n_sym,
                       "ok" if n_sym else "empty")
    print(f"dim_symbols: {n_sym} mã ({', '.join(cfg['exchanges'])})")

    # 2) Giá EOD toàn thị trường (bulk)
    symbols = warehouse.get_active_symbols(con)
    if not symbols:
        print("Chưa có mã nào trong dim_symbols — dừng.")
        warehouse.log_load(con, "warehouse_daily", "raw_price_daily", 0, "skipped",
                           notes="no symbols")
        con.close()
        return

    prices = ingest_market.fetch_eod_prices(symbols, source, cfg.get("price_board_batch", 50))
    n_px = warehouse.upsert_prices(con, prices)
    warehouse.log_load(con, "warehouse_daily", "raw_price_daily", n_px,
                       "ok" if n_px else "empty", watermark=run_date)
    print(f"raw_price_daily: {n_px}/{len(symbols)} mã có giá cho {run_date}")

    con.close()
    print("Xong warehouse job.")


if __name__ == "__main__":
    main()
