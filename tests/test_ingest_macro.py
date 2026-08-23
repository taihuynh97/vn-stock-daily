"""Test fetch/normalize tỷ giá + tin tức (D)."""
from unittest.mock import patch

import pandas as pd
import pytest

from src import dq
from src.ingest_market import fetch_exchange_rate, fetch_news
from src.warehouse import EXCHANGE_RATE_COLS, NEWS_COLS


def _fake_vcb_df():
    # Nguồn VCB thật trả số dạng chuỗi có dấu phẩy ngăn hàng nghìn cho các
    # loại tiền mệnh giá lớn (vd USD "25,900.00") — fixture phải mô phỏng
    # đúng định dạng này, không dùng float trần, để bắt được bug parse.
    return pd.DataFrame({
        "CurrencyCode": ["USD", "DKK"],
        "CurrencyName": ["US DOLLAR", "DANISH KRONE"],
        "Buy Cash": ["25,900.00", "-"],
        "Buy Transfer": ["25,930.00", "4,012.10"],
        "Sell": ["26,310.00", "4,165.55"],
        "date": ["2026-08-20", "2026-08-20"],
    })


def test_fetch_exchange_rate_tra_dung_cot(monkeypatch):
    def _fake(date):
        df = _fake_vcb_df()
        df.columns = ["currency_code", "currency_name", "buy_cash",
                     "buy_transfer", "sell", "date"]
        return df
    monkeypatch.setattr("src.ingest_market.vcb_exchange_rate", _fake)
    out = fetch_exchange_rate("2026-08-20")
    assert list(out.columns) == EXCHANGE_RATE_COLS


def test_fetch_exchange_rate_dash_thanh_null(monkeypatch):
    def _fake(date):
        df = _fake_vcb_df()
        df.columns = ["currency_code", "currency_name", "buy_cash",
                     "buy_transfer", "sell", "date"]
        return df
    monkeypatch.setattr("src.ingest_market.vcb_exchange_rate", _fake)
    out = fetch_exchange_rate("2026-08-20")
    dkk = out[out["currency_code"] == "DKK"].iloc[0]
    assert pd.isna(dkk["buy_cash"])
    assert dkk["buy_transfer"] == 4012.10


def test_fetch_exchange_rate_dau_phay_hang_nghin_khong_thanh_null(monkeypatch):
    def _fake(date):
        df = _fake_vcb_df()
        df.columns = ["currency_code", "currency_name", "buy_cash",
                     "buy_transfer", "sell", "date"]
        return df
    monkeypatch.setattr("src.ingest_market.vcb_exchange_rate", _fake)
    out = fetch_exchange_rate("2026-08-20")
    usd = out[out["currency_code"] == "USD"].iloc[0]
    assert usd["buy_cash"] == 25900.0
    assert usd["buy_transfer"] == 25930.0
    assert usd["sell"] == 26310.0


def test_fetch_exchange_rate_nguon_loi_tra_df_rong(monkeypatch):
    def _fake(date):
        raise Exception("network error")
    monkeypatch.setattr("src.ingest_market.vcb_exchange_rate", _fake)
    out = fetch_exchange_rate("2026-08-20")
    assert list(out.columns) == EXCHANGE_RATE_COLS
    assert len(out) == 0


def _fake_news_df(ids):
    return pd.DataFrame({
        "id": ids,
        "news_title": [f"Tiêu đề {i}" for i in ids],
        "news_short_content": [f"Nội dung {i}" for i in ids],
        "news_source_link": [f"https://x.com/{i}" for i in ids],
        "public_date": ["2026-08-01T10:00:00"] * len(ids),
    })


def test_fetch_news_tra_dung_cot(monkeypatch):
    class FakeCompany:
        def __init__(self, symbol, source):
            self.symbol = symbol
        def news(self):
            return _fake_news_df(["n1", "n2"])
    monkeypatch.setattr("src.ingest_market.Company", FakeCompany)
    out = fetch_news(["HPG"])
    assert list(out.columns) == NEWS_COLS
    assert (out["symbol"] == "HPG").all()


def test_fetch_news_mot_ma_loi_giua_nhieu_ma_tot_bi_bo_qua(monkeypatch):
    class FakeCompany:
        def __init__(self, symbol, source):
            self.symbol = symbol
        def news(self):
            if self.symbol == "BAD":
                raise Exception("API lỗi")
            return _fake_news_df([f"{self.symbol}-n1"])
    monkeypatch.setattr("src.ingest_market.Company", FakeCompany)
    out = fetch_news(["HPG", "BAD", "VNR"])
    assert set(out["symbol"]) == {"HPG", "VNR"}


def test_fetch_news_id_none_bi_loai_qua_dq_schema_error(monkeypatch):
    """id thiếu cột (schema đổi) phải bị dq.SchemaError bắt theo TỪNG mã,
    không sập cả hàm — giống fetch_corporate_events (B1)."""
    class FakeCompany:
        def __init__(self, symbol, source):
            self.symbol = symbol
        def news(self):
            df = _fake_news_df(["n1"])
            return df.drop(columns=["id"])  # thiếu cột bắt buộc
    monkeypatch.setattr("src.ingest_market.Company", FakeCompany)
    out = fetch_news(["HPG"])
    assert len(out) == 0
