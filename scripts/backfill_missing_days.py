"""Backfill giá EOD cho các ngày job daily bị lỗi (vd. CI fail do MotherDuck/DuckDB
version mismatch ngày 17-18/6/2026).

build_warehouse.py dùng price_board (chỉ lấy giá realtime "hôm nay"), nên không thể
backfill ngày đã qua bằng job đó. Script này dùng Quote.history (start/end tuỳ ý) cho
từng mã, giống cơ chế của backfill.py nhưng không phụ thuộc backfill_status (vì mã đã
"done" sẽ bị bỏ qua bởi get_pending_symbols).

INSERT OR REPLACE trong upsert_prices nên chạy lại an toàn.

Chạy:
    python scripts/backfill_missing_days.py --start 2026-06-17 --end 2026-06-18
"""
import argparse

from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Backfill giá EOD cho range ngày bị thiếu")
    parser.add_argument("--start", required=True, help="Ngày bắt đầu YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Ngày kết thúc YYYY-MM-DD")
    args = parser.parse_args()

    cfg_source = "VCI"

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    symbols = warehouse.get_active_symbols(con)
    print(f"Backfill {args.start} → {args.end} cho {len(symbols)} mã...")

    done = error = total_rows = 0
    for i, symbol in enumerate(symbols, 1):
        df = ingest_market.fetch_history_one(symbol, args.start, args.end, cfg_source)
        if df.empty:
            error += 1
            continue
        n = warehouse.upsert_prices(con, df)
        total_rows += n
        done += 1
        if i % 50 == 0 or i == len(symbols):
            print(f"  [{i}/{len(symbols)}] done={done} error={error} rows={total_rows}")

    warehouse.log_load(
        con, "backfill_missing_days", "raw_price_daily", total_rows,
        "ok" if error == 0 else "partial",
        watermark=args.end,
        notes=f"range={args.start}..{args.end} done={done} error={error}",
    )
    print(f"\nXong: done={done} error={error} rows={total_rows}")
    con.close()


if __name__ == "__main__":
    main()
