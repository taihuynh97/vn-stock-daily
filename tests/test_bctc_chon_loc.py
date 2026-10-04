"""Nạp BCTC chọn lọc + ngân sách thời gian + tạm nghỉ khi nguồn treo.

Spec: docs/superpowers/specs/2026-10-04-bctc-chon-loc-design.md
"""
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest

from src import ingest_market, warehouse

NOW = datetime(2026, 10, 4, 12, 0, 0)


def _report(latest="2026-Q2"):
    """BCTC dạng wide như nguồn trả về: 2 kỳ, kỳ mới nhất = `latest`."""
    return pd.DataFrame({
        "item": ["Doanh thu thuần"], "item_en": ["Net sales"], "item_id": ["net_sales"],
        latest: [100.0], "2026-Q1": [90.0],
    })


class _Source:
    """Giả lập Finance: đếm lần gọi theo (mã, báo cáo); có thể ném lỗi."""

    def __init__(self, latest=None, fail=()):
        self.latest = latest or {}
        self.fail = set(fail)
        self.calls = []

    def __call__(self, symbol, source, period):
        m = MagicMock()
        for st in ("income_statement", "balance_sheet", "cash_flow"):
            def f(st=st):
                self.calls.append((symbol, st))
                if symbol in self.fail:
                    raise ConnectionError("Read timed out")
                return _report(self.latest.get(symbol, "2026-Q2"))
            getattr(m, st).side_effect = f
        return m


def _run(symbols, known, src, **kw):
    with patch("src.ingest_market.Finance", side_effect=src), \
         patch("src.ingest_market.ingest._throttle"):
        return ingest_market.fetch_financial_statements(
            symbols, known=known, now=NOW, **kw)


def _calls(src, sym):
    return [st for s, st in src.calls if s == sym]


# --- 1. Dò trước, tải đủ khi cần ----------------------------------------------

def test_mã_chưa_có_trong_kho_tải_đủ_3_báo_cáo():
    src = _Source()
    out = _run(["NEW"], {}, src)
    assert _calls(src, "NEW") == ["income_statement", "balance_sheet", "cash_flow"]
    assert out.attrs["n_full"] == 1 and out.attrs["n_probe_only"] == 0


def test_không_có_kỳ_mới_và_còn_hạn_chỉ_dò_1_lần():
    src = _Source(latest={"OLD": "2026-Q2"})
    known = {"OLD": {"latest_label": "2026-q2", "full_at": NOW - timedelta(days=10)}}
    out = _run(["OLD"], known, src)
    assert _calls(src, "OLD") == ["income_statement"]
    assert out.attrs["n_probe_only"] == 1 and out.attrs["total_calls"] == 1
    # Kết quả dò vẫn được ghi (cập nhật lần dò + bắt điều chỉnh của báo cáo KQKD).
    assert set(out["statement_type"]) == {"income_statement"}


def test_có_kỳ_mới_thì_tải_đủ():
    src = _Source(latest={"Q3": "2026-Q3"})
    known = {"Q3": {"latest_label": "2026-q2", "full_at": NOW - timedelta(days=10)}}
    _run(["Q3"], known, src)
    assert _calls(src, "Q3") == ["income_statement", "balance_sheet", "cash_flow"]


def test_quá_90_ngày_chưa_tải_đủ_thì_tải_lại():
    src = _Source()
    known = {"STALE": {"latest_label": "2026-q2", "full_at": NOW - timedelta(days=91)},
             "NOFULL": {"latest_label": "2026-q2", "full_at": None}}
    _run(["STALE", "NOFULL"], known, src)
    assert len(_calls(src, "STALE")) == 3
    assert len(_calls(src, "NOFULL")) == 3


def test_dò_lỗi_thì_không_gọi_tiếp_2_báo_cáo_còn_lại():
    src = _Source(fail={"BAD"})
    out = _run(["BAD", "NEW"], {}, src, pause_after=99)
    assert _calls(src, "BAD") == ["income_statement"]
    assert out.attrs["n_errors"] == 1
    assert len(_calls(src, "NEW")) == 3


def test_known_none_giữ_hành_vi_cũ():
    src = _Source()
    with patch("src.ingest_market.Finance", side_effect=src), \
         patch("src.ingest_market.ingest._throttle"):
        out = ingest_market.fetch_financial_statements(["A", "B"])
    assert len(src.calls) == 6 and out.attrs["total_calls"] == 6


# --- 3. Hạn chót ----------------------------------------------------------------

def test_quá_hạn_chót_thì_dừng_và_báo():
    src = _Source()
    out = _run(["A", "B"], {}, src, deadline=time.monotonic() - 1)
    assert src.calls == []
    assert out.attrs["stopped_early"] is True
    assert out.attrs["stop_reason"] == "het_ngan_sach"
    assert out.attrs["n_symbols_done"] == 0


# --- 4. Tạm nghỉ khi nguồn treo ----------------------------------------------------

def test_lỗi_liên_tiếp_thì_tạm_nghỉ_rồi_dừng():
    src = _Source(fail={f"S{i}" for i in range(20)})
    sleeps = []
    with patch("src.ingest_market.time.sleep", side_effect=sleeps.append):
        out = _run([f"S{i}" for i in range(20)], {}, src,
                   pause_after=2, pause_seconds=7, max_pauses=2)
    # 2 lỗi → nghỉ, 2 lỗi → nghỉ, 2 lỗi → vượt số lần nghỉ → dừng.
    assert sleeps == [7, 7]
    assert out.attrs["stopped_early"] is True
    assert out.attrs["stop_reason"] == "nguon_treo"
    assert out.attrs["n_symbols_done"] == 6


