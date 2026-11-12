"""Danh sách mã, ICB, bảng giá gọi thẳng VCI — đầu ra ingest_market phải khớp
đáp án chụp từ vnstock 4.0.9 (tests/fixtures/vci)."""
import pytest

from src import ingest, ingest_market
from tests.vci_fixtures import assert_same, block_network, fake_http, load_expected

SYMS = ["FPT", "HPG", "VCB", "SSI", "BVH", "PVS", "MCH"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(ingest, "_throttle", lambda: None)
    block_network(monkeypatch)


def test_refresh_universe_khop_mau(monkeypatch):
    fake_http(monkeypatch, "listing_all_symbols")
    assert_same(ingest_market.refresh_universe(["HOSE", "HNX"]), load_expected("universe"))


def test_industries_icb_khop_mau(monkeypatch):
    fake_http(monkeypatch, "listing_industries_icb")
    assert_same(ingest_market.fetch_industries_icb(), load_expected("industries_icb"))


def test_eod_prices_khop_mau(monkeypatch):
    fake_http(monkeypatch, "price_board")
    out = ingest_market.fetch_eod_prices(SYMS, run_date="2026-11-12")
    assert_same(out, load_expected("eod_prices"))
    assert out.attrs["failed_symbols"] == []


def test_eod_prices_nguon_tra_rong_la_lo_loi(monkeypatch):
    """getList trả [] cho lô có mã → lô lỗi (thử lại + failed_symbols), không
    phải 'không có dữ liệu' (sự cố 05/10/2026: lô MBB, LPB mất mà log ghi ok)."""
    from src.sources import http
    from tests.vci_fixtures import FakeResponse

    monkeypatch.setattr(http, "_send", lambda *a, **k: FakeResponse(200, "[]"))
    monkeypatch.setattr(ingest_market.time, "sleep", lambda s: None)
    out = ingest_market.fetch_eod_prices(["FPT", "HPG"], run_date="2026-11-12")
    assert out.empty
    assert out.attrs["failed_symbols"] == ["FPT", "HPG"]


def test_eod_prices_nguon_loi_ghi_failed(monkeypatch):
    """Nguồn trả vỏ lỗi → lô vào failed_symbols, không trả bảng rỗng âm thầm."""
    from src.sources import http
    from tests.vci_fixtures import FakeResponse

    monkeypatch.setattr(http, "_send", lambda *a, **k: FakeResponse(404, ""))
    monkeypatch.setattr(ingest_market.time, "sleep", lambda s: None)
    out = ingest_market.fetch_eod_prices(["FPT", "HPG"], run_date="2026-11-12")
    assert out.empty
    assert out.attrs["failed_symbols"] == ["FPT", "HPG"]
