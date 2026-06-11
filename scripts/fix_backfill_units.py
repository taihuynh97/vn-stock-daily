"""Migration một lần: sửa đơn vị OHLC cho dữ liệu backfill cũ trong raw_price_daily.

Bối cảnh: ingest_market.fetch_history_one (backfill, dùng Quote.history nguồn VCI)
trước đây không nhân lại 1000 sau khi vnstock chia OHLC cho 1000 (đơn vị "nghìn đồng").
Vì vậy ~1.18 triệu dòng backfill (value IS NULL) bị lệch đơn vị 1000 lần so với dữ liệu
price_board (value NOT NULL, đơn vị VND). Code ingest đã được fix; script này sửa dữ liệu
CŨ đã ghi trước khi fix. Có guard chống chạy lại 2 lần (tra etl_load_log).

Chạy 1 lần:
    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python scripts/fix_backfill_units.py
"""
from dotenv import load_dotenv

from src import warehouse

load_dotenv()

JOB_NAME = "migration_fix_backfill_units_2026"


def main():
    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    already_run = con.execute(
        "SELECT count(*) FROM etl_load_log WHERE job_name = ? AND status = 'ok'",
        [JOB_NAME],
    ).fetchone()[0]
    if already_run:
        print(f"Migration '{JOB_NAME}' đã chạy trước đó — bỏ qua.")
        con.close()
        return

    before = con.execute(
        "SELECT count(*), avg(close) FROM raw_price_daily WHERE value IS NULL"
    ).fetchone()
    print(f"Trước migration: {before[0]:,} dòng value IS NULL, avg(close)={before[1]:.2f}")

    n = warehouse.fix_backfill_price_units(con)

    after_avg = con.execute(
        "SELECT avg(close) FROM raw_price_daily WHERE value IS NULL"
    ).fetchone()[0]
    print(f"Sau migration: {n:,} dòng đã x1000, avg(close)={after_avg:.2f}")

    warehouse.log_load(
        con, JOB_NAME, "raw_price_daily", n, "ok",
        notes="Nhan open/high/low/close x1000 cho dong backfill (value IS NULL) "
              "de dong nhat don vi VND voi price_board",
    )
    con.close()
    print("Xong.")


if __name__ == "__main__":
    main()
