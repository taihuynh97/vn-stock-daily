"""Backfill lịch sử giá OHLCV cho toàn bộ dim_symbols — Phase 1.5.

Chạy nhiều lần để hoàn tất (resumable nhờ backfill_status):

    python backfill.py               # 100 mã đầu, 3 năm lịch sử
    python backfill.py --limit 200   # 200 mã mỗi lần
    python backfill.py --years 5     # 5 năm lịch sử

Biến môi trường:
  WAREHOUSE_DB       (tuỳ chọn) mặc định data/warehouse.duckdb
  motherduck_token   (nếu dùng MotherDuck)
  VNSTOCK_API_KEY    (khuyến nghị) nâng rate limit lên 60 req/phút
"""
import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()
ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Backfill lịch sử giá OHLCV")
    parser.add_argument("--years", type=int, default=3, help="Số năm lịch sử (mặc định 3)")
    parser.add_argument("--limit", type=int, default=100, help="Số mã tối đa mỗi lần chạy (mặc định 100)")
    args = parser.parse_args()

    key = os.getenv("VNSTOCK_API_KEY")
    if key:
        from vnstock import vnai
        vnai.setup_api_key(key)

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")

    end_date   = date.today().isoformat()
    start_date = (date.today() - timedelta(days=args.years * 365)).isoformat()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)
    warehouse.init_backfill_status(con)

    pending = warehouse.get_pending_symbols(con)
    total_pending = len(pending)
    batch = pending[:args.limit]

    print(f"Backfill: {len(batch)}/{total_pending} mã còn pending | {start_date} → {end_date}")

    done = error = 0
    for i, symbol in enumerate(batch, 1):
        df = ingest_market.fetch_history_one(symbol, start_date, end_date, source)
        if df.empty:
            warehouse.mark_backfill_error(con, symbol, "empty response")
            error += 1
            print(f"  [{i}/{len(batch)}] {symbol}: empty — skip")
            continue

        warehouse.upsert_prices(con, df)
        warehouse.mark_backfill_done(con, symbol, end_date)
        done += 1
        if i % 10 == 0 or i == len(batch):
            print(f"  [{i}/{len(batch)}] {symbol}: {len(df)} phiên — OK")

    warehouse.log_load(
        con, "backfill", "raw_price_daily",
        done,
        "ok" if error == 0 else "partial",
        watermark=end_date,
        notes=f"done={done} error={error} pending_after={total_pending - done}",
    )

    total_rows = con.execute("SELECT count(*) FROM raw_price_daily").fetchone()[0]
    print(f"\nXong batch: done={done} error={error}")
    print(f"raw_price_daily tổng: {total_rows:,} dòng")
    still_pending = len(warehouse.get_pending_symbols(con))
    if still_pending > 0:
        print(f"Còn {still_pending} mã chưa xong — chạy lại: python backfill.py --limit {args.limit}")
    else:
        print("Backfill hoàn tất!")

    con.close()


if __name__ == "__main__":
    main()
