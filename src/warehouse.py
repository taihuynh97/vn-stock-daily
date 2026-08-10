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

# --- Cột raw_financial_ratio (nguồn: Company.ratio_summary, 61 cột) ---
# Loại bỏ có chủ đích: financial_leverage (≡ debt_to_equity, xác minh HPG),
# cost_to_income (≡ cir, xác minh VCB), owners_equity (ngữ nghĩa không rõ),
# ratio_ttm_id / ratio_year_id / organ_code / year_report / equity /
# loans_loss_reserves_to_np_ls / nob66 / nob69 / nob70 / bsb113.
# Nhóm COMMON = có giá trị THẬT ở cả ngân hàng lẫn phi tài chính (xác minh
# VCB vs HPG). Nhóm NONFIN/BANK = bên còn lại trả sentinel 0.0 hoặc None.
RATIO_COMMON = [
    "market_cap", "number_of_shares_mkt_cap", "dividend_yield",
    "pe", "pb", "ps", "roe", "roa", "debt_to_equity",
    "gross_margin", "pre_tax_profit_margin", "after_tax_profit_margin",
    "price_to_cash_flow",   # VCB 2,20 — giá trị thật, KHÔNG phải sentinel
]
RATIO_NONFIN = [
    "roic", "ev_to_ebitda",
    "current_ratio", "quick_ratio", "cash_ratio", "ebit_margin",
    "asset_turnover", "fixed_asset_turnover", "cash_cycle",
    "day_sale_outstanding", "days_inventory_outstanding",
    "days_payable_outstanding", "ebit", "ebitda", "debt_per_equity",
]
RATIO_BANK = [
    "net_interest_margin", "average_yield_on_earning_assets",
    "average_cost_of_financing", "non_and_interest_income", "cir",
    "loans_growth", "deposit_growth", "equity_to_liabilities",
    "equity_to_loans", "total_equity_total_asset", "ldr_loan_deposit_ratio",
    "npl", "loans_loss_reserve_to_loans", "provision_to_outstanding_loans",
    "car", "casa_ratio",
]
RATIO_NUM_COLS = RATIO_COMMON + RATIO_NONFIN + RATIO_BANK          # 44
RATIO_ALL_COLS = [
    "symbol", "year", "quarter", "period_type", "ratio_type",
] + RATIO_NUM_COLS                                                  # 49

# --- Cột raw_company_info (nguồn: Company.overview, 37 cột) ---
# Không lấy: analyst, target_price, upside_to_target_percent,
# projected_tsr_percentage, rating — là khuyến nghị của bên thứ ba, không
# phải dữ kiện; đưa vào sẽ khiến agent trích dẫn nhầm thành phân tích riêng.
COMPANY_COLS = [
    "symbol", "company_name", "short_name", "exchange", "com_type_code",
    "is_bank", "icb_code_lv2", "icb_code_lv4", "sector",
    "market_cap", "issue_share", "free_float_percentage",
    "foreigner_percentage", "maximum_foreign_percentage", "state_percentage",
    "avg_match_value_1m", "avg_match_volume_1m",
    "highest_price_1y", "lowest_price_1y", "listed_date",
]


def get_conn():
    db = os.getenv("WAREHOUSE_DB", DEFAULT_DB)
    if db.startswith("md:"):
        return duckdb.connect(db)  # MotherDuck tự đọc motherduck_token từ env
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(db)


