"""Sửa lịch sử raw_price_daily sau lỗi ánh xạ bảng giá (mảng Q).

Ba việc, theo đúng thứ tự:

1. Xoá PHIÊN MA: ngày nằm trong khoảng của lịch phiên VNINDEX nhưng VNINDEX
   không có phiên, VÀ phần lớn dòng hôm đó chép y nguyên phiên trước (close
   và volume bằng nhau). Phải chạy TRƯỚC bước 2 — sau khi ghi đè lịch sử,
   phiên trước đổi giá trị và dấu hiệu "chép y nguyên" biến mất.
2. Nạp lại lịch sử từng mã qua Quote.history (giá đã điều chỉnh tới hôm nay)
   từ ngày đầu tiên đang có, ghi đè open/high/low/close/volume. GIỮ `value`
   và khối ngoại đang có (Quote.history không có hai thứ này). `ref_price`
   của dòng sửa = NULL: giá tham chiếu cũ thuộc hệ giá chưa điều chỉnh, ghép
   với close đã điều chỉnh sẽ sinh sự kiện giả ở int_price_adjustment.
3. `loaded_at` của dòng sửa = thời điểm sửa — dbt coi đó là "mốc điều chỉnh":
   dòng đã được nguồn điều chỉnh cho mọi sự kiện trước mốc này.

Mặc định chỉ in kế hoạch (dry-run). Thêm --apply mới ghi.

    python scripts/repair_price_history.py                       # dry-run, WAREHOUSE_DB
    python scripts/repair_price_history.py --db md:vn_market --apply
    python scripts/repair_price_history.py --symbols TRC,PHR --apply
    python scripts/repair_price_history.py --apply --since "2026-10-04 09:00"   # chạy tiếp

Nên chạy ngoài giờ giao dịch (sau 15:00 hoặc cuối tuần): trong phiên,
Quote.history trả cả nến hôm nay chưa chốt.
"""
import argparse
import os
import time
from datetime import date, datetime

import pandas as pd
from dotenv import load_dotenv

from src import ingest_market, warehouse

# Tỷ lệ dòng "chép y nguyên phiên trước" tối thiểu để coi một ngày ngoài lịch
# VNINDEX là phiên ma. Đo ngày 31/08/2026: 55,6% (chỉ tính dòng có khớp lệnh);
# tính cả dòng không khớp lệnh còn cao hơn. Ngày thật bị thiếu chỉ số do lỗi
# nạp sẽ có giá thay đổi ở đa số mã → tỷ lệ thấp → không bị xoá nhầm.
PHANTOM_MIN_COPY_SHARE = 0.4

_PHANTOM_SQL = """
WITH idx AS (
    SELECT DISTINCT trade_date FROM raw_index_daily WHERE index_code = 'VNINDEX'
),
bounds AS (SELECT min(trade_date) AS lo, max(trade_date) AS hi FROM idx),
p AS (
    SELECT symbol, trade_date, close, volume,
           lag(close)  OVER w AS prev_close,
           lag(volume) OVER w AS prev_volume
    FROM raw_price_daily
    WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
)
SELECT p.trade_date,
       count(*) AS n_rows,
       avg(CASE WHEN p.close = p.prev_close AND p.volume = p.prev_volume
                THEN 1.0 ELSE 0.0 END) AS copy_share
FROM p, bounds
WHERE p.trade_date BETWEEN bounds.lo AND bounds.hi
  AND p.trade_date NOT IN (SELECT trade_date FROM idx)
GROUP BY 1
HAVING avg(CASE WHEN p.close = p.prev_close AND p.volume = p.prev_volume
                THEN 1.0 ELSE 0.0 END) >= ?
ORDER BY 1
"""


def phantom_sessions(con) -> pd.DataFrame:
    """Các ngày bị coi là phiên ma: [trade_date, n_rows, copy_share]."""
    return con.execute(_PHANTOM_SQL, [PHANTOM_MIN_COPY_SHARE]).df()


def delete_phantom_sessions(con) -> int:
    """Xoá mọi dòng của các phiên ma. Trả số dòng đã xoá."""
    ph = phantom_sessions(con)
    n = 0
    for d in ph["trade_date"]:
        n += warehouse.delete_trade_date(con, pd.Timestamp(d).date().isoformat())
    return n


def symbol_ranges(con, symbols=None, repaired_since: datetime | None = None) -> pd.DataFrame:
    """[symbol, first_date] cho mỗi mã có trong raw_price_daily.

    `repaired_since`: bỏ mã mà MỌI dòng đã có loaded_at >= mốc này (đã sửa ở
    lần chạy trước) — để chạy tiếp sau khi bị ngắt."""
    where, params = "", []
    if symbols:
        where = f"WHERE symbol IN ({', '.join('?' for _ in symbols)})"
        params += [s.upper().strip() for s in symbols]
    having = ""
    if repaired_since is not None:
        having = "HAVING min(loaded_at) < ?"
        params.append(repaired_since)
    return con.execute(
        f"SELECT symbol, min(trade_date) AS first_date FROM raw_price_daily "
        f"{where} GROUP BY symbol {having} ORDER BY symbol",
        params,
    ).df()


