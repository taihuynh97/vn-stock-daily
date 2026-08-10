import duckdb
import pytest

from src import warehouse as wh
from scripts import reconcile_warehouse as rw


def _seed(tmp_path):
    con = duckdb.connect(str(tmp_path / "rec.duckdb"))
    wh.init_warehouse(con)
    con.execute(
        "INSERT INTO dim_symbols (symbol, exchange, company_name, is_active, "
        "first_seen, last_seen) VALUES "
        "('AAA','HOSE','A',TRUE,DATE '2026-01-01',DATE '2026-08-07'),"
        "('BBB','HNX','B',TRUE,DATE '2026-01-01',DATE '2026-08-07')"
    )
    con.execute(
        "INSERT INTO raw_price_daily (symbol, trade_date, open, high, low, "
        "close, volume, value, loaded_at) VALUES "
        "('AAA',DATE '2026-08-07',1,1,1,20000,1000,20.0,now())"
    )
    return con


def test_check_layer_counts_flags_missing_prices(tmp_path):
    con = _seed(tmp_path)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["dim_symbols"]["value"] == 2
    assert by_name["raw_price_daily_symbols"]["value"] == 1
    assert by_name["raw_price_daily_symbols"]["ok"] is False   # 1/2 = 50% < 95%


def test_check_layer_counts_passes_when_complete(tmp_path):
    con = _seed(tmp_path)
    con.execute(
        "INSERT INTO raw_price_daily (symbol, trade_date, open, high, low, "
        "close, volume, value, loaded_at) VALUES "
        "('BBB',DATE '2026-08-07',1,1,1,15000,900,15.0,now())"
    )
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["raw_price_daily_symbols"]["ok"] is True


def test_check_layer_counts_returns_expected_checks(tmp_path):
    con = _seed(tmp_path)
    names = {r["check"] for r in rw.check_layer_counts(con)}
    con.close()
    assert {"dim_symbols", "raw_price_daily_symbols",
            "raw_company_info_symbols", "raw_financial_ratio_symbols",
            "dim_industry_rows", "raw_index_daily_codes"} <= names
