"""Nạp rải nhịp chậm (05/10/2026).

Nguồn iq.vietcap.com.vn chỉ chịu ~100–150 lệnh mỗi đợt (sự kiện và BCTC), kể cả
sau một đêm nghỉ. Mỗi lần chạy chỉ gọi một ít, mã cũ nhất trước, nhiều lần/ngày.
"""
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest

from src import ingest, ingest_market, warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    yield c
    c.close()


def test_ngắt_mạch_dừng_khi_đủ_hạn_mức_mã():
    br = ingest.SourceBreaker("events", max_symbols=2)
    done = 0
    while br.before():
        br.record(True, symbol=f"S{done}")
        done += 1
    assert done == 2 and br.stopped and br.reason == "du_han_muc"
    assert br.fetched == ["S0", "S1"]


def test_ghi_và_đọc_nhật_ký_nạp(con):
    warehouse.record_fetches(con, "events", ["AAA", "BBB"], fetched_at=datetime(2026, 10, 1))
    warehouse.record_fetches(con, "events", ["AAA"], fetched_at=datetime(2026, 10, 5))
    st = warehouse.fetch_status(con, "events").set_index("symbol")
    assert str(st.loc["AAA", "fetched_at"]) == "2026-10-05 00:00:00"
    assert str(st.loc["BBB", "fetched_at"]) == "2026-10-01 00:00:00"


def test_thứ_tự_sự_kiện_mã_chưa_nạp_trước_rồi_cũ_nhất(con):
    import build_warehouse as bw
    warehouse.record_fetches(con, "events", ["OLD"], fetched_at=datetime(2026, 9, 1))
    warehouse.record_fetches(con, "events", ["NEW"], fetched_at=datetime(2026, 10, 4))
    assert bw._order_by_fetch_age(con, "events", ["NEW", "OLD", "ZZZ", "AAA"]) == ["AAA", "ZZZ", "OLD", "NEW"]


def test_bctc_dừng_khi_đủ_hạn_mức_lần_gọi():
    def factory(symbol, source, period):
        m = MagicMock()
        m.income_statement.return_value = pd.DataFrame()   # dò rỗng: 1 lần gọi/mã
        return m
    with patch("src.ingest_market.Finance", side_effect=factory), \
         patch("src.ingest_market.ingest._throttle"):
        out = ingest_market.fetch_financial_statements(
            [f"S{i}" for i in range(10)], known={}, max_calls=4)
    assert out.attrs["total_calls"] == 4
    assert out.attrs["stopped_early"] and out.attrs["stop_reason"] == "du_han_muc"


def test_đủ_hạn_mức_là_trạng_thái_ok_không_phải_partial():
    import build_warehouse as bw
    br = ingest.SourceBreaker("events", max_symbols=1)
    br.before(); br.record(True, symbol="A"); br.before()
    assert br.reason == "du_han_muc"
    assert bw._phase_status(br, 10) == "ok"


def test_hạn_mức_đọc_từ_biến_môi_trường(monkeypatch):
    import build_warehouse as bw
    monkeypatch.delenv("EVENTS_MAX_SYMBOLS", raising=False)
    assert bw._env_int("EVENTS_MAX_SYMBOLS") is None
    monkeypatch.setenv("EVENTS_MAX_SYMBOLS", "50")
    assert bw._env_int("EVENTS_MAX_SYMBOLS") == 50
