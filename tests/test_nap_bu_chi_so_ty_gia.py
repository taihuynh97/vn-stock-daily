"""Nạp bù chỉ số và tỷ giá cho các phiên bị lỡ (job daily chỉ lấy ngày chạy).

Sự cố vnstock 09–13/11/2026: giá, chỉ số, tỷ giá đều thiếu 5 phiên, nhưng
scripts/backfill_missing_days.py khi đó chỉ nạp giá."""
import duckdb
import pandas as pd
import pytest

from src import ingest_market, warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    return c


def _index_df(code, dates):
    return pd.DataFrame({"index_code": code, "trade_date": dates, "open": 1.0, "high": 1.0,
                         "low": 1.0, "close": 1700.0, "volume": 1.0})


def _fx_df(rate_date):
    return pd.DataFrame({"currency_code": ["USD"], "currency_name": ["US DOLLAR"],
                         "buy_cash": [25000.0], "buy_transfer": [25100.0], "sell": [25870.0],
                         "rate_date": [rate_date]}).reindex(columns=warehouse.EXCHANGE_RATE_COLS)


def test_nap_bu_chi_so_trong_khoang_va_ty_gia_moi_ngay_giao_dich(monkeypatch, con):
    from scripts.backfill_missing_days import backfill_index_fx

    idx_calls, fx_calls = [], []

    def fake_index(code, start, end, source="VCI"):
        idx_calls.append((code, start, end))
        # Nguồn trả thêm phiên trước start: phải bỏ, không ghi đè phiên đã có.
        return _index_df(code, ["2026-11-06", "2026-11-09", "2026-11-13"])

    def fake_fx(rate_date):
        fx_calls.append(rate_date)
        return _fx_df(rate_date)

    monkeypatch.setattr(ingest_market, "fetch_index_history", fake_index)
    monkeypatch.setattr(ingest_market, "fetch_exchange_rate", fake_fx)

    n_idx, n_fx = backfill_index_fx(con, "2026-11-09", "2026-11-15", ["VNINDEX", "VN30"])

    assert idx_calls == [("VNINDEX", "2026-11-09", "2026-11-15"), ("VN30", "2026-11-09", "2026-11-15")]
    # 09–13/11 là T2–T6; 14, 15/11 là cuối tuần — không gọi VCB.
    assert fx_calls == ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    assert n_idx == 4 and n_fx == 5
    got = con.execute("SELECT index_code, CAST(trade_date AS VARCHAR) FROM raw_index_daily "
                      "ORDER BY 1, 2").fetchall()
    assert got == [("VN30", "2026-11-09"), ("VN30", "2026-11-13"),
                   ("VNINDEX", "2026-11-09"), ("VNINDEX", "2026-11-13")]
    assert con.execute("SELECT count(DISTINCT rate_date) FROM raw_exchange_rate").fetchone()[0] == 5


def test_mot_ngay_ty_gia_loi_khong_chan_ngay_khac(monkeypatch, con):
    from scripts.backfill_missing_days import backfill_index_fx

    monkeypatch.setattr(ingest_market, "fetch_index_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(ingest_market, "fetch_exchange_rate", lambda d: (
        pd.DataFrame(columns=warehouse.EXCHANGE_RATE_COLS) if d == "2026-11-10" else _fx_df(d)))

    n_idx, n_fx = backfill_index_fx(con, "2026-11-09", "2026-11-11", ["VNINDEX"])

    assert (n_idx, n_fx) == (0, 2)
