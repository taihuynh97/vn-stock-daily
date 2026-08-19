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

# --- Cột raw_corporate_event (nguồn: Company.events, 22 cột) ---
# Không lấy: các cột *_en (event_name_en, event_title_en, action_type_en —
# trùng nghĩa với bản tiếng Việt), display_date1/display_date2 (ngữ nghĩa
# không rõ, nguồn không tài liệu hoá), ticker (trùng symbol).
EVENT_COLS = [
    "id", "symbol", "event_code", "event_name_vi", "event_title_vi", "category",
    "public_date", "issue_date", "start_date", "end_date",
    "record_date", "exright_date", "listing_date", "payout_date",
    "exercise_ratio", "value_per_share", "action_type_vi",
]

# --- Cột raw_shareholder / raw_officer (nguồn: Company.shareholders/officers) ---
# snapshot_date do JOB gán (không có ở nguồn): hai bảng này là TRẠNG THÁI,
# không phải dòng sự kiện — xem docstring upsert_shareholders.
SHAREHOLDER_COLS = [
    "symbol", "share_holder", "quantity", "share_own_percent",
    "update_date", "snapshot_date",
]
OFFICER_COLS = [
    "symbol", "officer_name", "officer_position",
    "officer_own_percent", "officer_own_quantity",
    "update_date", "snapshot_date",
]

# --- Cột raw_financial_statement (nguồn: Company.Finance.income_statement/
# balance_sheet/cash_flow, unpivot wide -> dài) ---
# KHÔNG có cột com_class: đó là cột suy ra ở tầng dbt (stg_company_info.sql),
# không tồn tại lúc Python ingest chạy (ingest chạy TRƯỚC dbt build). symbol
# một mình đủ để JOIN dim_stock lấy com_class ở nơi cần lọc theo loại hình DN.
STATEMENT_COLS = [
    "symbol", "statement_type", "period_type", "period_label", "row_seq",
    "item_id", "item_vi", "item_en", "value",
]


def get_conn():
    db = os.getenv("WAREHOUSE_DB", DEFAULT_DB)
    if db.startswith("md:"):
        return duckdb.connect(db)  # MotherDuck tự đọc motherduck_token từ env
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(db)


def _ensure_column(con, table: str, column: str, ddl_type: str) -> None:
    """Thêm cột nếu chưa có (migration nhẹ, chạy lại an toàn).

    information_schema.columns không tự lọc theo catalog/schema hiện tại —
    trên MotherDuck, mọi database ATTACH được (kể cả sample_data mà
    MotherDuck tự attach cho mọi kết nối) đều hiện ra trong cùng truy vấn
    không lọc, nên table_name trùng tên ở catalog khác có thể khiến hàm này
    tưởng cột đã tồn tại trong khi thực ra không phải ở đúng database/schema
    đang dùng. Lọc thêm table_catalog/table_schema để chỉ thấy bảng của kết
    nối hiện tại. Dùng ADD COLUMN IF NOT EXISTS để tự idempotent luôn, không
    phụ thuộc riêng vào kết quả tra existing (tránh CatalogException khi hai
    tiến trình cùng chạy init_warehouse song song)."""
    existing = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND table_catalog = current_database() "
            "AND table_schema = current_schema()",
            [table],
        ).fetchall()
    }
    if column not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl_type}")


