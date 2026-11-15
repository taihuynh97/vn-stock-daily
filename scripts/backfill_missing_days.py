"""Backfill giá EOD, chỉ số và tỷ giá cho các ngày job daily bị lỗi (vd. CI fail do
MotherDuck/DuckDB version mismatch 17-18/6/2026, vnstock bị khai tử 09–13/11/2026).

build_warehouse.py chỉ lấy dữ liệu NGÀY CHẠY (bảng giá realtime, chỉ số và tỷ giá
của run_date), nên không thể lấp ngày đã qua bằng job đó. Script này dùng lịch sử
giá (start/end tuỳ ý) cho từng mã, giống backfill.py nhưng không phụ thuộc
backfill_status (mã đã "done" sẽ bị bỏ qua bởi get_pending_symbols); kèm chỉ số
(config/warehouse.yml) và tỷ giá VCB từng ngày giao dịch. Khối ngoại theo mã KHÔNG
lấy lại được (chỉ bảng giá trong ngày có).

INSERT OR REPLACE ở mọi bảng nên chạy lại an toàn.

Chạy:
    # Cả phiên bị lỡ: giá mọi mã + chỉ số + tỷ giá.
    python scripts/backfill_missing_days.py --start 2026-11-09 --end 2026-11-13
    # Chỉ mã bị thiếu (vd. lô bảng giá lỗi nguồn 05/10/2026), xem trước rồi mới ghi:
    python scripts/backfill_missing_days.py --start 2026-10-05 --end 2026-10-05 --missing-only --dry-run
"""
import argparse
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from src import ingest_market, warehouse

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def backfill_index_fx(con, start: str, end: str, indices: list[str]) -> tuple[int, int]:
    """Nạp bù chỉ số (một lần gọi mỗi mã chỉ số cho cả khoảng) và tỷ giá VCB
    (một lần gọi mỗi ngày giao dịch). Job daily chỉ lấy ngày chạy nên phiên bị
    lỡ không tự lấp (09–13/11/2026). Trả (số dòng chỉ số, số dòng tỷ giá).

    Chỉ ghi dòng trong [start, end]; INSERT OR REPLACE nên chạy lại an toàn."""
    n_idx = 0
    for code in indices:
        df = ingest_market.fetch_index_history(code, start, end)
        if not df.empty:
            df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
        n_idx += warehouse.upsert_index_prices(con, df)
        print(f"  chỉ số {code}: {len(df)} phiên")

    n_fx = 0
    for d in pd.date_range(start, end):
        if not ingest_market.is_trading_day(d.date()):
            continue
        day = d.strftime("%Y-%m-%d")
        n = warehouse.upsert_exchange_rate(con, ingest_market.fetch_exchange_rate(day))
        n_fx += n
        print(f"  tỷ giá {day}: {n} dòng" + ("" if n else " (nguồn rỗng/lỗi)"))
    return n_idx, n_fx


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
    # Cả phiên bị lỡ (không phải --missing-only) thì chỉ số và tỷ giá cũng thiếu.
    indices = [] if args.missing_only else yaml.safe_load(
        open(ROOT / "config" / "warehouse.yml", encoding="utf-8")).get("indices", [])
    print(f"Backfill {args.start} → {args.end} cho {len(symbols)} mã"
          + (f" + chỉ số {', '.join(indices)} + tỷ giá VCB" if indices else "") + "...")
    if args.dry_run:
        print(" ".join(symbols))
        con.close()
        return

    if indices:
        n_idx, n_fx = backfill_index_fx(con, args.start, args.end, indices)
        warehouse.log_load(con, "backfill_missing_days", "raw_index_daily", n_idx,
                           "ok" if n_idx else "empty", watermark=args.end,
                           notes=f"range={args.start}..{args.end}")
        warehouse.log_load(con, "backfill_missing_days", "raw_exchange_rate", n_fx,
                           "ok" if n_fx else "empty", watermark=args.end,
                           notes=f"range={args.start}..{args.end}")
        print(f"Chỉ số: {n_idx} dòng; tỷ giá: {n_fx} dòng")

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
