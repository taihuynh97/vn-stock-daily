import pandas as pd
import duckdb
import pytest
from src.warehouse import (
    init_warehouse,
    upsert_financial_ratios,
    upsert_company_info,
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


def test_upsert_financial_ratios_returns_row_count(con):
    df = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 10.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    n = upsert_financial_ratios(con, df)
    assert n == 1


def test_upsert_financial_ratios_idempotent(con):
    df = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 10.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    upsert_financial_ratios(con, df)
    upsert_financial_ratios(con, df)
    count = con.execute("SELECT COUNT(*) FROM raw_financial_ratio").fetchone()[0]
    assert count == 1


def test_upsert_financial_ratios_updates_pe(con):
    df1 = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 10.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    df2 = pd.DataFrame([{
        "symbol": "AAA", "period": "2023", "period_type": "year",
        "pe": 12.0, "pb": 1.5, "roe": 0.15, "roa": 0.08, "eps": 2000.0,
    }])
    upsert_financial_ratios(con, df1)
    upsert_financial_ratios(con, df2)
    pe = con.execute(
        "SELECT pe FROM raw_financial_ratio WHERE symbol='AAA' AND period='2023'"
    ).fetchone()[0]
    assert pe == 12.0


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
