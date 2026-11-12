"""Sự kiện, tin, hồ sơ công ty, cổ đông, ban lãnh đạo, ratio_summary gọi thẳng
VCI — đầu ra ingest_market phải khớp đáp án chụp từ vnstock 4.0.9."""
from datetime import date

import pytest

from src import ingest, ingest_market
from src.sources import vci_company
from tests.vci_fixtures import assert_same, block_network, fake_http, load_expected

SYMS = ["FPT", "HPG", "VCB", "SSI", "BVH", "PVS", "MCH"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(ingest, "_throttle", lambda: None)
    monkeypatch.setattr(vci_company, "_today", lambda: date(2026, 11, 12))
    block_network(monkeypatch)


def _raw_content(label):
    import json

    from tests.vci_fixtures import load_http
    return json.loads(load_http(label)[0]["body"])["data"]["content"]


@pytest.mark.parametrize("symbol", SYMS)
def test_events_khop_mau(monkeypatch, symbol):
    """Khớp tuyệt đối, trừ một lỗi cũ đã sửa: public_date lẫn kiểu có/không có
    mili giây (VCB) khiến _date_col biến các dòng khác kiểu thành NULL. Ở các
    dòng đáp án NULL đó, đầu ra mới phải bằng đúng ngày của nguồn."""
    fake_http(monkeypatch, f"company_events_{symbol}")
    out = ingest_market.fetch_corporate_events([symbol])
    exp = load_expected(f"events_{symbol}")
    lost = exp["public_date"].isna() & out["public_date"].notna()
    raw_date = {r["id"]: (r.get("publicDate") or "")[:10] for r in _raw_content(f"company_events_{symbol}")}
    assert (out.loc[lost, "public_date"] == out.loc[lost, "id"].map(raw_date)).all()
    fixed = exp.copy()
    fixed.loc[lost, "public_date"] = out.loc[lost, "public_date"]
    assert_same(out, fixed)


def test_events_vcb_khong_mat_ngay_cong_bo(monkeypatch):
    fake_http(monkeypatch, "company_events_VCB")
    out = ingest_market.fetch_corporate_events(["VCB"])
    assert out["public_date"].notna().all()
    assert "2022-01-28" in out["public_date"].tolist()  # nguồn: 2022-01-28T17:47:09.067


def test_events_nguon_loi_ghi_breaker(monkeypatch):
    from src.sources import http
    from tests.vci_fixtures import FakeResponse

    monkeypatch.setattr(http, "_send", lambda *a, **k: FakeResponse(200, '{"status":500,"code":1,"msg":"x"}'))
    br = ingest.SourceBreaker("events")
    out = ingest_market.fetch_corporate_events(["FPT"], breaker=br)
    assert out.empty
    assert br.n_errors == 1
