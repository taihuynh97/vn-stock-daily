"""Warehouse layer — DuckDB (local file hoặc MotherDuck cloud).

Kết nối qua biến môi trường WAREHOUSE_DB:
  - mặc định: data/warehouse.duckdb  (file local, để test)
  - md:vn_market                     (MotherDuck cloud — cần motherduck_token)
Cùng một code chạy được cho cả hai, không cần sửa gì.

Phase 1 gồm: dim_symbols (danh sách mã), raw_price_daily (giá EOD),
etl_load_log (nhật ký load — để incremental & debug).
"""
import os
from pathlib import Path
from datetime import datetime, timezone, date, timedelta

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = str(ROOT / "data" / "warehouse.duckdb")


def get_conn():
    db = os.getenv("WAREHOUSE_DB", DEFAULT_DB)
    if db.startswith("md:"):
        return duckdb.connect(db)  # MotherDuck tự đọc motherduck_token từ env
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(db)


def init_warehouse(con):
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS dim_symbols (
            symbol       VARCHAR PRIMARY KEY,
            exchange     VARCHAR,
            company_name VARCHAR,
            is_active    BOOLEAN DEFAULT TRUE,
            first_seen   DATE,
            last_seen    DATE
        );
        CREATE TABLE IF NOT EXISTS raw_price_daily (
            symbol     VARCHAR,
            trade_date DATE,
            open       DOUBLE,
            high       DOUBLE,
            low        DOUBLE,
            close      DOUBLE,
            volume     BIGINT,
            value      DOUBLE,
            loaded_at  TIMESTAMP,
            PRIMARY KEY (symbol, trade_date)
        );
        CREATE TABLE IF NOT EXISTS etl_load_log (
            job_name     VARCHAR,
            target_table VARCHAR,
            run_at       TIMESTAMP,
            rows_loaded  BIGINT,
            status       VARCHAR,
            watermark    VARCHAR,
            notes        VARCHAR
        );
        CREATE TABLE IF NOT EXISTS raw_financial_ratio (
            symbol      VARCHAR,
            period      VARCHAR,
            period_type VARCHAR,
            pe          DOUBLE,
            pb          DOUBLE,
            roe         DOUBLE,
            roa         DOUBLE,
            eps         DOUBLE,
            loaded_at   TIMESTAMP,
            PRIMARY KEY (symbol, period, period_type)
        );
        CREATE TABLE IF NOT EXISTS raw_company_info (
            symbol        VARCHAR PRIMARY KEY,
            company_name  VARCHAR,
            exchange      VARCHAR,
            industry_icb  VARCHAR,
            sector        VARCHAR,
            listed_date   DATE,
            loaded_at     TIMESTAMP
        );
        """
    )


def upsert_symbols(con, df, run_date) -> int:
    """Cập nhật dim_symbols. Giữ nguyên first_seen, cập nhật last_seen."""
    if df is None or df.empty:
        return 0
    con.register("df_sym", df)
    con.execute(
        f"""
        INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, first_seen, last_seen)
        SELECT symbol, exchange, company_name, TRUE, DATE '{run_date}', DATE '{run_date}'
        FROM df_sym
        ON CONFLICT (symbol) DO UPDATE SET
            exchange     = excluded.exchange,
            company_name = excluded.company_name,
            is_active    = TRUE,
            last_seen    = DATE '{run_date}';
        """
    )
    con.unregister("df_sym")
    return len(df)


def upsert_prices(con, df) -> int:
    """Ghi giá EOD. INSERT OR REPLACE theo (symbol, trade_date) → chạy lại an toàn."""
    if df is None or df.empty:
        return 0
    con.register("df_px", df)
    con.execute(
        """
        INSERT OR REPLACE INTO raw_price_daily
        SELECT symbol, trade_date, open, high, low, close, volume, value, now()
        FROM df_px;
        """
    )
    con.unregister("df_px")
    return len(df)


def upsert_financial_ratios(con, df) -> int:
    if df is None or df.empty:
        return 0
    con.register("df_fin", df)
    con.execute(
        """
        INSERT OR REPLACE INTO raw_financial_ratio
        SELECT symbol, period, period_type, pe, pb, roe, roa, eps, now()
        FROM df_fin;
        """
    )
    con.unregister("df_fin")
    return len(df)


def upsert_company_info(con, df) -> int:
    if df is None or df.empty:
        return 0
    con.register("df_ci", df)
    con.execute(
        """
        INSERT OR REPLACE INTO raw_company_info
        SELECT symbol, company_name, exchange, industry_icb, sector,
               TRY_CAST(listed_date AS DATE), now()
        FROM df_ci;
        """
    )
    con.unregister("df_ci")
    return len(df)


def get_active_symbols(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT symbol FROM dim_symbols WHERE is_active ORDER BY symbol"
    ).fetchall()]


def read_price_history(con, symbol: str, days: int) -> pd.DataFrame:
    """Đọc lịch sử OHLCV từ warehouse. Trả DataFrame với close, volume (tương thích signals.analyze)."""
    start = (date.today() - timedelta(days=days * 2)).isoformat()
    df = con.execute(
        """
        SELECT trade_date, open, high, low, close, volume, value
        FROM raw_price_daily
        WHERE symbol = ? AND trade_date >= ?
        ORDER BY trade_date
        """,
        [symbol.upper().strip(), start],
    ).df()
    return df.tail(days).reset_index(drop=True)


def fix_backfill_price_units(con) -> int:
    """Migration một lần: dữ liệu OHLC từ backfill (Quote.history, value IS NULL)
    bị lệch đơn vị 1000 lần (nghìn VNĐ) so với price_board (VND, value NOT NULL).
    Nhân lại 1000 để raw_price_daily đồng nhất đơn vị VND. Trả về số dòng đã sửa."""
    n = con.execute("SELECT count(*) FROM raw_price_daily WHERE value IS NULL").fetchone()[0]
    con.execute(
        """
        UPDATE raw_price_daily
        SET open = open * 1000, high = high * 1000, low = low * 1000, close = close * 1000
        WHERE value IS NULL
        """
    )
    return n


def delete_trade_date(con, trade_date: str) -> int:
    """Xoá toàn bộ dòng raw_price_daily của một trade_date (vd: dữ liệu phantom
    của ngày không phải phiên giao dịch). Trả về số dòng đã xoá."""
    n = con.execute(
        "SELECT count(*) FROM raw_price_daily WHERE trade_date = ?", [trade_date]
    ).fetchone()[0]
    con.execute("DELETE FROM raw_price_daily WHERE trade_date = ?", [trade_date])
    return n


def log_load(con, job_name, table, rows, status, watermark="", notes=""):
    con.execute(
        "INSERT INTO etl_load_log VALUES (?,?,?,?,?,?,?)",
        [job_name, table, datetime.now(timezone.utc), rows, status, watermark, notes],
    )


def init_backfill_status(con):
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS backfill_status (
            symbol     VARCHAR PRIMARY KEY,
            status     VARCHAR DEFAULT 'pending',
            last_date  DATE,
            notes      VARCHAR,
            updated_at TIMESTAMP
        );
        """
    )


