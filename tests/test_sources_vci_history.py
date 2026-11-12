"""Lịch sử giá cổ phiếu và chỉ số gọi thẳng VCI — đầu ra ingest_market phải
khớp đáp án chụp từ vnstock 4.0.9 (tests/fixtures/vci)."""
import pandas as pd
import pytest

from src import ingest, ingest_market
from tests.vci_fixtures import assert_same, block_network, fake_http, load_expected

RANGE = ("2026-10-01", "2026-11-11")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(ingest, "_throttle", lambda: None)
    block_network(monkeypatch)


@pytest.mark.parametrize("symbol", ["FPT", "HPG", "VCB", "SSI", "BVH", "PVS", "MCH"])
def test_history_khop_mau(monkeypatch, symbol):
    fake_http(monkeypatch, f"history_{symbol}")
    assert_same(ingest_market.fetch_history_one(symbol, *RANGE),
                load_expected(f"history_{symbol}"))


def test_history_dai_khong_bi_cat_va_khop_phan_chung(monkeypatch):
    """vnstock (vnai, gói cộng đồng) cắt còn ~8 năm và làm tròn giá điều chỉnh
    tới bậc 10 đồng. Gọi thẳng nguồn: đủ 3880 phiên; 1995 phiên cuối khớp đáp
    án trong dung sai làm tròn đó (5 đồng)."""
    fake_http(monkeypatch, "history_FPT_long")
    out = ingest_market.fetch_history_one("FPT", "2012-01-01", "2026-11-11")
    exp = load_expected("history_FPT_long")
    assert len(out) == 3880
    assert out["trade_date"].iloc[0] == "2011-04-29"
    tail = out.tail(len(exp)).reset_index(drop=True)
    assert list(tail.columns) == list(exp.columns)
    assert (tail["trade_date"] == exp["trade_date"]).all()
    assert (tail["volume"] == exp["volume"]).all()
    for col in ("open", "high", "low", "close"):
        assert (tail[col] - exp[col]).abs().max() <= 5, col
    # giá điều chỉnh giữ phần lẻ của nguồn, không bị làm tròn
    assert out["close"].iloc[0] == pytest.approx(3716.39)


@pytest.mark.parametrize("index_code", ["VNINDEX", "VN30", "HNXINDEX"])
def test_index_khop_mau(monkeypatch, index_code):
    fake_http(monkeypatch, f"history_{index_code}")
    assert_same(ingest_market.fetch_index_history(index_code, *RANGE),
                load_expected(f"index_{index_code}"))


def test_index_khong_nhan_1000(monkeypatch):
    fake_http(monkeypatch, "history_VNINDEX")
    out = ingest_market.fetch_index_history("VNINDEX", *RANGE)
    assert out["close"].iloc[0] == pytest.approx(1777.73)


def test_history_nguon_loi_tra_rong(monkeypatch):
    from src.sources import http
    from tests.vci_fixtures import FakeResponse

    monkeypatch.setattr(http, "_send", lambda *a, **k: FakeResponse(400, ""))
    assert ingest_market.fetch_history_one("FPT", *RANGE).empty
