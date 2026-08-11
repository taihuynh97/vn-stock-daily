"""Test cho upsert_symbols — bao phủ C1 (final whole-branch review):

Job daily (build_warehouse.py --mode daily, T2-T6) gọi refresh_universe() +
upsert_symbols() mỗi ngày. Listing(source='VCI').all_symbols() thật (xác
minh 2026-08-10) chỉ trả 2 cột [symbol, organ_name] — KHÔNG có cột sàn — nên
refresh_universe() gán exchange=None cho TOÀN BỘ universe mỗi lần chạy daily.
Trước bản sửa này, upsert_symbols ghi đè exchange vô điều kiện
(`exchange = excluded.exchange`), nên job daily kế tiếp sau job monthly
(update_symbol_exchanges, qua raw_company_info) sẽ xoá trắng
dim_symbols.exchange mà job monthly vừa điền cho ~1.587 mã, và giữ NULL suốt
~29 ngày còn lại trong tháng.
"""
import duckdb
import pandas as pd
import pytest

from src.warehouse import init_warehouse, upsert_symbols


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def test_upsert_symbols_first_insert_sets_exchange(con):
    df = pd.DataFrame([{"symbol": "AAA", "exchange": "HOSE", "company_name": "A"}])
    n = upsert_symbols(con, df, "2026-08-01")
    got = con.execute(
        "SELECT exchange, company_name FROM dim_symbols WHERE symbol = 'AAA'"
    ).fetchone()
    assert n == 1
    assert got == ("HOSE", "A")


def test_upsert_symbols_keeps_old_exchange_when_source_reports_none(con):
    """Kịch bản Critical đã xác minh bằng thực nghiệm: monthly điền 'HOSE',
    daily kế tiếp gửi exchange=None (nguồn không trả cột sàn) -> 'HOSE' phải
    CÒN NGUYÊN sau upsert lần hai, không bị đặt lại thành NULL."""
    first = pd.DataFrame([{"symbol": "AAA", "exchange": "HOSE", "company_name": "A"}])
    upsert_symbols(con, first, "2026-07-01")   # mô phỏng monthly đã điền

    second = pd.DataFrame([{"symbol": "AAA", "exchange": None, "company_name": "A"}])
    upsert_symbols(con, second, "2026-08-01")  # mô phỏng daily kế tiếp

    exchange = con.execute(
        "SELECT exchange FROM dim_symbols WHERE symbol = 'AAA'"
    ).fetchone()[0]
    assert exchange == "HOSE"   # KHÔNG bị xoá về NULL


def test_upsert_symbols_keeps_old_company_name_when_source_reports_none(con):
    first = pd.DataFrame([{"symbol": "AAA", "exchange": "HOSE", "company_name": "Cty A"}])
    upsert_symbols(con, first, "2026-07-01")

    second = pd.DataFrame([{"symbol": "AAA", "exchange": None, "company_name": None}])
    upsert_symbols(con, second, "2026-08-01")

    name = con.execute(
        "SELECT company_name FROM dim_symbols WHERE symbol = 'AAA'"
    ).fetchone()[0]
    assert name == "Cty A"


def test_upsert_symbols_updates_last_seen_even_when_exchange_unknown(con):
    """COALESCE chỉ áp cho exchange/company_name — last_seen vẫn phải cập
    nhật theo run_date mới nhất, is_active vẫn phải là TRUE, để không vô tình
    tái tạo lỗi 'is_active không bao giờ cập nhật' (finding khác, đã ghi nợ)."""
    first = pd.DataFrame([{"symbol": "AAA", "exchange": "HOSE", "company_name": "A"}])
    upsert_symbols(con, first, "2026-07-01")

    second = pd.DataFrame([{"symbol": "AAA", "exchange": None, "company_name": None}])
    upsert_symbols(con, second, "2026-08-01")

    last_seen, is_active = con.execute(
        "SELECT last_seen, is_active FROM dim_symbols WHERE symbol = 'AAA'"
    ).fetchone()
    assert str(last_seen) == "2026-08-01"
    assert is_active is True


def test_upsert_symbols_overwrites_exchange_when_source_has_new_value(con):
    """COALESCE chỉ giữ giá trị cũ khi nguồn KHÔNG biết (None) — khi nguồn có
    giá trị mới thật (vd. mã chuyển sàn), giá trị mới vẫn phải thắng, không
    bị kẹt vĩnh viễn ở giá trị cũ."""
    first = pd.DataFrame([{"symbol": "BSR", "exchange": "UPCOM", "company_name": "BSR"}])
    upsert_symbols(con, first, "2026-01-01")

    second = pd.DataFrame([{"symbol": "BSR", "exchange": "HOSE", "company_name": "BSR"}])
    upsert_symbols(con, second, "2026-08-01")

    exchange = con.execute(
        "SELECT exchange FROM dim_symbols WHERE symbol = 'BSR'"
    ).fetchone()[0]
    assert exchange == "HOSE"


def test_upsert_symbols_first_seen_unchanged_across_upserts(con):
    first = pd.DataFrame([{"symbol": "AAA", "exchange": "HOSE", "company_name": "A"}])
    upsert_symbols(con, first, "2020-01-01")
    second = pd.DataFrame([{"symbol": "AAA", "exchange": None, "company_name": None}])
    upsert_symbols(con, second, "2026-08-01")
    first_seen = con.execute(
        "SELECT first_seen FROM dim_symbols WHERE symbol = 'AAA'"
    ).fetchone()[0]
    assert str(first_seen) == "2020-01-01"