def get_pending_symbols(con) -> list[str]:
    """Trả danh sách mã chưa backfill xong (không có trong backfill_status hoặc status != done)."""
    return [r[0] for r in con.execute(
        """
        SELECT d.symbol
        FROM dim_symbols d
        LEFT JOIN backfill_status b ON d.symbol = b.symbol
        WHERE d.is_active AND (b.symbol IS NULL OR b.status != 'done')
        ORDER BY d.symbol
        """
    ).fetchall()]


def mark_backfill_done(con, symbol: str, last_date: str):
    con.execute(
        """
        INSERT INTO backfill_status (symbol, status, last_date, updated_at)
        VALUES (?, 'done', ?, now())
        ON CONFLICT (symbol) DO UPDATE SET
            status     = 'done',
            last_date  = excluded.last_date,
            notes      = NULL,
            updated_at = excluded.updated_at
        """,
        [symbol, last_date],
    )


def mark_backfill_error(con, symbol: str, note: str):
    con.execute(
        """
        INSERT INTO backfill_status (symbol, status, notes, updated_at)
        VALUES (?, 'error', ?, now())
        ON CONFLICT (symbol) DO UPDATE SET
            status     = 'error',
            notes      = excluded.notes,
            updated_at = excluded.updated_at
        """,
        [symbol, note],
    )
