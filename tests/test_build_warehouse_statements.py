"""Test cho fix trần 360 phút của GitHub Actions (final review B2).

Bối cảnh: Task 5 đo THẬT `build_warehouse.py --mode monthly` mất 767 phút,
vượt xa trần CỨNG 360 phút của GitHub-hosted runner — nghĩa là khi cron
chạy thật, GitHub sẽ giết job giữa chừng. Ba cơ chế được thêm vào
build_warehouse.py để job bị cắt không còn đồng nghĩa với mất trắng:

  1. Ghi theo lô (_ingest_statements_chunked) — lô nào xong là dữ liệu nằm
     thật trong bảng, không chờ tới cuối mới ghi một lần.
  2. Bỏ qua fetch period="year" cho mã đã có dữ liệu year còn tươi
     (_symbols_need_year_fetch) — cắt gần một nửa thời lượng tăng thêm.
  3. Đếm lỗi mạng/API (fetch_financial_statements đính kèm df.attrs) — để
     etl_load_log không còn ghi "ok" trong khi hàng trăm mã hỏng.

Việc đảo thứ tự khối BCTC xuống sau khối company_info/shareholders/officers
KHÔNG test được bằng unit test (nằm trong thân main() tuyến tính, phụ thuộc
argparse + mạng thật) — đã xác minh bằng đọc mã và ghi rõ trong báo cáo.
"""
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest

import build_warehouse as bw
from src.warehouse import STATEMENT_COLS, init_warehouse


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    init_warehouse(c)
    yield c
    c.close()


def _df(symbols, period_type="quarter", n_errors=0, total_calls=0) -> pd.DataFrame:
    """DataFrame BCTC giả, 1 dòng/mã, kèm attrs như hàm thật trả về."""
    out = pd.DataFrame([{
        "symbol": s, "statement_type": "income_statement",
        "period_type": period_type, "period_label": "2026-q2", "row_seq": 0,
        "item_id": "net_sales", "item_vi": "Doanh thu thuần",
        "item_en": "Net sales", "value": 100.0,
    } for s in symbols])[STATEMENT_COLS]
    out.attrs["n_errors"] = n_errors
    out.attrs["total_calls"] = total_calls
    return out


# --- 1) Ghi theo lô ---

def test_chunked_chia_dung_so_lo_va_cong_don_so_dong(con, monkeypatch):
    """250 mã, lô 100 -> đúng 3 lô (100/100/50), mỗi lô ghi NGAY một lần."""
    monkeypatch.setattr(bw, "STATEMENT_CHUNK_SIZE", 100)
    symbols = [f"S{i:03d}" for i in range(250)]
    seen_chunks = []

    def fake_fetch(chunk, source, period):
        seen_chunks.append(list(chunk))
        return _df(chunk, total_calls=len(chunk) * 3)

    with patch.object(bw.ingest_market, "fetch_financial_statements",
                      side_effect=fake_fetch):
        total, n_err, n_calls = bw._ingest_statements_chunked(
            con, symbols, "VCI", "quarter")

    assert [len(c) for c in seen_chunks] == [100, 100, 50]
    assert total == 250
    assert n_calls == 750
    assert n_err == 0
    # ĐÃ ghi thật vào bảng, không phải chỉ đếm
    assert con.execute(
        "SELECT count(*) FROM raw_financial_statement").fetchone()[0] == 250


def test_chunked_lo_truoc_van_con_nguyen_khi_lo_sau_no(con, monkeypatch):
    """Ca CHÍNH của fix: mô phỏng job bị GitHub giết giữa chừng (lô 3 ném
    lỗi). Trước khi sửa, upsert chỉ chạy 1 lần ở cuối nên kết quả là 0 dòng
    BCTC. Sau khi sửa, 2 lô đầu đã nằm thật trong bảng."""
    monkeypatch.setattr(bw, "STATEMENT_CHUNK_SIZE", 100)
    symbols = [f"S{i:03d}" for i in range(250)]

    def fake_fetch(chunk, source, period):
        if chunk[0] == "S200":            # lô thứ 3
            raise RuntimeError("job bị giết giữa chừng")
        return _df(chunk)

    with patch.object(bw.ingest_market, "fetch_financial_statements",
                      side_effect=fake_fetch):
        with pytest.raises(RuntimeError):
            bw._ingest_statements_chunked(con, symbols, "VCI", "quarter")

    n = con.execute("SELECT count(*) FROM raw_financial_statement").fetchone()[0]
    assert n == 200, "2 lô đầu phải còn nguyên trong bảng dù lô 3 nổ"


