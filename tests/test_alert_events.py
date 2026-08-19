"""Test cho alert_events.py — script cảnh báo sự kiện DN (C2)."""
from unittest.mock import patch

import duckdb
import pytest

import alert_events
from src.warehouse import init_warehouse, mark_events_alerted


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    # stg_corporate_event là VIEW trên raw_corporate_event thật (dbt) —
    # test dựng bảng GIẢ cùng tên/schema trực tiếp trên DuckDB in-memory,
    # không chạy dbt (đúng pattern conftest_mart.py toàn dự án).
    c.execute("""
        CREATE TABLE stg_corporate_event (
            id VARCHAR, symbol VARCHAR, event_title_vi VARCHAR,
            distribution_type VARCHAR, exright_date DATE,
            record_date DATE, payout_date DATE, public_date DATE
        );
        INSERT INTO stg_corporate_event VALUES
          ('e1','HPG','Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND',
           'CASH_DIVIDEND',DATE '2026-05-11',DATE '2026-05-12',DATE '2026-06-30',DATE '2026-04-01'),
          ('e2','VNR','Đại hội cổ đông thường niên 2026',
           'SHAREHOLDER_MEETING',NULL,NULL,NULL,DATE '2026-04-01'),
          ('e3','ZZZ','Sự kiện của mã KHÔNG nằm trong portfolio',
           'OTHER',NULL,NULL,NULL,DATE '2026-04-01');
    """)
    yield c
    c.close()


def test_fetch_unalerted_events_chi_lay_ma_trong_portfolio(con):
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    ids = {e["id"] for e in events}
    assert ids == {"e1", "e2"}
    assert "e3" not in ids


def test_fetch_unalerted_events_bo_qua_su_kien_da_bao(con):
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    ids = {e["id"] for e in events}
    assert ids == {"e2"}


def test_is_first_run_true_khi_alert_sent_log_rong(con):
    assert alert_events.is_first_run(con, ["HPG", "VNR"]) is True


def test_is_first_run_false_sau_khi_da_seed(con):
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    assert alert_events.is_first_run(con, ["HPG", "VNR"]) is False


def test_format_message_khong_co_markdown_co_du_thong_tin(con):
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    text = alert_events.format_message(events, "2026-08-19")
    assert "HPG" in text
    assert "Trả cổ tức bằng tiền mặt" in text
    assert "VNR" in text
    assert "*" not in text and "_" not in text  # không markdown


def test_main_lan_dau_khong_goi_notify_chi_seed(con, tmp_path, monkeypatch):
    pf = tmp_path / "portfolio.yml"
    pf.write_text("holdings:\n  - symbol: HPG\n  - symbol: VNR\nsource: VCI\n")
    monkeypatch.setattr(alert_events, "get_conn", lambda: con)

    with patch("alert_events.notify") as mock_notify:
        alert_events.main(portfolio_path=str(pf))
        mock_notify.send.assert_not_called()

    assert con.execute("SELECT count(*) FROM alert_sent_log").fetchone()[0] == 2


def test_main_lan_2_co_su_kien_moi_goi_notify_dung_1_lan(con, tmp_path, monkeypatch):
    pf = tmp_path / "portfolio.yml"
    pf.write_text("holdings:\n  - symbol: HPG\n  - symbol: VNR\nsource: VCI\n")
    monkeypatch.setattr(alert_events, "get_conn", lambda: con)

    # Seed trước (mô phỏng lần chạy đầu tiên đã xong)
    mark_events_alerted(con, ["e1", "e2"], {"e1": "HPG", "e2": "VNR"})
    # Sự kiện MỚI xuất hiện sau đó
    con.execute("""
        INSERT INTO stg_corporate_event VALUES
          ('e4','HPG','Phát hành cổ phiếu thưởng tỉ lệ 20%','BONUS_SHARE',
           DATE '2026-09-01',NULL,NULL,DATE '2026-08-20');
    """)

    with patch("alert_events.notify") as mock_notify:
        alert_events.main(portfolio_path=str(pf))
        mock_notify.send.assert_called_once()
        sent_text = mock_notify.send.call_args[0][0]
        assert "Phát hành cổ phiếu thưởng" in sent_text

    assert con.execute(
        "SELECT count(*) FROM alert_sent_log WHERE event_id = 'e4'"
    ).fetchone()[0] == 1


def test_main_khong_co_gi_moi_khong_goi_notify(con, tmp_path, monkeypatch):
    pf = tmp_path / "portfolio.yml"
    pf.write_text("holdings:\n  - symbol: HPG\n  - symbol: VNR\nsource: VCI\n")
    monkeypatch.setattr(alert_events, "get_conn", lambda: con)

    mark_events_alerted(con, ["e1", "e2"], {"e1": "HPG", "e2": "VNR"})

    with patch("alert_events.notify") as mock_notify:
        alert_events.main(portfolio_path=str(pf))
        mock_notify.send.assert_not_called()