def _ensure_column(con, table: str, column: str, ddl_type: str) -> None:
    """Thêm cột nếu chưa có (migration nhẹ, chạy lại an toàn)."""
    existing = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?",
            [table],
        ).fetchall()
    }
    if column not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


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
        CREATE TABLE IF NOT EXISTS dim_industry (
            icb_code    VARCHAR PRIMARY KEY,
            icb_name    VARCHAR,
            en_icb_name VARCHAR,
            level       INTEGER,
            loaded_at   TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS raw_index_daily (
            index_code VARCHAR,
            trade_date DATE,
            open       DOUBLE,
            high       DOUBLE,
            low        DOUBLE,
            close      DOUBLE,
            volume     BIGINT,
            loaded_at  TIMESTAMP,
            PRIMARY KEY (index_code, trade_date)
        );
        """
    )
    ratio_cols_ddl = ",\n            ".join(f"{c} DOUBLE" for c in RATIO_NUM_COLS)
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS raw_financial_ratio (
            symbol      VARCHAR,
            year        INTEGER,
            quarter     INTEGER,
            period_type VARCHAR,
            ratio_type  VARCHAR,
            {ratio_cols_ddl},
            loaded_at   TIMESTAMP,
            PRIMARY KEY (symbol, year, quarter)
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_company_info (
            symbol                     VARCHAR PRIMARY KEY,
            company_name               VARCHAR,
            short_name                 VARCHAR,
            exchange                   VARCHAR,
            com_type_code              VARCHAR,
            is_bank                    BOOLEAN,
            icb_code_lv2               VARCHAR,
            icb_code_lv4               VARCHAR,
            sector                     VARCHAR,
            market_cap                 DOUBLE,
            issue_share                DOUBLE,
            free_float_percentage      DOUBLE,
            foreigner_percentage       DOUBLE,
            maximum_foreign_percentage DOUBLE,
            state_percentage           DOUBLE,
            avg_match_value_1m         DOUBLE,
            avg_match_volume_1m        DOUBLE,
            highest_price_1y           DOUBLE,
            lowest_price_1y            DOUBLE,
            listed_date                DATE,
            loaded_at                  TIMESTAMP
        );
        """
    )
    # Bảng raw_financial_ratio có thể đã tồn tại từ trước (schema cũ 13 cột,
    # vd. trên MotherDuck production) — CREATE TABLE IF NOT EXISTS ở trên sẽ
    # no-op trong trường hợp đó. Dùng _ensure_column để migrate thêm các cột
    # mới (an toàn, chạy lại nhiều lần được), tránh BinderException khi
    # upsert_financial_ratios ghi vào cột chưa tồn tại trên bảng cũ.
    _ensure_column(con, "raw_financial_ratio", "ratio_type", "VARCHAR")
    for col in RATIO_NUM_COLS:
        _ensure_column(con, "raw_financial_ratio", col, "DOUBLE")
    _ensure_column(con, "etl_load_log", "rows_rejected", "BIGINT")
    # raw_company_info cũng đã tồn tại từ trước (schema cũ 7 cột trên
    # MotherDuck) — migrate thêm các cột mới của COMPANY_COLS tương tự trên.
    _company_ddl_types = {
        "is_bank": "BOOLEAN", "market_cap": "DOUBLE", "issue_share": "DOUBLE",
        "free_float_percentage": "DOUBLE", "foreigner_percentage": "DOUBLE",
        "maximum_foreign_percentage": "DOUBLE", "state_percentage": "DOUBLE",
        "avg_match_value_1m": "DOUBLE", "avg_match_volume_1m": "DOUBLE",
        "highest_price_1y": "DOUBLE", "lowest_price_1y": "DOUBLE",
        "listed_date": "DATE",
    }
    for col in COMPANY_COLS:
        _ensure_column(con, "raw_company_info", col, _company_ddl_types.get(col, "VARCHAR"))


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
    cols = ", ".join(RATIO_ALL_COLS)
    con.register("df_fin", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_financial_ratio ({cols}, loaded_at)
        SELECT {cols}, now() FROM df_fin;
        """
    )
    con.unregister("df_fin")
    return len(df)


def upsert_company_info(con, df) -> int:
    if df is None or df.empty:
        return 0
    cols = ", ".join(COMPANY_COLS)
    con.register("df_ci", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_company_info ({cols}, loaded_at)
        SELECT {cols}, now() FROM df_ci;
        """
    )
    con.unregister("df_ci")
    return len(df)


def upsert_industries(con, df) -> int:
    if df is None or df.empty:
        return 0
    con.register("df_ind", df)
    con.execute(
        """
        INSERT OR REPLACE INTO dim_industry
            (icb_code, icb_name, en_icb_name, level, loaded_at)
        SELECT icb_code, icb_name, en_icb_name, level, now() FROM df_ind;
        """
    )
    con.unregister("df_ind")
    return len(df)


def upsert_index_prices(con, df) -> int:
    """Ghi giá chỉ số (VNINDEX/VN30/HNXINDEX). INSERT OR REPLACE theo
    (index_code, trade_date) → chạy lại an toàn. raw_index_daily là bảng mới,
    chưa tồn tại trên MotherDuck nên không cần _ensure_column như các bảng cũ."""
    if df is None or df.empty:
        return 0
    con.register("df_idx", df)
    con.execute(
        """
        INSERT OR REPLACE INTO raw_index_daily
            (index_code, trade_date, open, high, low, close, volume, loaded_at)
        SELECT index_code, trade_date, open, high, low, close, volume, now()
        FROM df_idx;
        """
    )
    con.unregister("df_idx")
    return len(df)


def update_symbol_exchanges(con) -> int:
    """Đồng bộ dim_symbols.exchange từ raw_company_info (đang NULL 100%)."""
    n = con.execute(
        """
        SELECT count(*) FROM dim_symbols d JOIN raw_company_info c USING (symbol)
        WHERE c.exchange IS NOT NULL
          AND (d.exchange IS DISTINCT FROM c.exchange)
        """
    ).fetchone()[0]
    con.execute(
        """
        UPDATE dim_symbols AS d
        SET exchange = c.exchange
        FROM raw_company_info AS c
        WHERE d.symbol = c.symbol AND c.exchange IS NOT NULL
        """
    )
    return n


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


def log_load(con, job_name, table, rows, status, watermark="", notes="",
             rows_rejected=0):
    con.execute(
        """
        INSERT INTO etl_load_log
            (job_name, target_table, run_at, rows_loaded, status,
             watermark, notes, rows_rejected)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [job_name, table, datetime.now(timezone.utc), rows, status,
         watermark, notes, rows_rejected],
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