def test_một_lần_thành_công_đặt_lại_bộ_đếm_lỗi_liên_tiếp():
    src = _Source(fail={"E1", "E2"})
    sleeps = []
    with patch("src.ingest_market.time.sleep", side_effect=sleeps.append):
        out = _run(["E1", "OK", "E2"], {}, src, pause_after=2, pause_seconds=7)
    assert sleeps == []
    assert out.attrs["stopped_early"] is False


# --- 2. Mã cũ nhất đi trước ------------------------------------------------------

@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    warehouse.init_warehouse(c)
    rows = [
        # symbol, statement_type, period_label, ingested_at
        ("AAA", "income_statement", "2026-q2", "2026-10-01 10:00"),
        ("AAA", "balance_sheet", "2026-q2", "2026-08-01 10:00"),
        ("AAA", "cash_flow", "2026-q2", "2026-07-01 10:00"),
        ("BBB", "income_statement", "2026-q1", "2026-09-20 10:00"),
        ("BBB", "balance_sheet", "2026-q1", "2026-09-20 10:00"),
        ("BBB", "cash_flow", "2026-q1", "2026-09-20 10:00"),
    ]
    for s, st, pl, at in rows:
        c.execute("INSERT INTO raw_financial_statement (symbol, statement_type, period_type, "
                  "period_label, row_seq, item_id, item_vi, item_en, value, ingested_at) "
                  "VALUES (?, ?, 'quarter', ?, 0, 'x', 'x', 'x', 1.0, CAST(? AS TIMESTAMP))",
                  [s, st, pl, at])
    yield c
    c.close()


def test_statement_freshness_đọc_kỳ_mới_nhất_và_các_mốc(con):
    f = warehouse.statement_freshness(con, "quarter").set_index("symbol")
    assert f.loc["AAA", "latest_label"] == "2026-q2"
    assert str(f.loc["AAA", "probe_at"]) == "2026-10-01 10:00:00"
    # Lần tải đủ = lần CŨ HƠN trong hai báo cáo còn lại (cả hai phải mới).
    assert str(f.loc["AAA", "full_at"]) == "2026-07-01 10:00:00"
    assert f.loc["BBB", "latest_label"] == "2026-q1"


def test_thứ_tự_mã_chưa_có_trước_rồi_lần_dò_cũ_nhất(con):
    import build_warehouse as bw
    order, known = bw._order_statement_symbols(con, ["AAA", "BBB", "ZZZ", "CCC"], "quarter")
    assert order == ["CCC", "ZZZ", "BBB", "AAA"]
    assert set(known) == {"AAA", "BBB"}
    assert known["AAA"]["latest_label"] == "2026-q2"


# --- 3b. Ngân sách ở tầng job ------------------------------------------------------

def test_ngân_sách_đọc_từ_biến_môi_trường(monkeypatch):
    import build_warehouse as bw
    monkeypatch.delenv("INGEST_BUDGET_MINUTES", raising=False)
    assert bw._budget_deadline() is None and bw._over_budget(None) is False
    monkeypatch.setenv("INGEST_BUDGET_MINUTES", "0")
    d = bw._budget_deadline()
    time.sleep(0.01)
    assert d is not None and bw._over_budget(d) is True


def test_hết_ngân_sách_thì_bỏ_qua_giai_đoạn_và_ghi_partial(con):
    import build_warehouse as bw
    assert bw._skip_for_budget(con, "weekly", "raw_corporate_event",
                               time.monotonic() - 1, "2026-10-04") is True
    row = con.execute("SELECT status, notes FROM etl_load_log "
                      "WHERE target_table = 'raw_corporate_event'").fetchone()
    assert row[0] == "partial" and "het_ngan_sach" in row[1]
    assert bw._skip_for_budget(con, "weekly", "raw_corporate_event", None, "2026-10-04") is False


def test_vòng_lô_dừng_khi_nguồn_báo_dừng_sớm(con):
    import build_warehouse as bw
    calls = []

    def fake_fetch(chunk, source, period="quarter", **kw):
        calls.append(list(chunk))
        df = pd.DataFrame(columns=warehouse.STATEMENT_COLS)
        df.attrs.update(n_errors=5, total_calls=5, n_full=0, n_probe_only=0,
                        n_symbols_done=5, stopped_early=True, stop_reason="nguon_treo")
        return df

    stats = {}
    with patch("src.ingest_market.fetch_financial_statements", side_effect=fake_fetch):
        total, n_err, n_calls = bw._ingest_statements_chunked(
            con, [f"S{i:03d}" for i in range(250)], "VCI", "quarter",
            deadline=time.monotonic() + 60, selective=True, stats=stats)
    assert len(calls) == 1                     # dừng ngay sau lô đầu
    assert stats["stopped_early"] and stats["stop_reason"] == "nguon_treo"
    assert (n_err, n_calls) == (5, 5)


def test_mã_mới_mà_nguồn_không_có_bctc_chỉ_dò_1_lần():
    """316 mã hoạt động chưa từng có BCTC trong kho (đo 04/10/2026) — phần lớn
    nguồn không có dữ liệu. Dò rỗng thì không gọi tiếp 2 báo cáo còn lại, nếu
    không mỗi tuần phí ~630 lần gọi."""
    src = _Source()

    def empty_factory(symbol, source, period):
        m = MagicMock()
        for st in ("income_statement", "balance_sheet", "cash_flow"):
            def f(st=st):
                src.calls.append((symbol, st))
                return pd.DataFrame()
            getattr(m, st).side_effect = f
        return m

    with patch("src.ingest_market.Finance", side_effect=empty_factory), \
         patch("src.ingest_market.ingest._throttle"):
        out = ingest_market.fetch_financial_statements(["NODATA"], known={}, now=NOW)
    assert _calls(src, "NODATA") == ["income_statement"]
    assert out.attrs["n_probe_only"] == 1
