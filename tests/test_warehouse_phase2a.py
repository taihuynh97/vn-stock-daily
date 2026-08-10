import pandas as pd
import duckdb
import pytest
from src.warehouse import (
    init_warehouse,
    upsert_financial_ratios,
    upsert_company_info,
    RATIO_NUM_COLS,
)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def test_init_creates_financial_ratio_table(con):
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "raw_financial_ratio" in tables


def test_init_creates_company_info_table(con):
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    assert "raw_company_info" in tables


def _ratio_row(**overrides):
    # Bảng raw_financial_ratio nay có 44 cột số (Task 2) — khởi tạo đủ mọi
    # cột về 0.0 rồi override, tránh phải liệt kê thủ công cả 44 cột.
    row = {
        "symbol": "AAA", "year": 2023, "quarter": 5,
        "period_type": "year", "ratio_type": "RATIO_YEAR",
    }
    row.update({col: 0.0 for col in RATIO_NUM_COLS})
    row.update({
        "market_cap": 1.0e13, "pe": 10.0, "pb": 1.5, "ps": 1.2,
        "dividend_yield": 0.03, "roe": 0.15, "roa": 0.08, "roic": 0.12,
        "debt_to_equity": 0.5, "current_ratio": 1.8, "gross_margin": 0.2,
        "ebit_margin": 0.18, "after_tax_profit_margin": 0.15,
    })
    row.update(overrides)
    return row


def test_upsert_financial_ratios_returns_row_count(con):
    df = pd.DataFrame([_ratio_row()])
    n = upsert_financial_ratios(con, df)
    assert n == 1


def test_upsert_financial_ratios_idempotent(con):
    df = pd.DataFrame([_ratio_row()])
    upsert_financial_ratios(con, df)
    upsert_financial_ratios(con, df)
    count = con.execute("SELECT COUNT(*) FROM raw_financial_ratio").fetchone()[0]
    assert count == 1


def test_upsert_financial_ratios_updates_pe(con):
    df1 = pd.DataFrame([_ratio_row(pe=10.0)])
    df2 = pd.DataFrame([_ratio_row(pe=12.0)])
    upsert_financial_ratios(con, df1)
    upsert_financial_ratios(con, df2)
    pe = con.execute(
        "SELECT pe FROM raw_financial_ratio WHERE symbol='AAA' AND year=2023 AND quarter=5"
    ).fetchone()[0]
    assert pe == 12.0


def test_init_warehouse_migrates_old_13_col_financial_ratio_table():
    """Production (MotherDuck) có thể đã có raw_financial_ratio với schema cũ
    13 cột từ trước Task 2. CREATE TABLE IF NOT EXISTS no-op trên bảng đã tồn
    tại — init_warehouse phải tự bổ sung các cột mới qua _ensure_column, nếu
    không upsert_financial_ratios sẽ vỡ với BinderException ngay lần chạy kế
    tiếp trên production."""
    c = duckdb.connect(":memory:")
    c.execute(
        """
        CREATE TABLE raw_financial_ratio (
            symbol                   VARCHAR,
            year                     INTEGER,
            quarter                  INTEGER,
            period_type              VARCHAR,
            market_cap               DOUBLE,
            pe                       DOUBLE,
            pb                       DOUBLE,
            ps                       DOUBLE,
            dividend_yield           DOUBLE,
            roe                      DOUBLE,
            roa                      DOUBLE,
            roic                     DOUBLE,
            debt_to_equity           DOUBLE,
            current_ratio            DOUBLE,
            gross_margin             DOUBLE,
            ebit_margin              DOUBLE,
            after_tax_profit_margin  DOUBLE,
            loaded_at                TIMESTAMP,
            PRIMARY KEY (symbol, year, quarter)
        );
        """
    )

    init_warehouse(c)  # không được raise; phải migrate thêm cột thiếu

    df = pd.DataFrame([_ratio_row(npl=0.0115)])
    n = upsert_financial_ratios(c, df)
    npl = c.execute(
        "SELECT npl FROM raw_financial_ratio WHERE symbol='AAA' AND year=2023 AND quarter=5"
    ).fetchone()[0]
    c.close()

    assert n == 1
    assert npl == pytest.approx(0.0115)


def test_upsert_company_info_returns_row_count(con):
    df = pd.DataFrame([{
        "symbol": "AAA", "company_name": "An Phat Bioplastics",
        "exchange": "HOSE", "industry_icb": "Industrials",
        "sector": "Chemicals", "listed_date": "2010-01-15",
    }])
    n = upsert_company_info(con, df)
    assert n == 1


def test_upsert_company_info_overwrites_name(con):
    df1 = pd.DataFrame([{
        "symbol": "AAA", "company_name": "Old Name",
        "exchange": "HOSE", "industry_icb": "Industrials",
        "sector": "Chemicals", "listed_date": "2010-01-15",
    }])
    df2 = pd.DataFrame([{
        "symbol": "AAA", "company_name": "New Name",
        "exchange": "HOSE", "industry_icb": "Industrials",
        "sector": "Chemicals", "listed_date": "2010-01-15",
    }])
    upsert_company_info(con, df1)
    upsert_company_info(con, df2)
    name = con.execute(
        "SELECT company_name FROM raw_company_info WHERE symbol='AAA'"
    ).fetchone()[0]
    assert name == "New Name"


def test_upsert_empty_returns_zero(con):
    assert upsert_financial_ratios(con, pd.DataFrame()) == 0
    assert upsert_company_info(con, pd.DataFrame()) == 0
