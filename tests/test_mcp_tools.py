import duckdb
import pytest

from mcp_server import tools
from tests.conftest_mart import build_fake_mart


@pytest.fixture
def con(tmp_path):
    path = str(tmp_path / "mart.duckdb")
    build_fake_mart(path)
    c = duckdb.connect(path, read_only=True)
    yield c
    c.close()


def test_search_stocks_returns_ranked_with_as_of(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    assert res["profile"] == "bluechip_dividend"
    assert "price_as_of" in res and "ratio_as_of" in res
    symbols = [r["symbol"] for r in res["results"]]
    assert "CCC" not in symbols            # UPCOM + thanh khoản thấp → loại
    assert res["universe_size"] >= 1
    assert "rejected_counts" in res and "rejected_total" in res


def test_search_stocks_includes_peer_basis_and_facts(con):
    res = tools.search_stocks(con, profile="bluechip_dividend", limit=10)
    first = res["results"][0]
    assert "peer_basis" in first and "peer_count" in first
    assert "composite_score" in first
    assert "facts" in first


def test_get_stock_profile_has_quality_and_as_of(con):
    res = tools.get_stock_profile(con, "AAA")
    assert res["symbol"] == "AAA"
    assert res["com_class"] == "NONFIN"
    assert res["scores"]["quality"] == 70
    assert res["data_quality"]["data_quality_score"] == 90
    assert res["price_as_of"] == "2026-08-07"


def test_get_stock_profile_warns_on_low_quality(con):
    res = tools.get_stock_profile(con, "CCC")
    assert res["data_quality"]["data_quality_score"] == 45
    assert res["data_quality"]["reliable"] is False
    assert "thiếu lịch sử" in res["data_quality"]["quality_flags"]


def test_get_stock_profile_unknown_symbol(con):
    res = tools.get_stock_profile(con, "ZZZ")
    assert "error" in res
    assert "ZZZ" in res["error"]


def test_get_stock_profile_null_dates_return_none_not_nat(con):
    """Fix round 1 (code review): DDD có ratio_as_of NULL thật (mã mới niêm
    yết, chưa có kỳ định giá nào) và không có dòng khớp trong dim_stock nên
    listed_date cũng NULL qua LEFT JOIN. `_date_str()` từng trả chuỗi literal
    "NaT" cho các ca này (pandas.NaT lọt qua guard `isinstance(v, float)`,
    vì NaT không phải kiểu float) — phải trả None."""
    res = tools.get_stock_profile(con, "DDD")
    assert res["ratio_as_of"] is None
    assert res["listed_date"] is None
    assert res["ratio_as_of"] != "NaT"
    assert res["listed_date"] != "NaT"
    # price_as_of của DDD có giá trị thật — xác nhận ca không-NULL vẫn đúng
    # định dạng "YYYY-MM-DD" như trước, sửa guard không làm hỏng đường này.
    assert res["price_as_of"] == "2026-08-07"


def test_get_valuation_history_returns_series(con):
    res = tools.get_valuation_history(con, "AAA", years=5)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    latest = res["history"][0]
    assert latest["valuation_band"] == "rất rẻ"
    assert latest["pe_pct_own_5y"] == 0.18
    assert "ratio_as_of" in res


def test_get_financial_history_returns_quarters(con):
    res = tools.get_financial_history(con, "AAA", quarters=12)
    assert res["symbol"] == "AAA"
    assert len(res["history"]) == 2
    assert res["history"][0]["revenue_ttm"] == 1e13
    assert res["note"].startswith("Doanh thu và lợi nhuận là chỉ tiêu SUY RA")


def test_compare_stocks_warns_on_mixed_com_class(con):
    res = tools.compare_stocks(con, ["AAA", "VCB"])
    assert len(res["stocks"]) == 2
    assert res["comparable"] is False
    # Brief gốc viết test literal thường ("không tương đương") nhưng chính
    # code mẫu Step 3 của brief lại dựng cảnh báo với "KHÔNG" viết hoa để
    # nhấn mạnh — đúng quy ước đã có sẵn trong file này (vd note của
    # search_stocks: "KHÔNG cộng lại thành tổng"). Sửa test theo đúng quy
    # ước/hành vi thật thay vì hạ hoa cảnh báo xuống để né test.
    assert "KHÔNG tương đương" in res["warning"]


def test_compare_stocks_same_class_is_comparable(con):
    res = tools.compare_stocks(con, ["AAA", "CCC"])
    assert res["comparable"] is True
    assert res["warning"] == ""


def test_compare_stocks_reports_missing_symbol(con):
    res = tools.compare_stocks(con, ["AAA", "ZZZ"])
    assert res["not_found"] == ["ZZZ"]


def test_get_sector_snapshot_filters_com_class(con):
    res = tools.get_sector_snapshot(con, com_class="BANK")
    assert len(res["sectors"]) == 1
    assert res["sectors"][0]["industry_lv2"] == "Ngân hàng"
    assert res["sectors"][0]["median_pe"] == 8.6
