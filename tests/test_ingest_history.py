# tests/test_ingest_history.py
import pandas as pd
import pytest
from unittest.mock import patch
from src import ingest_market


@pytest.fixture(autouse=True)
def reset_module_state():
    import src.ingest_market as m
    m._printed_hist_cols = False
    yield
    m._printed_hist_cols = False


def _make_history_df():
    """vci.ohlc_history trả OHLC theo ĐỒNG (đơn vị của nguồn)."""
    return pd.DataFrame({
        'time':   pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04']),
        'open':   [50000.0, 51000.0, 49000.0],
        'high':   [52000.0, 53000.0, 51000.0],
        'low':    [49000.0, 50000.0, 48000.0],
        'close':  [51000.0, 49500.0, 50000.0],
        'volume': [100000,   120000,   90000],
        'value':  [5.1e9,    5.94e9,   4.5e9],
    })


def _run(symbol, **patch_kw):
    with patch('src.ingest_market.vci.ohlc_history', **patch_kw), \
         patch('src.ingest_market.ingest._throttle'):
        return ingest_market.fetch_history_one(symbol, '2024-01-01', '2024-01-31')


def test_fetch_history_one_returns_correct_schema():
    df = _run('VNM', return_value=_make_history_df())
    assert list(df.columns) == ['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'value']
    assert len(df) == 3
    assert (df['symbol'] == 'VNM').all()


def test_fetch_history_one_keeps_vnd_unit():
    """Giá giữ nguyên ĐỒNG, không nhân 1000 — đơn vị khớp bảng giá daily.
    (Thời vnstock, Quote.history trả nghìn đồng nên từng phải nhân 1000.)"""
    df = _run('VNM', return_value=_make_history_df())
    assert df['open'].tolist() == [50000.0, 51000.0, 49000.0]
    assert df['high'].tolist() == [52000.0, 53000.0, 51000.0]
    assert df['low'].tolist() == [49000.0, 50000.0, 48000.0]
    assert df['close'].tolist() == [51000.0, 49500.0, 50000.0]


def test_fetch_history_one_drops_rows_without_close():
    df_raw = _make_history_df()
    df_raw.loc[1, 'close'] = None
    assert len(_run('AAA', return_value=df_raw)) == 2


def test_fetch_history_one_returns_empty_on_exception():
    assert _run('ERR', side_effect=Exception("API error")).empty


def test_fetch_history_one_returns_empty_on_empty_response():
    assert _run('VNM', return_value=pd.DataFrame()).empty


def test_fetch_history_one_returns_empty_on_missing_columns():
    assert _run('VNM', return_value=pd.DataFrame({'price': [100], 'qty': [500]})).empty
