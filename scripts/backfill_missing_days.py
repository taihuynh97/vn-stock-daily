"""Backfill giá EOD cho các ngày job daily bị lỗi (vd. CI fail do MotherDuck/DuckDB
version mismatch ngày 17-18/6/2026).

build_warehouse.py dùng price_board (chỉ lấy giá realtime "hôm nay"), nên không thể
backfill ngày đã qua bằng job đó. Script này dùng Quote.history (start/end tuỳ ý) cho
từng mã, giống cơ chế của backfill.py nhưng không phụ thuộc backfill_status (vì mã đã
"done" sẽ bị bỏ qua bởi get_pending_symbols).

INSERT OR REPLACE trong upsert_prices nên chạy lại an toàn.

Chạy:
    python scripts/backfill_missing_days.py --start 2026-06-17 --end 2026-06-18
    # Chỉ mã bị thiếu (vd. lô bảng giá lỗi nguồn 05/10/2026), xem trước rồi mới ghi:
    python scripts/backfill_missing_days.py --start 2026-10-05 --end 2026-10-05 --missing-only --dry-run
"""
import argparse

from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()


def missing_symbols(con, start: str, end: str) -> list[str]:
    """Mã có giá ở phiên liền trước nhưng thiếu ở một phiên trong [start, end].

    Phiên = ngày có giá của ít nhất một mã. Bỏ mã OTC (đã huỷ niêm yết — từ
    05/10/2026 bảng giá không còn ghi dòng phiên cũ cho các mã này)."""
    rows = con.execute("""
        WITH sessions AS (
            SELECT DISTINCT trade_date FROM raw_price_daily
            WHERE trade_date <= CAST(? AS DATE)),
        pairs AS (
            SELECT trade_date AS d,
                   lag(trade_date) OVER (ORDER BY trade_date) AS prev_d
            FROM sessions)
        SELECT DISTINCT p.symbol
        FROM pairs
        JOIN raw_price_daily p ON p.trade_date = pairs.prev_d
        LEFT JOIN dim_symbols s ON s.symbol = p.symbol
        WHERE pairs.d BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
          AND coalesce(s.exchange, '') <> 'OTC'
          AND NOT EXISTS (SELECT 1 FROM raw_price_daily q
                          WHERE q.symbol = p.symbol AND q.trade_date = pairs.d)
        ORDER BY 1""", [end, start, end]).fetchall()
    return [r[0] for r in rows]


def keep_rows(con, df, start: str, end: str, missing_only: bool):
    """Chỉ giữ dòng trong [start, end] — Quote.history trả thêm vài phiên trước
    `start` (đo 06/10/2026: xin 05/10 nhận cả 01/10, 02/10). Với --missing-only
    bỏ luôn dòng đã có, để không xoá ref_price/khối ngoại của bảng giá."""
    df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
    if missing_only and not df.empty:
        have = {str(r[0]) for r in con.execute(
            "SELECT trade_date FROM raw_price_daily WHERE symbol = ? "
            "AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)",
            [df["symbol"].iloc[0], start, end]).fetchall()}
        df = df[~df["trade_date"].isin(have)]
    return df


def main():
    parser = argparse.ArgumentParser(description="Backfill giá EOD cho range ngày bị thiếu")
    parser.add_argument("--start", required=True, help="Ngày bắt đầu YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Ngày kết thúc YYYY-MM-DD")
    parser.add_argument("--missing-only", action="store_true",
                        help="Chỉ nạp mã có giá phiên trước nhưng thiếu trong khoảng ngày")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in danh sách mã, không gọi nguồn")
    args = parser.parse_args()

    cfg_source = "VCI"

    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    if args.missing_only:
        symbols = missing_symbols(con, args.start, args.end)
    else:
        symbols = warehouse.get_active_symbols(con)
    print(f"Backfill {args.start} → {args.end} cho {len(symbols)} mã...")
    if args.dry_run:
        print(" ".join(symbols))
        con.close()
        return

    done = error = total_rows = 0
    for i, symbol in enumerate(symbols, 1):
        df = ingest_market.fetch_history_one(symbol, args.start, args.end, cfg_source)
        if df.empty:
            error += 1
            continue
        df = keep_rows(con, df, args.start, args.end, args.missing_only)
        if df.empty:
            done += 1
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
