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


def test_split_symbols_by_seed_status_chia_dung_hai_nhom(con):
    """Fix Important #2 (review round 1): thay is_first_run (kiểm gộp cả
    danh sách) bằng hàm chia TỪNG mã — mã đã có log tách khỏi mã chưa có."""
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    can_bo_sung, da_co = alert_events.split_symbols_by_seed_status(con, ["HPG", "VNR"])
    assert can_bo_sung == ["VNR"]
    assert da_co == ["HPG"]


def test_split_symbols_by_seed_status_ca_hai_deu_moi(con):
    can_bo_sung, da_co = alert_events.split_symbols_by_seed_status(con, ["HPG", "VNR"])
    assert set(can_bo_sung) == {"HPG", "VNR"}
    assert da_co == []


def test_split_symbols_by_seed_status_ca_hai_deu_da_co(con):
    mark_events_alerted(con, ["e1", "e2"], {"e1": "HPG", "e2": "VNR"})
    can_bo_sung, da_co = alert_events.split_symbols_by_seed_status(con, ["HPG", "VNR"])
    assert can_bo_sung == []
    assert set(da_co) == {"HPG", "VNR"}


def test_split_symbols_by_seed_status_danh_sach_rong(con):
    assert alert_events.split_symbols_by_seed_status(con, []) == ([], [])


def test_format_message_khong_co_markdown_co_du_thong_tin(con):
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    text = alert_events.format_message(events, "2026-08-19")
    assert "HPG" in text
    assert "Trả cổ tức bằng tiền mặt" in text
    assert "VNR" in text
    assert "*" not in text and "_" not in text  # không markdown


def test_format_message_ngay_dung_dinh_dang_khong_co_gio_khong_co_nat(con):
    """Fix Important #1 (review round 1): fetch_unalerted_events đi qua
    .df() nên cột DATE NULL trở thành pandas.NaT (KHÔNG PHẢI None) và cột
    DATE có giá trị trở thành pandas.Timestamp (kèm 00:00:00), không phải
    datetime.date thuần. Ca HPG (e1, có exright_date thật) và VNR (e2,
    exright_date NULL, fallback qua public_date) tái hiện đúng cả hai lỗi
    cùng lúc trong 1 fixture có sẵn."""
    events = alert_events.fetch_unalerted_events(con, ["HPG", "VNR"])
    text = alert_events.format_message(events, "2026-08-19")
    assert "GDKHQ: 2026-05-11" in text          # HPG — không thừa giờ 00:00:00
    assert "00:00:00" not in text
    assert "NaT" not in text                    # VNR — exright_date NULL, KHÔNG in "GDKHQ: NaT"
    assert "Ngày công bố: 2026-04-01" in text    # VNR — fallback đúng qua public_date


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


def test_main_ma_moi_duoc_seed_rieng_ma_cu_gui_binh_thuong_cung_lan_chay(
    con, tmp_path, monkeypatch
):
    """Fix Important #2 (review round 1): portfolio.yml có HPG (mã CŨ, đã
    có dòng trong alert_sent_log từ trước — mô phỏng danh mục đang chạy ổn
    định) và VNR (mã MỚI vừa được thêm vào danh mục — CHƯA từng có dòng).
    Trong CÙNG 1 lần chạy main(): VNR phải được seed riêng (sự kiện e2 của
    nó KHÔNG được đưa vào tin gửi), HPG xử lý bình thường (sự kiện mới e5
    của nó PHẢI được gửi). Trước bản sửa, is_first_run(con, symbols) kiểm
    gộp cả danh sách nên trả False ngay vì HPG đã có log — khiến VNR (dù
    hoàn toàn mới) bị coi là "đã qua giai đoạn seed" và bị dội nguyên sự
    kiện e2 (Đại hội cổ đông...) vào tin Telegram đầu tiên."""
    pf = tmp_path / "portfolio.yml"
    pf.write_text("holdings:\n  - symbol: HPG\n  - symbol: VNR\nsource: VCI\n")
    monkeypatch.setattr(alert_events, "get_conn", lambda: con)

    # HPG: mã CŨ, đã seed từ trước
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    # Sự kiện MỚI thật sự của HPG (mã cũ) -> phải được gửi
    con.execute("""
        INSERT INTO stg_corporate_event VALUES
          ('e5','HPG','Trả cổ tức đợt 2','CASH_DIVIDEND',
           DATE '2026-10-01',NULL,NULL,DATE '2026-09-01');
    """)
    # VNR: mã MỚI, chưa có dòng nào trong alert_sent_log -> sự kiện e2 của
    # nó (đã có sẵn trong fixture `con`) phải bị SEED, không được gửi.

    with patch("alert_events.notify") as mock_notify:
        alert_events.main(portfolio_path=str(pf))
        mock_notify.send.assert_called_once()
        sent_text = mock_notify.send.call_args[0][0]
        assert "Trả cổ tức đợt 2" in sent_text        # HPG — mã cũ, gửi bình thường
        assert "Đại hội cổ đông" not in sent_text      # VNR — mã mới, bị seed, KHÔNG gửi

    # Cả hai đều đã được ghi log — e5 (đã gửi) và e2 (seed, không gửi)
    assert con.execute(
        "SELECT count(*) FROM alert_sent_log WHERE event_id = 'e5'"
    ).fetchone()[0] == 1
    assert con.execute(
        "SELECT count(*) FROM alert_sent_log WHERE event_id = 'e2'"
    ).fetchone()[0] == 1
