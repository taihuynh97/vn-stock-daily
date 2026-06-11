"""Migration một lần: xoá dữ liệu phantom của trade_date=2026-06-07 (Chủ Nhật)
trong raw_price_daily.

Bối cảnh: build_warehouse.py được chạy thủ công vào Chủ Nhật 2026-06-07. Lúc đó
fetch_eod_prices() stamp trade_date = date.today() (06-07) bất kể có phải phiên
giao dịch hay không (đã fix bằng is_trading_day() guard trong build_warehouse.py).
Ngoài ra, vào ngày không có phiên, Trading.price_board (VCI) trả dữ liệu không
nhất quán: open/high/low/volume là dữ liệu thật của phiên gần nhất (06-05) nhưng
close lại là giá tham chiếu (= close của 06-04), không phải match price thật của
06-05. Kết quả là 1.573 dòng trade_date='2026-06-07' với close không khớp OHLV —
dữ liệu này không đại diện cho bất kỳ phiên giao dịch thật nào và cần được xoá.

Có guard chống chạy lại 2 lần (tra etl_load_log).

Chạy 1 lần:
    export WAREHOUSE_DB=md:vn_market
    export motherduck_token=<token>
    python -m scripts.fix_phantom_sunday
"""
from dotenv import load_dotenv

from src import warehouse

load_dotenv()

JOB_NAME = "migration_delete_phantom_sunday_20260607"
PHANTOM_DATE = "2026-06-07"


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
        "SELECT count(*) FROM raw_price_daily WHERE trade_date = ?", [PHANTOM_DATE]
    ).fetchone()[0]
    print(f"Trước migration: {before:,} dòng trade_date={PHANTOM_DATE}")

    n = warehouse.delete_trade_date(con, PHANTOM_DATE)
    print(f"Đã xoá {n:,} dòng.")

    warehouse.log_load(
        con, JOB_NAME, "raw_price_daily", n, "ok",
        notes=f"Xoa du lieu phantom trade_date={PHANTOM_DATE} "
              "(Chu Nhat, price_board tra du lieu khong nhat quan)",
    )
    con.close()
    print("Xong.")


if __name__ == "__main__":
    main()