def _ensure_columns(con, table: str, columns: dict[str, str]) -> int:
    """Thêm các cột còn thiếu trong `columns` ({tên: kiểu_ddl}).

    Khác _ensure_column (số ít): tra information_schema MỘT LẦN cho cả batch
    thay vì một truy vấn riêng cho từng cột — init_warehouse gọi tới 45 lần
    cho raw_financial_ratio + 20 lần cho raw_company_info, tức hàng chục
    round-trip mạng tới MotherDuck mỗi lần khởi động warehouse nếu dùng
    _ensure_column cho từng cột. Trả về số cột đã thêm.

    Cùng lý do lọc catalog/schema và dùng ADD COLUMN IF NOT EXISTS như
    _ensure_column ở trên."""
    existing = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND table_catalog = current_database() "
            "AND table_schema = current_schema()",
            [table],
        ).fetchall()
    }
    added = 0
    for column, ddl_type in columns.items():
        if column not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl_type}")
            added += 1
    return added


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
    # no-op trong trường hợp đó. Dùng _ensure_columns (tra information_schema
    # một lần cho cả batch, không phải 45 lần) để migrate thêm các cột mới
    # (an toàn, chạy lại nhiều lần được), tránh BinderException khi
    # upsert_financial_ratios ghi vào cột chưa tồn tại trên bảng cũ.
    # loaded_at thêm vào bộ cột được đảm bảo (không chỉ các cột của
    # RATIO_NUM_COLS): nếu một bảng cũ trên production thiếu hẳn cột này,
    # upsert_financial_ratios sẽ chết bằng InternalException của DuckDB (C++
    # stack trace, rất khó chẩn đoán) ngay tại câu SELECT ... now() AS
    # loaded_at khi INSERT vào cột không tồn tại.
    _ratio_ddl_types = {"ratio_type": "VARCHAR", "loaded_at": "TIMESTAMP"}
    _ratio_ddl_types.update({col: "DOUBLE" for col in RATIO_NUM_COLS})
    _ensure_columns(con, "raw_financial_ratio", _ratio_ddl_types)
    _ensure_column(con, "etl_load_log", "rows_rejected", "BIGINT")
    # raw_company_info cũng đã tồn tại từ trước (schema cũ 7 cột trên
    # MotherDuck) — migrate thêm các cột mới của COMPANY_COLS tương tự trên.
    # Cùng lý do loaded_at ở trên: đảm bảo cả cột này dù nó không nằm trong
    # COMPANY_COLS (được thêm riêng lúc upsert_company_info).
    _company_ddl_types = {
        "is_bank": "BOOLEAN", "market_cap": "DOUBLE", "issue_share": "DOUBLE",
        "free_float_percentage": "DOUBLE", "foreigner_percentage": "DOUBLE",
        "maximum_foreign_percentage": "DOUBLE", "state_percentage": "DOUBLE",
        "avg_match_value_1m": "DOUBLE", "avg_match_volume_1m": "DOUBLE",
        "highest_price_1y": "DOUBLE", "lowest_price_1y": "DOUBLE",
        "listed_date": "DATE",
    }
    _ensure_columns(
        con, "raw_company_info",
        {col: _company_ddl_types.get(col, "VARCHAR") for col in COMPANY_COLS}
        | {"loaded_at": "TIMESTAMP"},
    )
    # --- B1: sự kiện DN (append-only) ---
    # id là PRIMARY KEY: cửa sổ Company.events() chỉ 50 sự kiện gần nhất và
    # trượt theo thời gian, nên bảng này CỘNG DỒN chứ không thay thế. Xem
    # insert_corporate_events.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_corporate_event (
            id              VARCHAR PRIMARY KEY,
            symbol          VARCHAR,
            event_code      VARCHAR,
            event_name_vi   VARCHAR,
            event_title_vi  VARCHAR,
            category        VARCHAR,
            public_date     DATE,
            issue_date      DATE,
            start_date      DATE,
            end_date        DATE,
            record_date     DATE,
            exright_date    DATE,
            listing_date    DATE,
            payout_date     DATE,
            exercise_ratio  DOUBLE,
            value_per_share DOUBLE,
            action_type_vi  VARCHAR,
            ingested_at     TIMESTAMP
        );
        """
    )
    # --- B1: cơ cấu sở hữu (snapshot theo ngày) ---
    # snapshot_date nằm trong PRIMARY KEY: chạy lại trong cùng ngày thì thay
    # thế (idempotent), sang kỳ sau thì thêm bản ghi mới — giữ được lịch sử
    # thay đổi sở hữu. Xem docstring upsert_shareholders.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_shareholder (
            symbol            VARCHAR,
            share_holder      VARCHAR,
            quantity          DOUBLE,
            share_own_percent DOUBLE,
            update_date       DATE,
            snapshot_date     DATE,
            ingested_at       TIMESTAMP,
            PRIMARY KEY (symbol, share_holder, snapshot_date)
        );
        CREATE TABLE IF NOT EXISTS raw_officer (
            symbol               VARCHAR,
            officer_name         VARCHAR,
            officer_position     VARCHAR,
            officer_own_percent  DOUBLE,
            officer_own_quantity DOUBLE,
            update_date          DATE,
            snapshot_date        DATE,
            ingested_at          TIMESTAMP,
            PRIMARY KEY (symbol, officer_name, snapshot_date)
        );
        """
    )
    # --- B2: BCTC chi tiết (upsert theo khoá mịn tới từng kỳ) ---
    # PRIMARY KEY gồm cả period_label lẫn row_seq: cửa sổ 8-kỳ trượt theo
    # thời gian giống sự kiện DN, nhưng khoá mịn tới từng kỳ khiến
    # INSERT OR REPLACE không đụng các kỳ đã rơi khỏi cửa sổ fetch mới —
    # xem docstring upsert_financial_statements.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_financial_statement (
            symbol         VARCHAR,
            statement_type VARCHAR,
            period_type    VARCHAR,
            period_label   VARCHAR,
            row_seq        INTEGER,
            item_id        VARCHAR,
            item_vi        VARCHAR,
            item_en        VARCHAR,
            value          DOUBLE,
            ingested_at    TIMESTAMP,
            PRIMARY KEY (symbol, statement_type, period_type, period_label, row_seq)
        );
        """
    )
    # --- C2: chống lặp tin cảnh báo sự kiện ---
    # event_id = stg_corporate_event.id (khoá ổn định, PRIMARY KEY của
    # raw_corporate_event từ B1). KHÔNG dùng SQLite cục bộ (storage.py) —
    # cơ chế cache-based của nó tự nhận best-effort, có thể mất khi GitHub
    # Actions evict cache, gây gửi lặp lại toàn bộ sự kiện cũ.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_sent_log (
            event_id    VARCHAR PRIMARY KEY,
            symbol      VARCHAR,
            alerted_at  TIMESTAMP
        );
        """
    )


