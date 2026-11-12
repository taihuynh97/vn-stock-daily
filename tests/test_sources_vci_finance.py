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


def test_nguon_loi_tra_error(monkeypatch):
    from src.sources import http
    from tests.vci_fixtures import FakeResponse

    monkeypatch.setattr(http, "_send", lambda *a, **k: FakeResponse(200, '{"status":500,"code":9}'))
    _, status = ingest_market._fetch_statement_one("FPT", "income_statement", "VCI", "quarter")
    assert status == "error"
