"""Test cho raw_financial_statement — cơ chế UPSERT theo khoá 5 cột.

Company.income_statement()/balance_sheet()/cash_flow() luôn trả TOÀN BỘ 8
kỳ gần nhất trong MỘT lần gọi (khác Company.events(), chỉ trả 50 sự kiện
gần nhất). Cửa sổ 8-kỳ CŨNG trượt theo thời gian (kỳ mới xuất hiện, kỳ cũ
nhất rơi khỏi cửa sổ) — nhưng khoá ở đây mịn tới từng KỲ
(period_label nằm trong khoá), nên INSERT OR REPLACE không đụng tới các
kỳ đã rơi khỏi cửa sổ fetch mới, khác hẳn nếu khoá chỉ tới (symbol,
statement_type) mà ghi đè cả khối.
"""
import duckdb
import pandas as pd
import pytest

from src.warehouse import STATEMENT_COLS, init_warehouse, upsert_financial_statements


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _row(symbol="AAA", statement_type="income_statement", period_type="quarter",
         period_label="2026-Q2", row_seq=0, item_id="net_sales",
         item_vi="Doanh thu thuần", value=100.0, **kw) -> dict:
    row = {
        "symbol": symbol, "statement_type": statement_type,
        "period_type": period_type, "period_label": period_label,
        "row_seq": row_seq, "item_id": item_id, "item_vi": item_vi,
        "item_en": "Net sales", "value": value,
    }
    row.update(kw)
    return row


def test_upsert_them_moi_tra_dung_so_dong(con):
    df = pd.DataFrame([_row(row_seq=0), _row(row_seq=1, item_id="cost_of_sales",
                                              item_vi="Giá vốn hàng bán")])[STATEMENT_COLS]
    assert upsert_financial_statements(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_financial_statement").fetchone()[0] == 2


def test_upsert_lai_cung_khoa_ghi_de_khong_them_dong(con):
    df = pd.DataFrame([_row(value=100.0)])[STATEMENT_COLS]
    upsert_financial_statements(con, df)
    df2 = pd.DataFrame([_row(value=200.0)])[STATEMENT_COLS]  # cùng khoá, giá trị mới
    upsert_financial_statements(con, df2)
    row = con.execute(
        "SELECT value FROM raw_financial_statement WHERE symbol='AAA'"
    ).fetchone()
    assert row[0] == 200.0
    assert con.execute("SELECT count(*) FROM raw_financial_statement").fetchone()[0] == 1


def test_ky_cu_khong_mat_khi_cua_so_8_ky_truot(con):
    """Ca thật: lần fetch sau, kỳ cũ nhất (period_label khác) đã rơi khỏi
    cửa sổ 8-kỳ trả về từ API. Bảng PHẢI giữ lại nó — đây chính là lý do
    khoá phải mịn tới period_label, không chỉ tới statement_type."""
    lan_1 = pd.DataFrame([
        _row(period_label="2024-Q3", row_seq=0),
        _row(period_label="2024-Q4", row_seq=0),
    ])[STATEMENT_COLS]
    upsert_financial_statements(con, lan_1)
    # Lần 2: "2024-Q3" đã rơi khỏi cửa sổ API, xuất hiện "2026-Q3"
    lan_2 = pd.DataFrame([
        _row(period_label="2024-Q4", row_seq=0),
        _row(period_label="2026-Q3", row_seq=0),
    ])[STATEMENT_COLS]
    upsert_financial_statements(con, lan_2)

    periods = {r[0] for r in con.execute(
        "SELECT period_label FROM raw_financial_statement"
    ).fetchall()}
    assert periods == {"2024-Q3", "2024-Q4", "2026-Q3"}


def test_hai_dong_khac_row_seq_cung_item_id_khong_de_len_nhau(con):
    """Ca thật: balance_sheet có 4 dòng cùng item_id='cost' (4 nhóm tài
    sản cố định khác nhau), phân biệt bởi row_seq. Khoá phải giữ cả 4."""
    df = pd.DataFrame([
        _row(item_id="cost", item_vi="Nguyên giá TSCĐ hữu hình",
             row_seq=30, value=1.0),
        _row(item_id="cost", item_vi="Nguyên giá tài sản thuê tài chính",
             row_seq=33, value=2.0),
        _row(item_id="cost", item_vi="Nguyên giá TSCĐ vô hình",
             row_seq=36, value=3.0),
        _row(item_id="cost", item_vi="Nguyên giá tài sản đầu tư",
             row_seq=40, value=4.0),
    ])[STATEMENT_COLS]
    assert upsert_financial_statements(con, df) == 4
    assert con.execute("SELECT count(*) FROM raw_financial_statement").fetchone()[0] == 4


def test_df_rong_tra_0(con):
    assert upsert_financial_statements(con, pd.DataFrame()) == 0
    assert upsert_financial_statements(con, None) == 0
