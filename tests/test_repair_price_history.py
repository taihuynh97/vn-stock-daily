"""Script sửa lịch sử giá (mảng Q, Task 2) — chạy trên DuckDB tạm, không gọi mạng."""
from datetime import datetime

import duckdb
import pandas as pd
import pytest

from scripts import repair_price_history as rp
from src import warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    # Lịch phiên chuẩn: VNINDEX có 27/08, 28/08, 03/09 — nghỉ lễ 31/08–02/09.
    for d in ["2026-08-27", "2026-08-28", "2026-09-03"]:
        c.execute("INSERT INTO raw_index_daily (index_code, trade_date, close, loaded_at) "
                  "VALUES ('VNINDEX', ?, 1700, now())", [d])
    rows = [
        # symbol, date, close, volume, value, ref, fbv
        ("AAA", "2026-08-27", 10000, 100, 1.0, 9900, 5),
        ("AAA", "2026-08-28", 10100, 200, 2.0, 10000, 6),
        ("AAA", "2026-08-31", 10100, 200, 2.0, 10000, 6),   # phiên ma: chép 28/08
        ("AAA", "2026-09-01", 10100, 200, 2.0, 10000, 6),   # phiên ma
        ("AAA", "2026-09-03", 10200, 300, 3.0, 10100, 7),
        ("AAA", "2026-09-04", 10300, 300, 3.0, 10200, 7),   # sau phiên chỉ số cuối
        ("BBB", "2026-08-28", 5000, 50, 0.25, 5000, 0),
        ("BBB", "2026-08-31", 5000, 50, 0.25, 5000, 0),     # phiên ma
    ]
    for s, d, cl, v, val, ref, fbv in rows:
        c.execute(
            "INSERT INTO raw_price_daily (symbol, trade_date, open, high, low, close, volume, "
            "value, ref_price, foreign_buy_volume, loaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TIMESTAMP '2026-09-05 10:00:00')",
            [s, d, cl, cl, cl, cl, v, val, ref, fbv])
    yield c
    c.close()


def test_phantom_sessions_chỉ_là_ngày_không_có_trong_vnindex_và_chép_phiên_trước(con):
    ph = rp.phantom_sessions(con)
    assert list(ph["trade_date"].astype(str)) == ["2026-08-31", "2026-09-01"]
    assert list(ph["n_rows"]) == [2, 1]


def test_ngày_sau_phiên_chỉ_số_cuối_không_phải_phiên_ma(con):
    ph = rp.phantom_sessions(con)
    assert "2026-09-04" not in set(ph["trade_date"].astype(str))


def test_ngày_không_có_trong_vnindex_nhưng_giá_thay_đổi_thì_không_xoá(con):
    # Ngày chỉ số bị thiếu do lỗi nạp, nhưng giá các mã thay đổi thật → giữ.
    con.execute("UPDATE raw_price_daily SET close = close + 50, volume = volume + 1 "
                "WHERE trade_date = DATE '2026-09-01'")
    ph = rp.phantom_sessions(con)
    assert "2026-09-01" not in set(ph["trade_date"].astype(str))


def test_delete_phantom_sessions_xoá_đúng_số_dòng(con):
    assert rp.delete_phantom_sessions(con) == 3
    left = con.execute("SELECT count(*) FROM raw_price_daily").fetchone()[0]
    assert left == 5


def test_merge_history_ghi_đè_ohlcv_giữ_value_và_khối_ngoại(con):
    hist = pd.DataFrame({
        "symbol": ["AAA", "AAA", "AAA"],
        "trade_date": ["2026-08-27", "2026-08-28", "2026-08-26"],
        "open": [2490.0, 2520.0, 2400.0], "high": [2510.0, 2530.0, 2450.0],
        "low": [2480.0, 2500.0, 2390.0], "close": [2500.0, 2525.0, 2410.0],
        "volume": [400, 800, 999], "value": [None, None, None],
    })
    at = datetime(2026, 10, 3, 9, 0, 0)
    assert rp.merge_history(con, hist, at) == 3
    got = con.execute(
        "SELECT trade_date::VARCHAR, close, volume, value, ref_price, foreign_buy_volume, loaded_at "
        "FROM raw_price_daily WHERE symbol='AAA' AND trade_date <= DATE '2026-08-28' "
        "ORDER BY trade_date").fetchall()
    assert got[0] == ("2026-08-26", 2410.0, 999, None, None, None, at)        # dòng mới
    assert got[1] == ("2026-08-27", 2500.0, 400, 1.0, None, 5, at)            # giữ value/khối ngoại
    assert got[2] == ("2026-08-28", 2525.0, 800, 2.0, None, 6, at)
    # Dòng không có trong lịch sử không bị đụng tới.
    untouched = con.execute(
        "SELECT close, ref_price FROM raw_price_daily "
        "WHERE symbol='AAA' AND trade_date = DATE '2026-09-04'").fetchone()
    assert untouched == (10300.0, 10200.0)


def test_symbol_ranges_lấy_ngày_đầu_tiên_mỗi_mã(con):
    r = rp.symbol_ranges(con)
    assert dict(zip(r["symbol"], r["first_date"].astype(str))) == {
        "AAA": "2026-08-27", "BBB": "2026-08-28"}
    r2 = rp.symbol_ranges(con, symbols=["BBB"])
    assert list(r2["symbol"]) == ["BBB"]


def test_symbol_ranges_bỏ_mã_đã_sửa_sau_mốc_resume(con):
    con.execute("UPDATE raw_price_daily SET loaded_at = TIMESTAMP '2026-10-03 09:00:00' "
                "WHERE symbol = 'BBB'")
    r = rp.symbol_ranges(con, repaired_since=datetime(2026, 10, 3, 8, 0, 0))
    assert list(r["symbol"]) == ["AAA"]
