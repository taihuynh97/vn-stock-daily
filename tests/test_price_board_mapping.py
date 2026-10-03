"""Hợp đồng ánh xạ bảng giá VCI → raw_price_daily (mảng Q, Task 1).

Lỗi gốc (07/06 → 02/10/2026): `_find()` trả cột ĐẦU TIÊN chứa BẤT KỲ từ
khoá nào, nên "close" khớp `listing.ref_price` (cột listing.* đứng trước
match.*). Mọi giá đóng cửa hằng ngày thực chất là giá tham chiếu = giá đóng
cửa phiên TRƯỚC. Fixture dưới giữ ĐÚNG thứ tự cột thật của VCI để khoá lại
đúng tình huống đã sinh lỗi.
"""
import duckdb
import pandas as pd
import pytest

from src import dq, ingest_market, warehouse

# Thứ tự cột phẳng thật của Trading(source='VCI').price_board (rút gọn các
# cột không liên quan nhưng GIỮ thứ tự tương đối listing.* trước match.*).
VCI_COLS = [
    "listing.symbol", "listing.ceiling", "listing.floor", "listing.ref_price",
    "listing.trading_status", "listing.trading_date",
    "match.accumulated_value", "match.accumulated_volume",
    "match.match_price_ato", "match.match_price_atc", "match.avg_match_price",
    "match.foreign_buy_volume", "match.foreign_sell_volume",
    "match.foreign_buy_value", "match.foreign_sell_value",
    "match.highest", "match.lowest", "match.match_price", "match.open_price",
    "match.first_time_match_price", "match.reference_price",
]


def _board(rows):
    return pd.DataFrame(rows, columns=VCI_COLS)


def _row(sym, ref, close, open_, high, low, vol, val, tdate="2026-10-02",
         fbv=10, fsv=20, fbval=1e6, fsval=2e6):
    return [sym, ref * 1.07, ref * 0.93, ref, "TRADING_ACTIVATED", tdate,
            val, vol, None, None, close, fbv, fsv, fbval, fsval,
            high, low, close, open_, "2026-10-02T02:15:00Z", ref]


def test_pick_ưu_tiên_theo_thứ_tự_ứng_viên_không_theo_thứ_tự_cột():
    # "price" là chuỗi con của listing.ref_price — _pick không được khớp chuỗi con.
    assert ingest_market._pick(VCI_COLS, "match.match_price") == "match.match_price"
    assert ingest_market._pick(VCI_COLS, "match_price") == "match.match_price"
    assert ingest_market._pick(VCI_COLS, "khong_co", "highest") == "match.highest"
    assert ingest_market._pick(VCI_COLS, "khong_co") is None


def test_close_là_giá_khớp_không_phải_giá_tham_chiếu():
    df = _board([_row("TRC", ref=24250, close=24150, open_=24250, high=25200,
                      low=23600, vol=273200, val=6600.88)])
    out = ingest_market._normalize_board(df, "2026-10-02")
    r = out.iloc[0]
    assert r["close"] == 24150
    assert r["ref_price"] == 24250
    assert (r["open"], r["high"], r["low"]) == (24250, 25200, 23600)
    assert r["volume"] == 273200
    assert r["value"] == pytest.approx(6600.88)
    assert r["foreign_sell_value"] == 2e6
    assert str(r["trade_date"]) == "2026-10-02"


def test_mã_không_khớp_lệnh_lấy_giá_tham_chiếu_và_khối_lượng_0():
    df = _board([_row("ACS", ref=4500, close=0, open_=None, high=0, low=0,
                      vol=0, val=0.0)])
    r = ingest_market._normalize_board(df, "2026-10-02").iloc[0]
    assert r["close"] == 4500
    assert r["volume"] == 0
    assert pd.isna(r["open"]) and pd.isna(r["high"]) and pd.isna(r["low"])


def test_mã_tạm_ngừng_có_ngày_giao_dịch_cũ_bị_bỏ():
    df = _board([
        _row("FPT", 62700, 62100, 62700, 63200, 62100, 3199600, 200301.44),
        _row("AMD", 1100, 0, None, 0, 0, 0, 0.0, tdate="2025-12-30"),
        _row("AGE", 9500, 0, None, 0, 0, 0, 0.0, tdate=None),
    ])
    out = ingest_market._normalize_board(df, "2026-10-02")
    assert list(out["symbol"]) == ["FPT"]


