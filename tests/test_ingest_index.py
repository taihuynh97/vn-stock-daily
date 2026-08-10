import duckdb
import pandas as pd
import pytest
from unittest.mock import patch

from src import warehouse as wh
from src.ingest_market import fetch_index_history


def _mock_index_history():
    """Quote.history('VNINDEX') — giá trị KHÔNG nhân 1000."""
    return pd.DataFrame([
        {"time": "2026-08-06", "open": 1784.65, "high": 1784.65,
         "low": 1762.34, "close": 1764.78, "volume": 579915937},
        {"time": "2026-08-07", "open": 1761.23, "high": 1774.61,
         "low": 1756.07, "close": 1768.06, "volume": 660590646},
    ])


def test_fetch_index_history_does_not_scale_by_1000():
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = _mock_index_history()
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert df.iloc[-1]["close"] == pytest.approx(1768.06)   # KHÔNG phải 1_768_060
    assert df.iloc[-1]["open"] == pytest.approx(1761.23)


def test_fetch_index_history_schema():
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = _mock_index_history()
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert list(df.columns) == [
        "index_code", "trade_date", "open", "high", "low", "close", "volume"
    ]
    assert set(df["index_code"]) == {"VNINDEX"}
    assert df.iloc[0]["trade_date"] == "2026-08-06"


def test_fetch_index_history_raises_on_missing_close():
    bad = pd.DataFrame([{"time": "2026-08-07", "open": 1.0}])
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = bad
        with pytest.raises(Exception) as exc:
            fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert "close" in str(exc.value)


def test_fetch_index_history_empty_on_api_error():
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.side_effect = Exception("down")
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert df.empty


def test_upsert_index_prices_idempotent(tmp_path):
    con = duckdb.connect(str(tmp_path / "idx.duckdb"))
    wh.init_warehouse(con)
    with patch("src.ingest_market.Quote") as MockQ, \
         patch("src.ingest_market.ingest._throttle"):
        MockQ.return_value.history.return_value = _mock_index_history()
        df = fetch_index_history("VNINDEX", "2026-08-01", "2026-08-07")
    assert wh.upsert_index_prices(con, df) == 2
    assert wh.upsert_index_prices(con, df) == 2
    total = con.execute("SELECT count(*) FROM raw_index_daily").fetchone()[0]
    close = con.execute(
        "SELECT close FROM raw_index_daily "
        "WHERE index_code='VNINDEX' AND trade_date=DATE '2026-08-07'"
    ).fetchone()[0]
    con.close()
    assert total == 2
    assert close == pytest.approx(1768.06)