def test_chunked_cong_don_n_errors_tu_attrs(con, monkeypatch):
    """n_errors/total_calls của TỪNG lô phải được cộng dồn ra ngoài để
    build_warehouse ghi vào notes của etl_load_log."""
    monkeypatch.setattr(bw, "STATEMENT_CHUNK_SIZE", 2)

    def fake_fetch(chunk, source, period):
        return _df(chunk, n_errors=len(chunk), total_calls=len(chunk) * 3)

    with patch.object(bw.ingest_market, "fetch_financial_statements",
                      side_effect=fake_fetch):
        total, n_err, n_calls = bw._ingest_statements_chunked(
            con, ["A", "B", "C"], "VCI", "quarter")

    assert (total, n_err, n_calls) == (3, 3, 9)


def test_chunked_danh_sach_rong_khong_goi_fetch(con):
    with patch.object(bw.ingest_market, "fetch_financial_statements") as m:
        assert bw._ingest_statements_chunked(con, [], "VCI", "year") == (0, 0, 0)
    m.assert_not_called()


# --- 2) Bỏ qua fetch year cho mã đã có dữ liệu year còn tươi ---

def _insert_year_row(con, symbol, days_ago):
    con.execute(
        """
        INSERT INTO raw_financial_statement VALUES
        (?, 'income_statement', 'year', '2025', 0, 'net_sales',
         'Doanh thu thuần', 'Net sales', 1.0, now() - INTERVAL 1 DAY * ?)
        """,
        [symbol, days_ago],
    )


def test_year_gating_bo_qua_ma_da_co_du_lieu_year_tuoi(con):
    _insert_year_row(con, "FRESH", 10)      # còn tươi -> bỏ qua
    _insert_year_row(con, "OLD", 400)       # quá 300 ngày -> vẫn fetch
    con.execute(
        """
        INSERT INTO raw_financial_statement VALUES
        ('QONLY', 'income_statement', 'quarter', '2026-q2', 0, 'net_sales',
         'Doanh thu thuần', 'Net sales', 1.0, now())
        """
    )                                        # chỉ có quarter -> vẫn fetch year

    need = bw._symbols_need_year_fetch(con, ["FRESH", "OLD", "QONLY", "NEW"])

    assert need == ["OLD", "QONLY", "NEW"]


def test_year_gating_lan_chay_dau_tien_fetch_toan_bo(con):
    """Bảng rỗng (lần chạy đầu) -> không bỏ qua mã nào."""
    symbols = ["AAA", "BBB", "CCC"]
    assert bw._symbols_need_year_fetch(con, symbols) == symbols


def test_year_gating_giu_nguyen_thu_tu_dau_vao(con):
    _insert_year_row(con, "BBB", 5)
    assert bw._symbols_need_year_fetch(con, ["CCC", "BBB", "AAA"]) == ["CCC", "AAA"]


# --- 3) Đếm lỗi mạng/API (I4) ---

def _good_report() -> pd.DataFrame:
    return pd.DataFrame({
        "item":    ["Doanh thu thuần"],
        "item_id": ["net_sales"],
        "item_en": ["Net sales"],
        "2026-Q2": [100.0],
    })


def test_fetch_dem_loi_mang_va_dinh_kem_vao_attrs():
    """I4 (final review): lỗi mạng/timeout/RetryError phải ĐẾM ĐƯỢC, không
    chỉ in một dòng log rồi biến mất. Trước bản sửa, hàng trăm mã có thể
    hỏng mà etl_load_log vẫn ghi status='ok' — không ai biết ngoài việc tự
    grep log."""
    from src.ingest_market import fetch_financial_statements

    def side_effect_factory(symbol, source, period):
        if symbol == "NETFAIL":
            raise ConnectionError("Read timed out")   # KHÔNG phải SchemaError
        mock = MagicMock()
        mock.income_statement.return_value = _good_report()
        mock.balance_sheet.return_value = _good_report()
        mock.cash_flow.return_value = _good_report()
        return mock

    with patch("src.ingest_market.Finance", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        out = fetch_financial_statements(["NETFAIL", "OK1", "OK2"])

    assert out.attrs["n_errors"] == 3        # 3 loại báo cáo của NETFAIL
    assert out.attrs["total_calls"] == 9     # 3 mã x 3 báo cáo
    assert out.attrs["rejected"] == 0        # lỗi mạng KHÔNG phải lỗi schema
    assert set(out["symbol"]) == {"OK1", "OK2"}


def test_fetch_khong_loi_thi_n_errors_bang_khong():
    from src.ingest_market import fetch_financial_statements

    def side_effect_factory(symbol, source, period):
        mock = MagicMock()
        mock.income_statement.return_value = _good_report()
        mock.balance_sheet.return_value = _good_report()
        mock.cash_flow.return_value = _good_report()
        return mock

    with patch("src.ingest_market.Finance", side_effect=side_effect_factory), \
         patch("src.ingest_market.ingest._throttle"):
        out = fetch_financial_statements(["AAA"])

    assert out.attrs["n_errors"] == 0
    assert out.attrs["total_calls"] == 3