def upsert_symbols(con, df, run_date) -> int:
    """Cập nhật dim_symbols. Giữ nguyên first_seen, cập nhật last_seen.

    COALESCE(excluded.exchange, dim_symbols.exchange) — KHÔNG ghi đè bằng
    NULL: refresh_universe (job daily, T2-T6) chạy trên Listing.all_symbols()
    hiện không trả cột sàn (API thật chỉ có symbol/organ_name) nên gán
    exchange=None cho toàn bộ universe mỗi lần chạy. Trước bản sửa này, upsert
    vô điều kiện khiến job daily xoá trắng dim_symbols.exchange mà job
    monthly (update_symbol_exchanges, qua raw_company_info) vừa điền cho
    ~1.587 mã — ngay lần chạy daily kế tiếp sau monthly. Cùng lý do áp cho
    company_name (job daily cũng không có company_name đáng tin/đầy đủ hơn
    job monthly)."""
    if df is None or df.empty:
        return 0
    con.register("df_sym", df)
    con.execute(
        f"""
        INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, first_seen, last_seen)
        SELECT symbol, exchange, company_name, TRUE, DATE '{run_date}', DATE '{run_date}'
        FROM df_sym
        ON CONFLICT (symbol) DO UPDATE SET
            exchange     = COALESCE(excluded.exchange, dim_symbols.exchange),
            company_name = COALESCE(excluded.company_name, dim_symbols.company_name),
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


def insert_corporate_events(con, df) -> int:
    """Ghi sự kiện DN — APPEND-ONLY: chỉ chèn `id` chưa có, không ghi đè.

    KHÁC upsert_prices/upsert_financial_ratios (INSERT OR REPLACE) một cách
    có chủ đích. Company.events() chỉ trả 50 sự kiện GẦN NHẤT mỗi mã và cửa
    sổ đó TRƯỢT: đo trên 15 mã (2026-08-16), 50 sự kiện phủ từ 1,0 năm
    (MWG) tới 9,9 năm (AGX) tuỳ mã hoạt động sự kiện nhiều hay ít. Mã năng
    động rơi mất sự kiện cũ nhất sau mỗi lần công bố sự kiện mới — nếu bảng
    này thay thế theo mỗi mẻ fetch thì phần rơi khỏi cửa sổ mất vĩnh viễn.
    Cộng dồn thì ngược lại: chạy đều mỗi tuần, lịch sử dày lên theo thời
    gian bất kể giới hạn API.

    Trả về số dòng THỰC SỰ được thêm (không phải len(df)) — con số này vào
    thẳng etl_load_log để theo dõi tốc độ tích luỹ.
    """
    if df is None or df.empty:
        return 0
    before = con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0]
    cols = ", ".join(EVENT_COLS)
    con.register("df_ev", df)
    con.execute(
        f"""
        INSERT INTO raw_corporate_event ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_ev src
        WHERE src.id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM raw_corporate_event t WHERE t.id = src.id
          );
        """
    )
    con.unregister("df_ev")
    after = con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0]
    return after - before


def upsert_shareholders(con, df) -> int:
    """Ghi snapshot cơ cấu cổ đông. INSERT OR REPLACE theo
    (symbol, share_holder, snapshot_date) → chạy lại trong cùng ngày an toàn.

    KHÁC insert_corporate_events (append-only theo id): cổ đông là dữ liệu
    TRẠNG THÁI, không phải dòng sự kiện. Nguồn không có id ổn định, và thứ
    có giá trị là THAY ĐỔI theo thời gian ("quỹ ngoại giảm từ 8% xuống
    5%"). Cộng dồn không phân biệt được "cổ đông mới xuất hiện" với "cổ
    đông cũ đổi tỉ lệ"; snapshot theo ngày thì phân biệt được cả hai.
    """
    if df is None or df.empty:
        return 0
    cols = ", ".join(SHAREHOLDER_COLS)
    con.register("df_sh", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_shareholder ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_sh;
        """
    )
    con.unregister("df_sh")
    return len(df)


