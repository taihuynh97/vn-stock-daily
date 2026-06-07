import pandas as pd
import pytest
from unittest.mock import patch, MagicMock


def _make_wh_df(n_rows=60):
    return pd.DataFrame({
        "trade_date": [f"2024-01-{i+1:02d}" for i in range(n_rows)],
        "open": [10.0] * n_rows,
        "high": [11.0] * n_rows,
        "low":  [9.5]  * n_rows,
        "close": [10.5] * n_rows,
        "volume": [100000] * n_rows,
        "value": [1e9] * n_rows,
    })


def test_fetch_history_uses_warehouse_when_enough_data():
    wh_df = _make_wh_df(n_rows=60)

    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest._throttle"):
        mock_con = MagicMock()
        mock_wh.get_conn.return_value = mock_con
        mock_wh.read_price_history.return_value = wh_df

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert not result.empty
    assert "close" in result.columns
    mock_wh.read_price_history.assert_called_once()


def test_fetch_history_falls_back_to_api_when_warehouse_empty():
    api_df = _make_wh_df(n_rows=30)
    api_df.columns = ["time", "open", "high", "low", "close", "volume", "value"]

    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest.Quote") as MockQuote, \
         patch("src.ingest._throttle"):
        mock_con = MagicMock()
        mock_wh.get_conn.return_value = mock_con
        mock_wh.read_price_history.return_value = pd.DataFrame()
        MockQuote.return_value.history.return_value = api_df

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert not result.empty
    MockQuote.return_value.history.assert_called_once()


def test_fetch_history_falls_back_to_api_when_warehouse_unavailable():
    api_df = _make_wh_df(n_rows=30)
    api_df.columns = ["time", "open", "high", "low", "close", "volume", "value"]

    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest.Quote") as MockQuote, \
         patch("src.ingest._throttle"):
        mock_wh.get_conn.side_effect = Exception("DB not found")
        MockQuote.return_value.history.return_value = api_df

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert not result.empty
    MockQuote.return_value.history.assert_called_once()


def test_fetch_history_returns_empty_when_both_fail():
    with patch("src.ingest.warehouse") as mock_wh, \
         patch("src.ingest.Quote") as MockQuote, \
         patch("src.ingest._throttle"):
        mock_wh.get_conn.side_effect = Exception("DB fail")
        MockQuote.return_value.history.return_value = None

        from src.ingest import fetch_history
        result = fetch_history("AAA", days=30)

    assert result.empty
