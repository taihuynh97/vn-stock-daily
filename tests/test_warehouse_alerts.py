"""Test cho alert_sent_log — bảng chống lặp tin của C2."""
import duckdb
import pytest

from src.warehouse import init_warehouse, mark_events_alerted


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def test_mark_events_alerted_ghi_dung_so_dong(con):
    n = mark_events_alerted(con, ["e1", "e2"], {"e1": "HPG", "e2": "VNR"})
    assert n == 2
    assert con.execute("SELECT count(*) FROM alert_sent_log").fetchone()[0] == 2


def test_mark_events_alerted_ghi_dung_symbol(con):
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    row = con.execute(
        "SELECT symbol FROM alert_sent_log WHERE event_id = 'e1'"
    ).fetchone()
    assert row[0] == "HPG"


def test_mark_events_alerted_danh_sach_rong_tra_0(con):
    assert mark_events_alerted(con, [], {}) == 0


def test_mark_events_alerted_khong_the_ghi_trung_event_id(con):
    """event_id là PRIMARY KEY — ghi lại cùng id là lỗi logic (gọi hàm 2 lần
    cho cùng sự kiện là bug ở tầng gọi), không phải ghi đè hợp lệ."""
    mark_events_alerted(con, ["e1"], {"e1": "HPG"})
    with pytest.raises(duckdb.ConstraintException):
        mark_events_alerted(con, ["e1"], {"e1": "HPG"})
