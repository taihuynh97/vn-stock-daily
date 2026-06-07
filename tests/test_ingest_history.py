# tests/test_ingest_history.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from src import ingest_market


@pytest.fixture(autouse=True)
def reset_module_state():
    import src.ingest_market as m
    m._printed_hist_cols = False
    yield
    m._printed_hist_cols = False


def _make_history_df():
    return pd.DataFrame({
        'time':   ['2024-01-02', '2024-01-03', '2024-01-04'],
        'open':   [50000.0,  51000.0,  49000.0],
        'high':   [52000.0,  53000.0,  51000.0],
        'low':    [49000.0,  50000.0,  48000.0],
        'close':  [51000.0,  49500.0,  50000.0],
        'volume': [100000,   120000,   90000],
        'value':  [5.1e9,    5.94e9,   4.5e9],
    })


def test_fetch_history_one_returns_correct_schema():
    mock_quote = MagicMock()
    mock_quote.history.return_value = _make_history_df()

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        with patch('src.ingest_market.ingest._throttle'):
            df = ingest_market.fetch_history_one('VNM', '2024-01-01', '2024-01-31')

    assert list(df.columns) == ['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'value']
    assert len(df) == 3
    assert (df['symbol'] == 'VNM').all()


def test_fetch_history_one_drops_rows_without_close():
    df_raw = _make_history_df()
    df_raw.loc[1, 'close'] = None
    mock_quote = MagicMock()
    mock_quote.history.return_value = df_raw

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        with patch('src.ingest_market.ingest._throttle'):
            df = ingest_market.fetch_history_one('AAA', '2024-01-01', '2024-01-31')

    assert len(df) == 2


def test_fetch_history_one_returns_empty_on_exception():
    mock_quote = MagicMock()
    mock_quote.history.side_effect = Exception("API error")

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        with patch('src.ingest_market.ingest._throttle'):
            df = ingest_market.fetch_history_one('ERR', '2024-01-01', '2024-01-31')

    assert df.empty


def test_fetch_history_one_returns_empty_on_empty_response():
    mock_quote = MagicMock()
    mock_quote.history.return_value = pd.DataFrame()

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        with patch('src.ingest_market.ingest._throttle'):
            df = ingest_market.fetch_history_one('VNM', '2024-01-01', '2024-01-31')

    assert df.empty


def test_fetch_history_one_returns_empty_on_missing_columns():
    mock_quote = MagicMock()
    mock_quote.history.return_value = pd.DataFrame({'price': [100], 'qty': [500]})

    with patch('src.ingest_market.Quote', return_value=mock_quote):
        with patch('src.ingest_market.ingest._throttle'):
            df = ingest_market.fetch_history_one('VNM', '2024-01-01', '2024-01-31')

    assert df.empty