def test_ngày_giao_dịch_của_bảng_giá_là_ngày_phổ_biến_nhất():
    df = _board([
        _row("FPT", 62700, 62100, 62700, 63200, 62100, 3199600, 200301.44, tdate="2026-08-28"),
        _row("HPG", 20000, 20050, 20000, 20100, 19900, 100, 2.0, tdate="2026-08-28"),
        _row("AMD", 1100, 0, None, 0, 0, 0, 0.0, tdate="2025-12-30"),
    ])
    assert ingest_market.board_trading_date(df) == "2026-08-28"
    # Ngày lễ: bảng giá vẫn mang phiên 28/08 → dòng chuẩn hoá ghi ngày 28/08,
    # không phải ngày chạy job (đó là cách phiên ma 31/08–02/09 đã sinh ra).
    out = ingest_market._normalize_board(df, "2026-09-01")
    assert out.attrs["market_trading_date"] == "2026-08-28"
    assert set(out["trade_date"].astype(str)) == {"2026-08-28"}


def test_board_trading_date_không_có_cột_thì_None():
    df = pd.DataFrame({"listing.symbol": ["FPT"], "match.match_price": [1.0]})
    assert ingest_market.board_trading_date(df) is None


def test_hợp_đồng_ohlc_ném_lỗi_khi_close_ngoài_biên_hàng_loạt():
    bad = pd.DataFrame({
        "symbol": [f"S{i}" for i in range(10)],
        "open": [10.0] * 10, "high": [11.0] * 10, "low": [9.0] * 10,
        "close": [12.0] * 6 + [10.0] * 4, "volume": [100] * 10,
    })
    with pytest.raises(dq.SchemaError):
        dq.assert_ohlc_consistent(bad, "price_board")


def test_hợp_đồng_ohlc_bỏ_qua_dòng_không_khớp_lệnh_và_chấp_nhận_lệch_lẻ():
    ok = pd.DataFrame({
        "symbol": [f"S{i}" for i in range(40)],
        "open": [10.0] * 40, "high": [11.0] * 39 + [None],
        "low": [9.0] * 39 + [None],
        "close": [10.0] * 38 + [12.0, 7.0],   # 1 dòng lệch thật + 1 dòng NULL biên
        "volume": [100] * 39 + [0],
    })
    dq.assert_ohlc_consistent(ok, "price_board")   # 1/39 < 5% → im lặng


def test_upsert_prices_lưu_ref_price_và_khối_ngoại(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    warehouse.init_warehouse(con)
    df = _board([_row("TRC", 24250, 24150, 24250, 25200, 23600, 273200, 6600.88)])
    n = warehouse.upsert_prices(con, ingest_market._normalize_board(df, "2026-10-02"))
    assert n == 1
    row = con.execute(
        "SELECT close, ref_price, foreign_buy_volume, foreign_sell_value "
        "FROM raw_price_daily WHERE symbol='TRC'").fetchone()
    assert row == (24150.0, 24250.0, 10, 2e6)


def test_upsert_prices_nhận_dataframe_lịch_sử_thiếu_cột_mới(tmp_path):
    # backfill (Quote.history) không có ref_price/khối ngoại → ghi NULL, không lỗi.
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    warehouse.init_warehouse(con)
    hist = pd.DataFrame({
        "symbol": ["FPT"], "trade_date": ["2026-10-01"], "open": [63000.0],
        "high": [63100.0], "low": [62600.0], "close": [62700.0],
        "volume": [3434926], "value": [None],
    })
    assert warehouse.upsert_prices(con, hist) == 1
    assert con.execute(
        "SELECT ref_price IS NULL, foreign_buy_value IS NULL FROM raw_price_daily"
    ).fetchone() == (True, True)


def test_init_warehouse_thêm_cột_mới_vào_bảng_cũ(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute("""CREATE TABLE raw_price_daily (symbol VARCHAR, trade_date DATE,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
        value DOUBLE, loaded_at TIMESTAMP, PRIMARY KEY (symbol, trade_date))""")
    warehouse.init_warehouse(con)
    warehouse.init_warehouse(con)   # idempotent
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='raw_price_daily'").fetchall()}
    assert set(warehouse.PRICE_EXTRA_COLUMNS) <= cols
