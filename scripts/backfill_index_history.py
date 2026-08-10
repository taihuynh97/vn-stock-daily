"""Backfill lịch sử chỉ số (một lần). Chỉ 3 call API nên chạy rất nhanh.

    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.backfill_index_history --years 10
"""
import argparse
from datetime import date, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
JOB_NAME = "backfill_index_history"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=10)
    args = parser.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config" / "warehouse.yml", encoding="utf-8"))
    source = cfg.get("source", "VCI")
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=args.years * 366)).isoformat()

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    total = 0
    for code in cfg.get("indices", []):
        df = ingest_market.fetch_index_history(code, start, end, source)
        n = warehouse.upsert_index_prices(con, df)
        total += n
        print(f"{code}: {n} phiên ({start} → {end})")

    warehouse.log_load(con, JOB_NAME, "raw_index_daily", total,
                       "ok" if total else "empty", watermark=end)
    print(con.execute(
        "SELECT index_code, count(*) phien, min(trade_date), max(trade_date) "
        "FROM raw_index_daily GROUP BY 1 ORDER BY 1"
    ).df().to_string())
    con.close()


if __name__ == "__main__":
    main()
