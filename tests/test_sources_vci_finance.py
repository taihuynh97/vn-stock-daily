"""BCTC chi tiết gọi thẳng VCI — đầu ra _fetch_statement_one phải khớp đáp án
chụp từ vnstock 4.0.9, kể cả THỨ TỰ DÒNG (row_seq) và item_id (dbt chọn lợi
nhuận theo item_id trong int_quarterly_profit)."""
import pytest

from src import ingest, ingest_market
from src.sources import vci_finance
from tests.vci_fixtures import assert_same, block_network, fake_http, load_expected

STMT_SYMS = ["FPT", "VCB", "SSI", "BVH"]          # NONFIN, BANK, OTHERFIN x2
TYPES = ["income_statement", "balance_sheet", "cash_flow"]
CASES = [(t, p, s) for s in STMT_SYMS for p in ("quarter", "year") for t in TYPES]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(ingest, "_throttle", lambda: None)
    vci_finance.clear_cache()
    block_network(monkeypatch)


@pytest.mark.parametrize("stype,period,symbol", CASES, ids=["-".join(c) for c in CASES])
def test_statement_khop_mau(monkeypatch, stype, period, symbol):
    fake_http(monkeypatch, f"finance_{stype}_{period}_{symbol}")
    row, status = ingest_market._fetch_statement_one(symbol, stype, "VCI", period)
    assert status == "ok"
    assert_same(row, load_expected(f"stmt_{stype}_{period}_{symbol}"))


def test_mot_ma_du_ba_bao_cao_chi_bon_lan_goi(monkeypatch):
    """3 section + 1 metrics (dùng chung, cache theo mã) thay vì 12 lần như vnstock."""
    sent = fake_http(monkeypatch, *[f"finance_{t}_quarter_FPT" for t in TYPES])
    for t in TYPES:
        _, status = ingest_market._fetch_statement_one("FPT", t, "VCI", "quarter")
        assert status == "ok"
    assert len(sent) == 4


@pytest.mark.parametrize("title,expected", [
    ("Net profit/(loss) after tax", "net_profit_loss_after_tax"),
    ("Attributable to parent company", "attributable_to_parent_company"),
    ("Cash & cash equivalents", "cash_and_cash_equivalents"),
    ("Shareholders' equity", "shareholders_equity"),
    ("1. Revenue", "revenue"),
    ("A. ASSETS", "assets"),
    ("IV. Inventories", "inventories"),
    ("2020 bonds", "n_2020_bonds"),
])
def test_item_id(title, expected):
    assert vci_finance.item_id(title) == expected


def _fake_iq(monkeypatch, section_data, metrics):
    """Giả iq_data: trả `section_data` cho section, `metrics` cho /metrics."""
    from src.sources import vci_finance as vf

    def fake(path, params=None):
        return metrics if path.endswith("/metrics") else section_data
    monkeypatch.setattr(vf, "iq_data", fake)


_MET = {"INCOME_STATEMENT": [{"field": "isa1", "titleVi": "Doanh thu", "titleEn": "Sales"}]}


def test_data_null_la_loi_khong_phai_rong(monkeypatch):
    """data: null (nguồn trục trặc/bóp lưu lượng) → "error" để thử lại; nếu
    thành "empty", mã mới niêm yết bị bỏ qua 30 ngày (EMPTY_PROBE_SKIP_DAYS).
    vnstock cũ cũng ném lỗi khi data là None."""
    _fake_iq(monkeypatch, None, _MET)
    _, status = ingest_market._fetch_statement_one("FPT", "income_statement", "VCI", "quarter")
    assert status == "error"


def test_danh_sach_ky_rong_la_empty(monkeypatch):
    """Mã thật sự chưa có BCTC: nguồn trả danh sách kỳ rỗng → "empty"."""
    _fake_iq(monkeypatch, {"quarters": [], "years": []}, _MET)
    _, status = ingest_market._fetch_statement_one("FPT", "income_statement", "VCI", "quarter")
    assert status == "empty"


def test_chi_tieu_thieu_ten_khong_ra_null(monkeypatch):
    """Chỉ tiêu không có titleVi/titleEn: item/item_id không được NULL
    (stg_financial_statement có not_null trên item_id, item_vi → cả dbt build đỏ).
    vnstock cũ fillna(0) cả cột tên."""
    met = {"INCOME_STATEMENT": [{"field": "isa1", "titleVi": "Doanh thu", "titleEn": "Sales"},
                                {"field": "isa2", "titleVi": None, "titleEn": None}]}
    rec = {"yearReport": 2026, "lengthReport": 3, "isa1": 10.0, "isa2": 5.0}
    _fake_iq(monkeypatch, {"quarters": [rec], "years": []}, met)
    df = vci_finance.statement("FPT", "income_statement", "quarter")
    assert df[["item", "item_en", "item_id"]].notna().all().all()
    assert (df[["item", "item_en", "item_id"]] != "").all().all()


def test_nguon_loi_tra_error(monkeypatch):
    from src.sources import http
    from tests.vci_fixtures import FakeResponse

    monkeypatch.setattr(http, "_send", lambda *a, **k: FakeResponse(200, '{"status":500,"code":9}'))
    _, status = ingest_market._fetch_statement_one("FPT", "income_statement", "VCI", "quarter")
    assert status == "error"
