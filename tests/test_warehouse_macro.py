"""Test cho raw_exchange_rate (OR REPLACE) và raw_news (append-only, D)."""
import duckdb
import pandas as pd
import pytest

from src.warehouse import init_warehouse, insert_news, upsert_exchange_rate


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _rate_row(currency_code="USD", currency_name="US DOLLAR", buy_cash=25000.0,
             buy_transfer=25100.0, sell=25400.0, rate_date="2026-08-20", **kw):
    row = {"currency_code": currency_code, "currency_name": currency_name,
           "buy_cash": buy_cash, "buy_transfer": buy_transfer, "sell": sell,
           "rate_date": rate_date}
    row.update(kw)
    return row


def test_upsert_exchange_rate_ghi_dung_so_dong(con):
    df = pd.DataFrame([_rate_row(), _rate_row(currency_code="EUR")])
    assert upsert_exchange_rate(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_exchange_rate").fetchone()[0] == 2


def test_upsert_exchange_rate_cung_ngay_cung_ma_ghi_de(con):
    df1 = pd.DataFrame([_rate_row(sell=25400.0)])
    upsert_exchange_rate(con, df1)
    df2 = pd.DataFrame([_rate_row(sell=25500.0)])  # cùng khoá, giá trị mới
    upsert_exchange_rate(con, df2)
    row = con.execute(
        "SELECT sell FROM raw_exchange_rate WHERE currency_code='USD' AND rate_date='2026-08-20'"
    ).fetchone()
    assert row[0] == 25500.0
    assert con.execute("SELECT count(*) FROM raw_exchange_rate").fetchone()[0] == 1


def test_upsert_exchange_rate_buy_cash_null_giu_nguyen_null(con):
    """buy_cash NULL (nguồn trả '-') phải VẪN LÀ NULL sau khi ghi — không
    được biến thành 0.0 (khác 'không áp dụng' với 'tỷ giá bằng 0')."""
    df = pd.DataFrame([_rate_row(currency_code="DKK", buy_cash=None)])
    upsert_exchange_rate(con, df)
    row = con.execute(
        "SELECT buy_cash FROM raw_exchange_rate WHERE currency_code='DKK'"
    ).fetchone()
    assert row[0] is None


def test_upsert_exchange_rate_df_rong_tra_0(con):
    assert upsert_exchange_rate(con, pd.DataFrame()) == 0


def _news_row(id_="n1", symbol="HPG", news_title="Tiêu đề 1",
              news_short_content="Nội dung ngắn", news_source_link="https://x.com/1",
              public_date="2026-08-01T10:00:00"):
    return {"id": id_, "symbol": symbol, "news_title": news_title,
            "news_short_content": news_short_content,
            "news_source_link": news_source_link, "public_date": public_date}


def test_insert_news_them_moi_tra_dung_so_dong(con):
    df = pd.DataFrame([_news_row(id_="n1"), _news_row(id_="n2")])
    assert insert_news(con, df) == 2
    assert con.execute("SELECT count(*) FROM raw_news").fetchone()[0] == 2


def test_insert_news_khong_ghi_lai_id_da_co(con):
    """Append-only: gọi lại với id đã tồn tại KHÔNG tạo dòng mới, KHÔNG lỗi."""
    df = pd.DataFrame([_news_row(id_="n1", news_title="Bản gốc")])
    insert_news(con, df)
    df2 = pd.DataFrame([_news_row(id_="n1", news_title="Bản khác (không được ghi)"),
                        _news_row(id_="n2")])
    n = insert_news(con, df2)
    assert n == 1  # chỉ n2 thực sự mới
    assert con.execute(
        "SELECT news_title FROM raw_news WHERE id='n1'"
    ).fetchone()[0] == "Bản gốc"
    assert con.execute("SELECT count(*) FROM raw_news").fetchone()[0] == 2


def test_insert_news_tin_cu_khong_mat_khi_cua_so_truot(con):
    """Mô phỏng đúng ca thật: cửa sổ 50-tin trượt, tin cũ (n_old) rơi khỏi
    lần fetch mới nhưng PHẢI vẫn còn trong bảng."""
    insert_news(con, pd.DataFrame([_news_row(id_="n_old")]))
    insert_news(con, pd.DataFrame([_news_row(id_="n_new")]))  # n_old không có trong lần này
    ids = {r[0] for r in con.execute("SELECT id FROM raw_news").fetchall()}
    assert ids == {"n_old", "n_new"}


def test_insert_news_df_rong_tra_0(con):
    assert insert_news(con, pd.DataFrame()) == 0
    assert insert_news(con, None) == 0
