"""Gọi nguồn THẬT (Vietcap, VCB) một lần mỗi endpoint — phát hiện nguồn đổi
schema/chặn truy cập. Bỏ qua mặc định; chạy tay:

    pytest -m network -q tests/test_sources_live.py
"""
from datetime import date, timedelta

import pytest

from src import ingest_market

pytestmark = pytest.mark.network

SYM = "FPT"


def _recent_weekday() -> str:
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def test_universe():
    out = ingest_market.refresh_universe(["HOSE", "HNX"])
    assert len(out) > 1000 and {"symbol", "company_name"} <= set(out.columns)


def test_industries_icb():
    assert len(ingest_market.fetch_industries_icb()) > 100


def test_bang_gia():
    out = ingest_market.fetch_eod_prices([SYM, "VCB"])
    assert set(out["symbol"]) == {SYM, "VCB"}
    assert out.attrs["failed_symbols"] == []


def test_lich_su_gia_va_chi_so():
    end = _recent_weekday()
    start = (date.fromisoformat(end) - timedelta(days=14)).isoformat()
    px = ingest_market.fetch_history_one(SYM, start, end)
    assert len(px) >= 5 and px["close"].min() > 1000          # đồng, không phải nghìn đồng
    ix = ingest_market.fetch_index_history("VNINDEX", start, end)
    assert len(ix) >= 5 and 500 < ix["close"].iloc[-1] < 5000  # điểm chỉ số


def test_ty_gia():
    out = ingest_market.fetch_exchange_rate(_recent_weekday())
    assert "USD" in set(out["currency_code"])


def test_cong_ty():
    assert len(ingest_market.fetch_corporate_events([SYM])) > 0
    assert len(ingest_market.fetch_news([SYM])) > 0
    assert len(ingest_market.fetch_company_info([SYM])) == 1
    assert len(ingest_market.fetch_shareholders([SYM])) > 0
    assert len(ingest_market.fetch_officers([SYM])) > 0
    assert len(ingest_market.fetch_financials([SYM])) > 0


@pytest.mark.parametrize("stype", ["income_statement", "balance_sheet", "cash_flow"])
def test_bctc(stype):
    row, status = ingest_market._fetch_statement_one(SYM, stype, "VCI", "quarter")
    assert status == "ok" and row["period_label"].nunique() == 8
