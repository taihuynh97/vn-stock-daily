"""Nạp bù hồ sơ DN cho mã chưa có hồ sơ (18/10/2026).

Hồ sơ DN (ngành ICB, sàn, com_class) chỉ nạp ở job monthly, và monthly bị huỷ
vì quá giờ 01/09 + 01/10 → DTR/KAI/GTX lên sàn 09/2026 không có ngành, test
not_null của mart_sector_snapshot fail ở run weekly 17/10. Giai đoạn
`company_missing` chạy trong trickle, chỉ gọi mã CHƯA CÓ hồ sơ, có hạn mức,
và nhớ lần dò để không gọi lại mỗi ngày những mã nguồn trả rỗng thật
(DPD/PYU/TAC).
"""
from datetime import datetime

import duckdb
import pandas as pd
import pytest

from src import warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    yield c
    c.close()


def _add_profile(con, symbol):
    con.execute("INSERT INTO raw_company_info (symbol) VALUES (?)", [symbol])


def test_chỉ_chọn_mã_chưa_có_hồ_sơ(con):
    import build_warehouse as bw
    _add_profile(con, "HPG")
    assert bw._symbols_missing_profile(con, ["HPG", "DTR", "KAI"],
                                       now=datetime(2026, 10, 18)) == ["DTR", "KAI"]


def test_mã_vừa_dò_trong_cửa_sổ_thì_bỏ_qua_quá_cửa_sổ_thì_dò_lại(con):
    import build_warehouse as bw
    warehouse.record_fetches(con, "company_missing", ["DPD"], fetched_at=datetime(2026, 10, 15))
    warehouse.record_fetches(con, "company_missing", ["PYU"], fetched_at=datetime(2026, 10, 1))
    out = bw._symbols_missing_profile(con, ["DPD", "PYU", "GTX"],
                                      now=datetime(2026, 10, 18), retry_days=7)
    # GTX chưa từng dò → đứng đầu; PYU dò 17 ngày trước → dò lại; DPD 3 ngày → bỏ.
    assert out == ["GTX", "PYU"]


def test_mã_đã_có_hồ_sơ_không_bị_dò_dù_từng_ghi_nhật_ký(con):
    import build_warehouse as bw
    warehouse.record_fetches(con, "company_missing", ["DTR"], fetched_at=datetime(2026, 9, 1))
    _add_profile(con, "DTR")
    assert bw._symbols_missing_profile(con, ["DTR"], now=datetime(2026, 10, 18)) == []


def test_company_missing_là_giai_đoạn_hợp_lệ_của_only():
    import build_warehouse as bw
    assert bw._parse_only("events,statements,company_missing") == {
        "events", "statements", "company_missing"}


def test_main_weekly_company_missing_chỉ_gọi_mã_thiếu_và_ghi_nhật_ký(tmp_path, monkeypatch):
    """Chạy thật main() như trickle: chỉ mã thiếu hồ sơ được gọi, có hạn mức,
    lần dò được ghi lại để lần sau bỏ qua."""
    import build_warehouse as bw
    db = tmp_path / "wh.duckdb"
    monkeypatch.setenv("WAREHOUSE_DB", str(db))
    monkeypatch.setenv("COMPANY_MISSING_MAX_SYMBOLS", "2")
    monkeypatch.delenv("VNSTOCK_API_KEY", raising=False)
    monkeypatch.delenv("INGEST_BUDGET_MINUTES", raising=False)

    c = warehouse.get_conn()
    warehouse.init_warehouse(c)
    _add_profile(c, "HPG")
    c.close()

    universe = pd.DataFrame({"symbol": ["HPG", "DTR", "GTX", "KAI"],
                             "exchange": [None] * 4, "company_name": [None] * 4})
    called = []

    def fake_fetch(symbols, source="VCI", breaker=None):
        rows = []
        for s in symbols:
            if not breaker.before():
                break
            called.append(s)
            breaker.record(True, symbol=s)
            if s == "DTR":   # GTX: nguồn trả rỗng thật
                row = {col: None for col in warehouse.COMPANY_COLS}
                row.update(symbol="DTR", icb_code_lv2="0500", exchange="HOSE")
                rows.append(row)
        return pd.DataFrame(rows)

    monkeypatch.setattr(bw.ingest_market, "refresh_universe", lambda *a, **k: universe)
    monkeypatch.setattr(bw.ingest_market, "fetch_company_info", fake_fetch)
    monkeypatch.setattr("sys.argv", ["build_warehouse.py", "--mode", "weekly",
                                     "--only", "company_missing"])
    bw.main()

    assert called == ["DTR", "GTX"]          # HPG đã có hồ sơ; KAI vượt hạn mức 2
    c = warehouse.get_conn()
    assert c.execute("SELECT icb_code_lv2 FROM raw_company_info WHERE symbol='DTR'"
                     ).fetchone() == ("0500",)
    probed = set(warehouse.fetch_status(c, "company_missing")["symbol"])
    assert probed == {"DTR", "GTX"}
    # Lần chạy kế: GTX vừa dò rỗng → bỏ qua; DTR đã có hồ sơ → bỏ qua; còn KAI.
    assert bw._symbols_missing_profile(c, ["HPG", "DTR", "GTX", "KAI"]) == ["KAI"]
    c.close()