def upsert_officers(con, df) -> int:
    """Ghi snapshot ban lãnh đạo + tỉ lệ sở hữu. Cùng cơ chế snapshot như
    upsert_shareholders (xem docstring hàm đó)."""
    if df is None or df.empty:
        return 0
    cols = ", ".join(OFFICER_COLS)
    con.register("df_of", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_officer ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_of;
        """
    )
    con.unregister("df_of")
    return len(df)


def upsert_financial_statements(con, df) -> int:
    """Ghi chi tiết BCTC. INSERT OR REPLACE theo khoá 5 cột (symbol,
    statement_type, period_type, period_label, row_seq) → chạy lại cùng kỳ
    an toàn.

    Cửa sổ 8-kỳ mà Company.income_statement()/balance_sheet()/cash_flow()
    trả về CŨNG trượt theo thời gian (giống sự kiện DN) — kỳ mới xuất
    hiện, kỳ cũ nhất rơi khỏi cửa sổ. Nhưng KHÁC insert_corporate_events
    (phải append-only vì đơn vị trùng lặp là toàn bộ sự kiện, không gì
    phân biệt "sự kiện cũ" ngoài chính nó): ở đây khoá mịn tới từng KỲ
    (period_label nằm trong khoá cùng row_seq), nên khi kỳ cũ nhất rơi
    khỏi batch mới, INSERT OR REPLACE đơn giản KHÔNG ĐỤNG tới khoá đó —
    nó vẫn còn nguyên từ lần ghi trước. Ghi đè chỉ xảy ra khi CÙNG kỳ
    được fetch lại (giá trị hiếm khi đổi, nhưng nếu đổi thì bản mới đúng
    hơn).
    """
    if df is None or df.empty:
        return 0
    cols = ", ".join(STATEMENT_COLS)
    con.register("df_st", df)
    con.execute(
        f"""
        INSERT OR REPLACE INTO raw_financial_statement ({cols}, ingested_at)
        SELECT {cols}, now() FROM df_st;
        """
    )
    con.unregister("df_st")
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


def mark_events_alerted(con, event_ids: list[str], symbol_by_id: dict[str, str]) -> int:
    """Ghi các event_id đã gửi/đã biết vào alert_sent_log — chống lặp tin.

    event_id là PRIMARY KEY: gọi lại với cùng event_id là lỗi ở tầng gọi
    (một sự kiện chỉ được đánh dấu đã biết đúng 1 lần), không silently
    ignore — để lộ bug sớm thay vì che giấu.
    """
    if not event_ids:
        return 0
    now = datetime.now(timezone.utc)
    con.executemany(
        "INSERT INTO alert_sent_log (event_id, symbol, alerted_at) VALUES (?, ?, ?)",
        [(eid, symbol_by_id[eid], now) for eid in event_ids],
    )
    return len(event_ids)
