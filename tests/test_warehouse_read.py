import pandas as pd
import duckdb
import pytest
from datetime import date, timedelta
from src.warehouse import init_warehouse, upsert_prices, read_price_history


@pytest.fixture
def con_with_data():
    con = duckdb.connect(":memory:")
    init_warehouse(con)
    today = date.today()
    rows = []
    for i in range(60):
        d = (today - timedelta(days=60 - i)).isoformat()
        rows.append({
            "symbol": "AAA", "trade_date": d,
            "open": 10.0, "high": 11.0, "low": 9.5,
            "close": 10.5, "volume": 100000, "value": 1050000000.0,
        })
    df = pd.DataFrame(rows)
    upsert_prices(con, df)
    yield con
    con.close()


def test_read_price_history_returns_dataframe(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    assert isinstance(result, pd.DataFrame)
    assert not result.empty


def test_read_price_history_has_required_columns(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    assert "close" in result.columns
    assert "volume" in result.columns


def test_read_price_history_respects_days_limit(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    assert len(result) <= 30


def test_read_price_history_returns_empty_for_unknown_symbol(con_with_data):
    result = read_price_history(con_with_data, "UNKNOWN", days=30)
    assert result.empty


def test_read_price_history_sorted_ascending(con_with_data):
    result = read_price_history(con_with_data, "AAA", days=30)
    dates = result["trade_date"].tolist()
    assert dates == sorted(dates)
