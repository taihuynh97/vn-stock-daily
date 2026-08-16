"""Test cho raw_corporate_event — cơ chế APPEND-ONLY.

Company.events() chỉ trả 50 sự kiện gần nhất và cửa sổ đó TRƯỢT theo thời
gian: đo trên 15 mã (2026-08-16), 50 sự kiện phủ từ 1,0 năm (MWG) tới 9,9
năm (AGX) tuỳ mã đó hoạt động sự kiện nhiều hay ít. Ghi đè bảng theo mỗi
lần fetch là mất vĩnh viễn phần đã rơi khỏi cửa sổ — đây là lý do bảng này
ghi append-only thay vì INSERT OR REPLACE như raw_price_daily.
"""
import duckdb
import pandas as pd
import pytest

from src.warehouse import EVENT_COLS, init_warehouse, insert_corporate_events


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _event_row(event_id: str, symbol: str = "AAA", code: str = "DIV", **kw) -> dict:
    row = {
        "id": event_id, "symbol": symbol, "event_code": code,
        "event_name_vi": "Trả cổ tức bằng tiền mặt",
        "event_title_vi": "Trả cổ tức bằng tiền mặt - Cả năm 2025 - 500 VND",
        "category": "DIVIDEND", "public_date": "2026-04-20",
        "issue_date": "2026-04-20", "start_date": None, "end_date": None,
        "record_date": "2026-05-12", "exright_date": "2026-05-11",
        "listing_date": None, "payout_date": "2026-06-30",
        "exercise_ratio": 0.05, "value_per_share": 500.0, "action_type_vi": None,
    }
    row.update(kw)
    return row


def test_insert_them_moi_tra_dung_so_dong(con):
    df = pd.DataFrame([_event_row("e1"), _event_row("e2")])[EVENT_COLS]
    assert insert_corporate_events(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0] == 2


def test_insert_lai_cung_id_khong_them_dong_nao(con):
    df = pd.DataFrame([_event_row("e1")])[EVENT_COLS]
    insert_corporate_events(con, df)
    assert insert_corporate_events(con, df) == 0
    assert con.execute("SELECT count(*) FROM raw_corporate_event").fetchone()[0] == 1


def test_su_kien_cu_khong_bi_mat_khi_cua_so_truot(con):
    """Ca thật: lần fetch sau, sự kiện cũ nhất đã rơi khỏi cửa sổ 50 của API.

    Bảng PHẢI giữ lại nó. Đây chính là lý do tồn tại của append-only — nếu
    đổi sang INSERT OR REPLACE trên toàn bảng hoặc DELETE+INSERT thì test
    này đỏ.
    """
    lan_1 = pd.DataFrame([_event_row("cu"), _event_row("moi_1")])[EVENT_COLS]
    insert_corporate_events(con, lan_1)
    # Lần 2: "cu" đã rơi khỏi cửa sổ API, xuất hiện "moi_2"
    lan_2 = pd.DataFrame([_event_row("moi_1"), _event_row("moi_2")])[EVENT_COLS]
    assert insert_corporate_events(con, lan_2) == 1

    ids = {r[0] for r in con.execute("SELECT id FROM raw_corporate_event").fetchall()}
    assert ids == {"cu", "moi_1", "moi_2"}


def test_bo_qua_dong_id_null(con):
    df = pd.DataFrame([_event_row("e1"), _event_row(None)])[EVENT_COLS]
    assert insert_corporate_events(con, df) == 1


def test_df_rong_tra_0(con):
    assert insert_corporate_events(con, pd.DataFrame()) == 0
    assert insert_corporate_events(con, None) == 0
