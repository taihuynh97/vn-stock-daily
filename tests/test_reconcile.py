from unittest.mock import patch

import duckdb
import pandas as pd
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
            "dim_industry_rows", "raw_index_daily_codes",
            "symbols_missing_ratio"} <= names


def test_check_layer_counts_symbols_missing_ratio_fails_when_over_tolerance(tmp_path):
    con = _seed(tmp_path)
    # AAA và BBB đều active nhưng chưa mã nào có tỷ số -> 100% thiếu > 5%.
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["symbols_missing_ratio"]["value"] == 2
    assert by_name["symbols_missing_ratio"]["ok"] is False


def test_check_layer_counts_symbols_missing_ratio_ok_when_covered(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, pe=10.0, roe=0.15)
    _seed_ratio(con, "BBB", 2025, 1, pe=10.0, roe=0.15)
    rows = rw.check_layer_counts(con)
    con.close()
    by_name = {r["check"]: r for r in rows}
    assert by_name["symbols_missing_ratio"]["value"] == 0
    assert by_name["symbols_missing_ratio"]["ok"] is True


def _seed_ratio(con, symbol, year, quarter, pe, roe):
    con.execute(
        "INSERT INTO raw_financial_ratio (symbol, year, quarter, period_type, "
        "pe, roe, loaded_at) VALUES (?, ?, ?, 'quarter', ?, ?, now())",
        [symbol, year, quarter, pe, roe],
    )


def test_check_against_source_same_period_flags_real_drift(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, pe=10.0, roe=0.15)
    api_df = pd.DataFrame([{"year": 2025, "quarter": 1, "pe": 50.0, "roe": 0.15}])
    with patch("src.ingest_market.fetch_financials", return_value=api_df):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is False   # cùng kỳ, pe lệch 4x -> phải fail


def test_check_against_source_same_period_within_tolerance_passes(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, pe=10.0, roe=0.15)
    api_df = pd.DataFrame([{"year": 2025, "quarter": 1, "pe": 10.0, "roe": 0.15}])
    with patch("src.ingest_market.fetch_financials", return_value=api_df):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True
    assert "2025Q1" in rows[0]["detail"]


def test_check_against_source_newer_api_period_is_informational_not_fail(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, pe=10.0, roe=0.15)
    # API đã công bố kỳ mới hơn (2025Q2) mà warehouse chưa kịp reload — API
    # KHÔNG có 2025Q1 nên không thể so kỳ. Giá trị 2025Q2 lệch rất lớn so với
    # warehouse nhưng đây không phải lỗi dữ liệu, chỉ là chưa reload kỳ mới.
    api_df = pd.DataFrame([{"year": 2025, "quarter": 2, "pe": 999.0, "roe": 0.99}])
    with patch("src.ingest_market.fetch_financials", return_value=api_df):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True
    assert "2025Q1" in rows[0]["detail"] and "2025Q2" in rows[0]["detail"]


def test_check_against_source_api_empty_is_not_fail(tmp_path):
    con = _seed(tmp_path)
    _seed_ratio(con, "AAA", 2025, 1, pe=10.0, roe=0.15)
    with patch("src.ingest_market.fetch_financials", return_value=pd.DataFrame()):
        rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True


def test_check_against_source_symbol_with_no_ratio_row_is_informational_not_fail(tmp_path):
    """Mã được lấy mẫu chưa có dòng nào trong raw_financial_ratio (~13/1598
    mã thực tế) không được tính là fail — độ phủ đã được canh có hệ thống ở
    check_layer_counts (symbols_missing_ratio), không phải qua mẫu 5 mã ngẫu
    nhiên của check_against_source (tránh CI đỏ ngẫu nhiên)."""
    con = _seed(tmp_path)
    # AAA active nhưng KHÔNG seed dòng nào trong raw_financial_ratio.
    rows = rw.check_against_source(con, ["AAA"])
    con.close()
    assert rows[0]["ok"] is True
    assert "AAA" in rows[0]["detail"]