def merge_history(con, hist: pd.DataFrame, repaired_at: datetime) -> int:
    """Ghi đè OHLCV từ lịch sử đã điều chỉnh; giữ value/khối ngoại; ref_price NULL."""
    if hist is None or hist.empty:
        return 0
    h = hist[["symbol", "trade_date", "open", "high", "low", "close", "volume", "value"]].copy()
    con.register("hist_df", h)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _repair_hist AS
        SELECT h.symbol,
               CAST(h.trade_date AS DATE) AS trade_date,
               CAST(h.open AS DOUBLE) AS open, CAST(h.high AS DOUBLE) AS high,
               CAST(h.low AS DOUBLE) AS low, CAST(h.close AS DOUBLE) AS close,
               CAST(h.volume AS BIGINT) AS volume,
               coalesce(CAST(h.value AS DOUBLE), r.value) AS value,
               r.foreign_buy_volume, r.foreign_sell_volume,
               r.foreign_buy_value, r.foreign_sell_value
        FROM hist_df h
        LEFT JOIN raw_price_daily r
               ON r.symbol = h.symbol AND r.trade_date = CAST(h.trade_date AS DATE)
    """)
    con.unregister("hist_df")
    con.execute("""
        INSERT OR REPLACE INTO raw_price_daily
            (symbol, trade_date, open, high, low, close, volume, value, ref_price,
             foreign_buy_volume, foreign_sell_volume, foreign_buy_value,
             foreign_sell_value, loaded_at)
        SELECT symbol, trade_date, open, high, low, close, volume, value, NULL,
               foreign_buy_volume, foreign_sell_volume, foreign_buy_value,
               foreign_sell_value, ?
        FROM _repair_hist
    """, [repaired_at])
    n = con.execute("SELECT count(*) FROM _repair_hist").fetchone()[0]
    con.execute("DROP TABLE _repair_hist")
    return n


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Sửa lịch sử giá sau lỗi ánh xạ bảng giá (mảng Q)")
    ap.add_argument("--db", help="Đích, vd md:vn_market hoặc đường dẫn .duckdb (mặc định WAREHOUSE_DB)")
    ap.add_argument("--symbols", help="Danh sách mã, phân tách bằng dấu phẩy")
    ap.add_argument("--limit", type=int, help="Chỉ xử lý N mã đầu (thử nghiệm)")
    ap.add_argument("--since", help="Chạy tiếp: bỏ mã đã sửa sau mốc này (YYYY-MM-DD HH:MM)")
    ap.add_argument("--source", default="VCI")
    ap.add_argument("--apply", action="store_true", help="Ghi thật (mặc định chỉ in kế hoạch)")
    args = ap.parse_args()

    if args.db:
        os.environ["WAREHOUSE_DB"] = args.db
    con = warehouse.get_conn()
    warehouse.init_warehouse(con)

    ph = phantom_sessions(con)
    print(f"Phiên ma: {len(ph)} ngày, {int(ph['n_rows'].sum()) if len(ph) else 0} dòng")
    for _, r in ph.iterrows():
        print(f"  {pd.Timestamp(r['trade_date']).date()}  {int(r['n_rows'])} dòng  "
              f"chép phiên trước {r['copy_share']:.0%}")

    symbols = [s for s in args.symbols.split(",")] if args.symbols else None
    since = datetime.fromisoformat(args.since) if args.since else None
    ranges = symbol_ranges(con, symbols, since)
    if args.limit:
        ranges = ranges.head(args.limit)
    print(f"Nạp lại lịch sử: {len(ranges)} mã (~{len(ranges) / 60:.0f} phút ở 60 lượt/phút)")

    if not args.apply:
        print("Dry-run — thêm --apply để ghi.")
        con.close()
        return

    n_del = delete_phantom_sessions(con)
    print(f"Đã xoá {n_del} dòng phiên ma")

    repaired_at = datetime.now()
    today = date.today().isoformat()
    done = errors = rows = 0
    t0 = time.time()
    for i, r in enumerate(ranges.itertuples(index=False), 1):
        start = pd.Timestamp(r.first_date).date().isoformat()
        hist = ingest_market.fetch_history_one(r.symbol, start, today, args.source)
        if hist.empty:
            errors += 1
        else:
            rows += merge_history(con, hist, repaired_at)
            done += 1
        if i % 50 == 0 or i == len(ranges):
            print(f"  [{i}/{len(ranges)}] xong={done} lỗi={errors} dòng={rows} "
                  f"({time.time() - t0:.0f}s)", flush=True)

    warehouse.log_load(
        con, "repair_price_history", "raw_price_daily", rows,
        "ok" if errors == 0 else "partial", watermark=today,
        notes=f"repaired_at={repaired_at.isoformat()} done={done} errors={errors} "
              f"phantom_deleted={n_del}",
    )
    print(f"Xong: {done} mã, {errors} lỗi, {rows} dòng. Mốc sửa: {repaired_at.isoformat()}")
    con.close()


if __name__ == "__main__":
    main()
