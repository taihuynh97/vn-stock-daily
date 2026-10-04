"""Giảm tải cho nguồn iq.vietcap.com.vn (04/10/2026).

Nguồn bóp theo lưu lượng: lần chạy tối 04/10 dừng sau 97 mã BCTC (0 dòng) và
104 mã sự kiện. Lô BCTC đầu toàn là ~300 mã chưa từng có BCTC — phần lớn nguồn
KHÔNG có dữ liệu — bị dò lại đầu tiên mỗi tuần.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest

from src import ingest_market, warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    yield c
    c.close()


# --- 1. Nhớ kết quả dò BCTC -------------------------------------------------------

def test_ghi_và_đọc_kết_quả_dò(con):
    warehouse.record_statement_probes(con, "quarter", [("AAA", "empty"), ("BBB", "ok")],
                                      probed_at=datetime(2026, 10, 1, 8, 0))
    warehouse.record_statement_probes(con, "quarter", [("AAA", "error")],
                                      probed_at=datetime(2026, 10, 4, 8, 0))
    st = warehouse.statement_probe_status(con, "quarter").set_index("symbol")
    # Lỗi KHÔNG ghi đè kết quả "empty"/"ok" đã biết — lỗi không cho thông tin gì.
    assert st.loc["AAA", "result"] == "empty"
    assert str(st.loc["AAA", "probed_at"]) == "2026-10-01 08:00:00"
    assert st.loc["BBB", "result"] == "ok"


def test_fetch_chọn_lọc_trả_kết_quả_dò_từng_mã():
    def factory(symbol, source, period):
        m = MagicMock()
        if symbol == "ERR":
            m.income_statement.side_effect = ConnectionError("Read timed out")
        elif symbol == "NODATA":
            m.income_statement.return_value = pd.DataFrame()
        else:
            m.income_statement.return_value = pd.DataFrame({
                "item": ["DT"], "item_en": ["Sales"], "item_id": ["net_sales"], "2026-Q2": [1.0]})
            m.balance_sheet.return_value = m.income_statement.return_value
            m.cash_flow.return_value = m.income_statement.return_value
        return m

    with patch("src.ingest_market.Finance", side_effect=factory), \
         patch("src.ingest_market.ingest._throttle"):
        out = ingest_market.fetch_financial_statements(
            ["OK", "NODATA", "ERR"], known={}, pause_after=99)
    assert dict(out.attrs["probes"]) == {"OK": "ok", "NODATA": "empty", "ERR": "error"}


def test_thứ_tự_bỏ_mã_dò_rỗng_gần_đây_và_đưa_mã_chưa_dò_lên_đầu(con):
    import build_warehouse as bw
    now = datetime(2026, 10, 5, 6, 0)
    warehouse.record_statement_probes(con, "quarter", [("EMPTY_RECENT", "empty")],
                                      probed_at=now - timedelta(days=3))
    warehouse.record_statement_probes(con, "quarter", [("EMPTY_OLD", "empty")],
                                      probed_at=now - timedelta(days=45))
    order, known = bw._order_statement_symbols(
        con, ["EMPTY_RECENT", "EMPTY_OLD", "NEVER"], "quarter", now=now)
    assert order == ["NEVER", "EMPTY_OLD"]          # rỗng 3 ngày trước → bỏ
    assert known == {}


def test_vòng_lô_ghi_kết_quả_dò_sau_mỗi_lô(con):
    import build_warehouse as bw

    def fake_fetch(chunk, source, period="quarter", **kw):
        df = pd.DataFrame(columns=warehouse.STATEMENT_COLS)
        df.attrs.update(n_errors=0, total_calls=len(chunk), n_full=0,
                        n_probe_only=len(chunk), n_symbols_done=len(chunk),
                        stopped_early=False, stop_reason=None,
                        probes=[(s, "empty") for s in chunk])
        return df

    with patch("src.ingest_market.fetch_financial_statements", side_effect=fake_fetch):
        bw._ingest_statements_chunked(con, ["A1", "A2"], "VCI", "quarter", selective=True)
    st = warehouse.statement_probe_status(con, "quarter")
    assert set(st["symbol"]) == {"A1", "A2"} and set(st["result"]) == {"empty"}


# --- 2. Sự kiện hằng tuần chỉ cho mã đủ lớn ------------------------------------------

def test_mã_sự_kiện_hằng_tuần_theo_vốn_hoá_cộng_danh_mục(con):
    import build_warehouse as bw
    con.execute("CREATE TABLE dim_stock (symbol VARCHAR, market_cap DOUBLE)")
    con.execute("INSERT INTO dim_stock VALUES ('BIG', 2e12), ('MID', 6e11), ('SMALL', 1e11), ('PORT', 5e10)")
    syms = ["BIG", "MID", "SMALL", "PORT", "NEW"]
    out = bw._weekly_event_symbols(con, syms, min_market_cap_vnd=5e11, portfolio=["PORT"])
    assert out == ["BIG", "MID", "PORT"]


def test_chưa_có_dim_stock_thì_dùng_mọi_mã(con):
    import build_warehouse as bw
    syms = ["A", "B"]
    assert bw._weekly_event_symbols(con, syms, min_market_cap_vnd=5e11, portfolio=[]) == syms
