"""Lô bảng giá lỗi nguồn được thử lại và không bị báo ok (05/10/2026: hai lô 50
mã gồm MBB, LPB bị mất, etl_load_log vẫn ghi ok)."""
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd

from src import ingest_market, warehouse


def _board(batch):
    return pd.DataFrame({"symbol": batch})


def _run(fail_calls, symbols, **kw):
    calls = []

    def factory(source):
        m = MagicMock()

        def pb(symbols_list):
            calls.append(list(symbols_list))
            if len(calls) in fail_calls:
                raise ConnectionError("Read timed out")
            return _board(symbols_list)
        m.price_board.side_effect = pb
        return m

    with patch("src.ingest_market.Trading", side_effect=factory), \
         patch("src.ingest_market.ingest._throttle"), \
         patch("src.ingest_market.time.sleep") as sl, \
         patch("src.ingest_market._normalize_board", side_effect=lambda raw, d: raw.copy()), \
         patch("src.ingest_market.dq.assert_ohlc_consistent"):
        out = ingest_market.fetch_eod_prices(symbols, batch_size=4, retry_batch_size=2, **kw)
    return out, calls, sl


def test_lô_lỗi_được_thử_lại_theo_lô_nhỏ():
    syms = [f"S{i}" for i in range(8)]
    out, calls, sl = _run({1}, syms)             # lô đầu (S0–S3) lỗi lần đầu
    assert calls[2:] == [["S0", "S1"], ["S2", "S3"]]
    assert sorted(out["symbol"]) == syms
    assert out.attrs["failed_symbols"] == []
    sl.assert_called_once()


def test_vẫn_lỗi_sau_khi_thử_lại_thì_báo_mã_lỗi():
    syms = [f"S{i}" for i in range(8)]
    out, calls, _ = _run({1, 3}, syms)            # lô đầu lỗi; lô thử lại S0–S1 cũng lỗi
    assert out.attrs["failed_symbols"] == ["S0", "S1"]
    assert sorted(out["symbol"]) == ["S2", "S3", "S4", "S5", "S6", "S7"]


def test_không_lỗi_thì_không_nghỉ():
    out, calls, sl = _run(set(), ["A", "B"])
    assert len(calls) == 1 and out.attrs["failed_symbols"] == []
    sl.assert_not_called()


def test_mọi_lô_lỗi_trả_rỗng_kèm_mã_lỗi():
    out, _, _ = _run(set(range(1, 10)), ["A", "B", "C"])
    assert out.empty and out.attrs["failed_symbols"] == ["A", "B", "C"]


def test_missing_symbols_chỉ_lấy_mã_thiếu_không_lấy_OTC():
    from scripts.backfill_missing_days import missing_symbols
    con = duckdb.connect(":memory:")
    warehouse.init_warehouse(con)
    con.execute("INSERT INTO dim_symbols (symbol, exchange) VALUES ('MBB','HOSE'), ('FPT','HOSE'), ('OLD','OTC')")
    for sym, d in [("MBB", "2026-10-02"), ("FPT", "2026-10-02"), ("OLD", "2026-10-02"),
                   ("FPT", "2026-10-05")]:
        con.execute("INSERT INTO raw_price_daily (symbol, trade_date, close) VALUES (?, CAST(? AS DATE), 1)",
                    [sym, d])
    assert missing_symbols(con, "2026-10-05", "2026-10-05") == ["MBB"]


def test_keep_rows_bỏ_ngày_ngoài_khoảng_và_dòng_đã_có():
    from scripts.backfill_missing_days import keep_rows
    con = duckdb.connect(":memory:")
    warehouse.init_warehouse(con)
    con.execute("INSERT INTO raw_price_daily (symbol, trade_date, close, ref_price) "
                "VALUES ('MBB', DATE '2026-10-06', 1, 1)")
    df = pd.DataFrame({"symbol": "MBB",
                       "trade_date": ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"]})
    # Quote.history trả thêm 01/10, 02/10 khi xin 05/10.
    assert list(keep_rows(con, df, "2026-10-05", "2026-10-06", False)["trade_date"]) == \
        ["2026-10-05", "2026-10-06"]
    # --missing-only: không ghi đè dòng bảng giá đã có (giữ ref_price).
    assert list(keep_rows(con, df, "2026-10-05", "2026-10-06", True)["trade_date"]) == ["2026-10-05"]
