"""Tỷ giá Vietcombank gọi thẳng (src/sources/vcb.py) — đầu ra
fetch_exchange_rate phải khớp đáp án chụp từ vnstock 4.0.9."""
import pytest

from src import ingest_market
from tests.vci_fixtures import assert_same, block_network, fake_http, load_expected


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    block_network(monkeypatch)


def test_fx_khop_mau(monkeypatch):
    fake_http(monkeypatch, "fx_vcb_2026-11-11")
    assert_same(ingest_market.fetch_exchange_rate("2026-11-11"), load_expected("fx_2026-11-11"))


def test_fx_gach_ngang_la_null(monkeypatch):
    """'-' từ nguồn (loại tiền không áp dụng giao dịch đó) → NULL, không phải 0."""
    from src.sources import vcb

    fake_http(monkeypatch, "fx_vcb_2026-11-11")
    raw = vcb.exchange_rate("2026-11-11")
    dashed = raw.index[raw["buy_cash"].astype(str).str.strip() == "-"]
    assert len(dashed) > 0, "fixture phải có ít nhất một ô '-'"
    out = ingest_market.fetch_exchange_rate("2026-11-11")
    codes = raw.loc[dashed, "currency_code"].tolist()
    assert out.loc[out["currency_code"].isin(codes), "buy_cash"].isna().all()


def test_fx_nguon_loi_tra_bang_rong_dung_cot(monkeypatch):
    from src import warehouse
    from src.sources import http
    from tests.vci_fixtures import FakeResponse

    monkeypatch.setattr(http, "_send", lambda *a, **k: FakeResponse(500, ""))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    out = ingest_market.fetch_exchange_rate("2026-11-11")
    assert out.empty
    assert list(out.columns) == warehouse.EXCHANGE_RATE_COLS
